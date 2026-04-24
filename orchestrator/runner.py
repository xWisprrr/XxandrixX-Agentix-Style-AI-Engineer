"""OrchestratorRunner: sequential TaskGraph execution engine.

This module is the heart of the Agentix execution system.  Given a
:class:`~conversation_controller.schema.TaskGraph` produced by the
:class:`~conversation_controller.controller.ConversationController`, the
runner:

1. Topologically orders :class:`ExecutionStep` objects respecting
   ``depends_on`` constraints.
2. Iterates steps sequentially, dispatching matched
   :class:`~conversation_controller.schema.ToolCall` objects via
   :class:`~orchestrator.tools.ToolDispatcher`.
3. Enforces all ``constraints`` and ``stop_conditions`` from the graph.
4. Retries failed steps up to ``max_debug_retries_per_error`` times.
5. Emits :class:`~orchestrator.events.OrchestratorEvent` objects via an
   optional callback, enabling real-time streaming to a frontend over
   WebSocket or any other transport.

Usage::

    from orchestrator.runner import OrchestratorRunner
    from orchestrator.sandbox import SandboxEnvironment

    def on_event(event):
        print(event.event_type, event.payload)

    with SandboxEnvironment() as sandbox:
        runner = OrchestratorRunner(sandbox=sandbox, event_callback=on_event)
        result = runner.run(task_graph)

For WebSocket streaming, wrap ``run()`` in ``asyncio.to_thread()`` and
forward events from the callback through an ``asyncio.Queue``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Callable

from conversation_controller.schema import ExecutionStep, TaskGraph, ToolCall
from orchestrator.events import (
    CommandOutputEvent,
    FileMutatedEvent,
    OrchestratorEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    StepCompletedEvent,
    StepFailedEvent,
    StepStartedEvent,
    StopConditionEvent,
    ToolCalledEvent,
    ToolResultEvent,
)
from orchestrator.result import RunResult, StepResult, ToolResult
from orchestrator.sandbox import SandboxEnvironment
from orchestrator.tools import ToolDispatcher

logger = logging.getLogger(__name__)

EventCallback = Callable[[OrchestratorEvent], None]


class OrchestratorRunner:
    """Executes a :class:`TaskGraph` step-by-step, emitting live events.

    Args:
        sandbox: The :class:`SandboxEnvironment` to use.  When *None*, a
            temporary sandbox is created automatically (and **not** cleaned
            up by the runner — pass a context-managed sandbox if you need
            cleanup).
        event_callback: Optional callable invoked synchronously for every
            :class:`OrchestratorEvent` emitted during the run.  Suitable for
            feeding a WebSocket queue or logging pipeline.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        self._sandbox = sandbox or SandboxEnvironment()
        self._dispatcher = ToolDispatcher(self._sandbox)
        self._event_callback = event_callback
        self._stop_requested = False
        self._events_emitted = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task_graph: TaskGraph) -> RunResult:
        """Execute *task_graph* sequentially and return a :class:`RunResult`.

        The method respects all fields in ``task_graph.constraints`` and
        ``task_graph.stop_conditions``.  Each step fires appropriate
        :class:`OrchestratorEvent` instances via the configured callback.

        Args:
            task_graph: A validated :class:`TaskGraph` from the
                :class:`~conversation_controller.controller.ConversationController`.

        Returns:
            A :class:`RunResult` summarising the entire run.
        """
        # Capture any pre-run stop request, then reset for this run.
        pre_stopped = self._stop_requested
        self._stop_requested = False
        self._events_emitted = 0
        start_ms = time.monotonic() * 1000

        ordered_steps = self._topological_sort(task_graph.execution_plan)
        steps_total = len(ordered_steps)

        self._emit(
            RunStartedEvent(
                task_id=task_graph.task_id,
                payload={
                    "steps_total": steps_total,
                    "mode": task_graph.mode,
                    "risk_level": task_graph.risk_level,
                },
            )
        )

        if pre_stopped:
            return self._stopped(task_graph, "user_interrupt", [], steps_total, start_ms)

        step_results: list[StepResult] = []
        consumed_tool_indices: set[int] = set()

        for idx, step in enumerate(ordered_steps):
            # ── Stop conditions ────────────────────────────────────────
            if self._stop_requested:
                return self._stopped(
                    task_graph, "user_interrupt", step_results, steps_total, start_ms
                )

            if idx >= task_graph.constraints.max_execution_steps:
                self._emit(
                    StopConditionEvent(
                        task_id=task_graph.task_id,
                        step_id=step.step_id,
                        payload={"reason": "max_steps_exceeded", "step_idx": idx},
                    )
                )
                return self._stopped(
                    task_graph, "max_steps_exceeded", step_results, steps_total, start_ms
                )

            # ── Execute step (with retry) ──────────────────────────────
            matched_calls = self._match_tool_calls(
                step, task_graph.tool_calls, consumed_tool_indices
            )
            step_result = self._execute_step_with_retry(
                step=step,
                task_graph=task_graph,
                tool_calls=matched_calls,
                max_retries=task_graph.constraints.max_debug_retries_per_error,
            )
            step_results.append(step_result)

            if step_result.status == "failure":
                if "critical_build_failure" in task_graph.stop_conditions:
                    self._emit(
                        StopConditionEvent(
                            task_id=task_graph.task_id,
                            step_id=step.step_id,
                            payload={
                                "reason": "critical_build_failure",
                                "error": step_result.error,
                            },
                        )
                    )
                    self._emit(
                        RunFailedEvent(
                            task_id=task_graph.task_id,
                            payload={
                                "steps_completed": len(step_results) - 1,
                                "steps_total": steps_total,
                                "stop_reason": "critical_build_failure",
                            },
                        )
                    )
                    return RunResult(
                        task_id=task_graph.task_id,
                        status="failed",
                        stop_reason="critical_build_failure",
                        steps_completed=len(
                            [r for r in step_results if r.status == "success"]
                        ),
                        steps_total=steps_total,
                        step_results=step_results,
                        duration_ms=time.monotonic() * 1000 - start_ms,
                        events_emitted=self._events_emitted,
                    )

        # ── All steps completed ────────────────────────────────────────
        success_count = len([r for r in step_results if r.status == "success"])
        self._emit(
            RunCompletedEvent(
                task_id=task_graph.task_id,
                payload={
                    "steps_completed": success_count,
                    "steps_total": steps_total,
                    "success_criteria": task_graph.success_criteria,
                },
            )
        )
        return RunResult(
            task_id=task_graph.task_id,
            status="completed",
            steps_completed=success_count,
            steps_total=steps_total,
            step_results=step_results,
            duration_ms=time.monotonic() * 1000 - start_ms,
            events_emitted=self._events_emitted,
        )

    def stop(self) -> None:
        """Request a graceful stop after the current step finishes."""
        logger.info("Stop requested — will halt after current step.")
        self._stop_requested = True

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def _execute_step_with_retry(
        self,
        step: ExecutionStep,
        task_graph: TaskGraph,
        tool_calls: list[ToolCall],
        max_retries: int,
    ) -> StepResult:
        """Execute *step*, retrying on failure up to *max_retries* times."""
        for attempt in range(max_retries + 1):
            result = self._execute_step(step, task_graph, tool_calls, attempt)
            if result.status == "success":
                return result

            if attempt < max_retries:
                logger.info(
                    "Step %d failed (attempt %d/%d), retrying…",
                    step.step_id,
                    attempt + 1,
                    max_retries + 1,
                )
            else:
                if "repeated_test_failure_after_retry" in task_graph.stop_conditions:
                    self._emit(
                        StopConditionEvent(
                            task_id=task_graph.task_id,
                            step_id=step.step_id,
                            payload={
                                "reason": "repeated_test_failure_after_retry",
                                "step_id": step.step_id,
                                "attempts": attempt + 1,
                            },
                        )
                    )

        return result  # type: ignore[return-value]  # set on last loop iteration

    def _execute_step(
        self,
        step: ExecutionStep,
        task_graph: TaskGraph,
        tool_calls: list[ToolCall],
        attempt: int = 0,
    ) -> StepResult:
        """Execute a single step and return its result."""
        step_start = time.monotonic() * 1000

        self._emit(
            StepStartedEvent(
                task_id=task_graph.task_id,
                step_id=step.step_id,
                payload={
                    "type": step.type,
                    "action": step.action,
                    "target": step.target,
                    "attempt": attempt,
                    "tool_calls_count": len(tool_calls),
                },
            )
        )

        tool_results: list[ToolResult] = []
        failure_error: str | None = None

        if not tool_calls:
            # Derive implicit action from step type when no tool calls are matched
            implicit = self._implicit_tool_call(step)
            if implicit is not None:
                tool_calls = [implicit]

        for tc in tool_calls:
            self._emit(
                ToolCalledEvent(
                    task_id=task_graph.task_id,
                    step_id=step.step_id,
                    payload={"tool": tc.tool, "args": tc.args},
                )
            )

            tr = self._dispatcher.dispatch(tc)
            tool_results.append(tr)

            # Emit specialised sub-events for rich frontend streaming
            if tr.status == "success":
                if tc.tool in ("filesystem.write", "filesystem.read"):
                    self._emit(
                        FileMutatedEvent(
                            task_id=task_graph.task_id,
                            step_id=step.step_id,
                            payload={
                                "tool": tc.tool,
                                "path": tc.args.get("path", ""),
                                "result": tr.output,
                            },
                        )
                    )
                elif tc.tool == "terminal.run":
                    output = tr.output or {}
                    self._emit(
                        CommandOutputEvent(
                            task_id=task_graph.task_id,
                            step_id=step.step_id,
                            payload={
                                "command": tc.args.get("command", ""),
                                "stdout": output.get("stdout", ""),
                                "stderr": output.get("stderr", ""),
                                "returncode": output.get("returncode", 0),
                            },
                        )
                    )

            self._emit(
                ToolResultEvent(
                    task_id=task_graph.task_id,
                    step_id=step.step_id,
                    payload={
                        "tool": tr.tool,
                        "status": tr.status,
                        "output": tr.output,
                        "error": tr.error,
                    },
                )
            )

            if tr.status == "failure":
                failure_error = tr.error
                break

        duration = time.monotonic() * 1000 - step_start

        if failure_error:
            self._emit(
                StepFailedEvent(
                    task_id=task_graph.task_id,
                    step_id=step.step_id,
                    payload={
                        "error": failure_error,
                        "attempt": attempt,
                        "duration_ms": duration,
                    },
                )
            )
            return StepResult(
                step_id=step.step_id,
                status="failure",
                tool_results=tool_results,
                duration_ms=duration,
                error=failure_error,
                retries=attempt,
            )

        self._emit(
            StepCompletedEvent(
                task_id=task_graph.task_id,
                step_id=step.step_id,
                payload={
                    "type": step.type,
                    "target": step.target,
                    "duration_ms": duration,
                    "tools_executed": len(tool_results),
                },
            )
        )
        return StepResult(
            step_id=step.step_id,
            status="success",
            tool_results=tool_results,
            duration_ms=duration,
            retries=attempt,
        )

    # ------------------------------------------------------------------
    # Tool-call matching
    # ------------------------------------------------------------------

    def _match_tool_calls(
        self,
        step: ExecutionStep,
        all_tool_calls: list[ToolCall],
        consumed: set[int],
    ) -> list[ToolCall]:
        """Return tool_calls relevant to *step* that haven't been consumed.

        Matching strategy (in priority order):
        1. Calls whose ``args.path`` matches ``step.target`` (file steps).
        2. Calls whose ``args.command`` contains ``step.action`` (exec/test).
        3. The next unconsumed tool_call by index (positional pairing).

        Matched calls are added to *consumed* to prevent double-dispatch.
        """
        matched: list[ToolCall] = []
        matched_indices: list[int] = []

        # Strategy 1 & 2: semantic matching
        for i, tc in enumerate(all_tool_calls):
            if i in consumed:
                continue
            path_arg = tc.args.get("path", "")
            cmd_arg = tc.args.get("command", "")
            if step.target and path_arg and step.target in path_arg:
                matched_indices.append(i)
                matched.append(tc)
            elif step.action and cmd_arg and step.action.lower() in cmd_arg.lower():
                matched_indices.append(i)
                matched.append(tc)

        # Strategy 3: positional fallback (one call per step)
        if not matched:
            for i, tc in enumerate(all_tool_calls):
                if i not in consumed:
                    matched_indices.append(i)
                    matched.append(tc)
                    break

        consumed.update(matched_indices)
        return matched

    # ------------------------------------------------------------------
    # Implicit tool-call derivation
    # ------------------------------------------------------------------

    def _implicit_tool_call(self, step: ExecutionStep) -> ToolCall | None:
        """Derive a ToolCall from a step's type when no explicit call exists."""
        if step.type in ("exec", "test") and step.action:
            return ToolCall(tool="terminal.run", args={"command": step.action})
        if step.type in ("code", "modify") and step.target:
            # Write an empty placeholder so the file exists
            return ToolCall(
                tool="filesystem.write",
                args={"path": step.target, "content": f"# {step.action}\n"},
            )
        if step.type == "architecture" and step.action:
            return ToolCall(tool="terminal.run", args={"command": step.action})
        return None

    # ------------------------------------------------------------------
    # Topological sort
    # ------------------------------------------------------------------

    def _topological_sort(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        """Return *steps* ordered so that every dependency comes before its
        dependents (Kahn's algorithm).

        Steps with no ``depends_on`` are ordered by ``step_id``.  Circular
        dependencies fall back to the original step order.
        """
        if not steps:
            return []

        by_id = {s.step_id: s for s in steps}
        in_degree: dict[int, int] = defaultdict(int)
        adjacency: dict[int, list[int]] = defaultdict(list)

        for step in steps:
            if step.step_id not in in_degree:
                in_degree[step.step_id] = 0
            for dep in step.depends_on:
                if dep in by_id:
                    adjacency[dep].append(step.step_id)
                    in_degree[step.step_id] += 1

        # Start with nodes that have no dependencies, sorted by step_id
        queue: deque[int] = deque(
            sorted(sid for sid, deg in in_degree.items() if deg == 0)
        )
        ordered: list[ExecutionStep] = []

        while queue:
            sid = queue.popleft()
            ordered.append(by_id[sid])
            for neighbour in sorted(adjacency[sid]):
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(ordered) != len(steps):
            # Cycle detected — fall back to step_id order
            logger.warning("Cycle detected in execution_plan; falling back to step_id order.")
            return sorted(steps, key=lambda s: s.step_id)

        return ordered

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event: OrchestratorEvent) -> None:
        """Invoke the event callback if one is registered."""
        self._events_emitted += 1
        logger.debug("Event: %s", event.event_type)
        if self._event_callback is not None:
            self._event_callback(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stopped(
        self,
        task_graph: TaskGraph,
        reason: str,
        step_results: list[StepResult],
        steps_total: int,
        start_ms: float,
    ) -> RunResult:
        """Emit a RunFailed event and return a stopped RunResult."""
        self._emit(
            RunFailedEvent(
                task_id=task_graph.task_id,
                payload={
                    "stop_reason": reason,
                    "steps_completed": len(
                        [r for r in step_results if r.status == "success"]
                    ),
                },
            )
        )
        return RunResult(
            task_id=task_graph.task_id,
            status="stopped",
            stop_reason=reason,
            steps_completed=len([r for r in step_results if r.status == "success"]),
            steps_total=steps_total,
            step_results=step_results,
            duration_ms=time.monotonic() * 1000 - start_ms,
            events_emitted=self._events_emitted,
        )
