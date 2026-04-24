"""ReactiveLoop: dynamic mid-execution re-planning runtime.

This module adds a reactive execution layer on top of the deterministic
:class:`~orchestrator.runner.OrchestratorRunner`.  After each step completes
it observes the sandbox output, detects anomalies, and—when necessary—
triggers a partial re-plan of the *remaining* steps without restarting the
entire task.

Design goals
------------

* **Non-breaking**: wraps rather than replaces the existing runner.
* **Deterministic**: no uncontrolled loops; maximum re-plan attempts is
  bounded by ``max_replan_attempts``.
* **Preserving**: completed step outputs are never discarded; only the
  remaining (not-yet-executed) steps are mutated.
* **Observable**: emits new v2 events (``execution_anomaly_detected``,
  ``taskgraph_rewritten``, ``agent_thinking``, ``project_state_updated``)
  for frontend streaming.

Integration
-----------

The existing :class:`~orchestrator.runner.OrchestratorRunner` is used
internally.  The ``ReactiveLoop.run()`` method is a drop-in replacement that
returns the same :class:`~orchestrator.result.RunResult` type::

    from orchestrator.reactive_loop import ReactiveLoop
    from orchestrator.sandbox import SandboxEnvironment
    from runtime.project_state_graph import ProjectStateGraph
    from conversation_controller.compiler_v2 import CompilerV2

    with SandboxEnvironment() as sandbox:
        state_graph = ProjectStateGraph()
        compiler_v2 = CompilerV2(llm_client=my_client)
        loop = ReactiveLoop(
            sandbox=sandbox,
            event_callback=on_event,
            compiler_v2=compiler_v2,
            state_graph=state_graph,
        )
        result = loop.run(task_graph)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from conversation_controller.schema import ExecutionStep, TaskGraph, ToolCall
from orchestrator.events import (
    AgentThinkingEvent,
    ExecutionAnomalyDetectedEvent,
    OrchestratorEvent,
    ProjectStateUpdatedEvent,
    TaskGraphRewrittenEvent,
)
from orchestrator.result import RunResult, StepResult
from orchestrator.runner import OrchestratorRunner
from orchestrator.sandbox import SandboxEnvironment

logger = logging.getLogger(__name__)

EventCallback = Callable[[OrchestratorEvent], None]


# ---------------------------------------------------------------------------
# Anomaly detection models
# ---------------------------------------------------------------------------


class AnomalyType(str, Enum):
    """Categories of anomalies that may trigger re-planning."""

    REPEATED_FAILURE = "repeated_failure"
    UNEXPECTED_OUTPUT = "unexpected_output"
    DEPENDENCY_MISMATCH = "dependency_mismatch"


@dataclass
class AnomalyDetection:
    """Result of inspecting a step's execution output."""

    detected: bool = False
    anomaly_type: AnomalyType | None = None
    details: str = ""
    confidence: float = 0.0  # 0.0–1.0


# ---------------------------------------------------------------------------
# Anomaly heuristics
# ---------------------------------------------------------------------------

_DEPENDENCY_ERRORS = (
    "ModuleNotFoundError",
    "ImportError",
    "cannot find module",
    "No module named",
    "command not found",
    "not found",
    "ENOENT",
    "no such file",
)

_UNEXPECTED_OUTPUT_SIGNALS = (
    "Traceback (most recent call last)",
    "SyntaxError",
    "TypeError",
    "AttributeError",
    "NameError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "AssertionError",
    "FAILED",
    "ERROR",
    "CRITICAL",
)


def _detect_anomaly(
    step: ExecutionStep,
    step_result: StepResult,
    failure_counts: dict[str, int],
) -> AnomalyDetection:
    """Analyse *step_result* for anomalies.

    Checks (in priority order):

    1. Repeated failure — same step has failed more than once.
    2. Dependency mismatch — stderr contains import / module-not-found errors.
    3. Unexpected output — stderr contains known error-signal strings.

    Args:
        step: The step that was just executed.
        step_result: The outcome produced by the runner.
        failure_counts: Mapping of ``step_id`` (str) → failure count so far
            (maintained by the caller across iterations).

    Returns:
        An :class:`AnomalyDetection` instance.
    """
    step_key = str(step.step_id)

    # ── Repeated failure ──────────────────────────────────────────────
    if step_result.status == "failure":
        count = failure_counts.get(step_key, 0)
        if count >= 1:
            return AnomalyDetection(
                detected=True,
                anomaly_type=AnomalyType.REPEATED_FAILURE,
                details=(
                    f"Step {step.step_id} has failed {count + 1} time(s). "
                    f"Last error: {step_result.error or 'unknown'}"
                ),
                confidence=0.9,
            )

    # ── Collect stderr from tool results ─────────────────────────────
    stderr_combined = ""
    for tr in step_result.tool_results:
        if isinstance(tr.output, dict):
            stderr_combined += tr.output.get("stderr", "") or ""
        if tr.error:
            stderr_combined += tr.error

    if not stderr_combined:
        return AnomalyDetection()

    # ── Dependency mismatch ───────────────────────────────────────────
    for marker in _DEPENDENCY_ERRORS:
        if marker.lower() in stderr_combined.lower():
            return AnomalyDetection(
                detected=True,
                anomaly_type=AnomalyType.DEPENDENCY_MISMATCH,
                details=f"Dependency/file mismatch detected: {marker!r} in stderr.",
                confidence=0.85,
            )

    # ── Unexpected output ─────────────────────────────────────────────
    for signal in _UNEXPECTED_OUTPUT_SIGNALS:
        if signal.lower() in stderr_combined.lower():
            return AnomalyDetection(
                detected=True,
                anomaly_type=AnomalyType.UNEXPECTED_OUTPUT,
                details=f"Unexpected error signal {signal!r} in stderr.",
                confidence=0.7,
            )

    return AnomalyDetection()


# ---------------------------------------------------------------------------
# ReactiveLoop
# ---------------------------------------------------------------------------


class ReactiveLoop:
    """Wraps :class:`~orchestrator.runner.OrchestratorRunner` with reactive adaptation.

    After each step executes, the loop:

    1. Inspects the step result for anomalies.
    2. Updates the :class:`~runtime.project_state_graph.ProjectStateGraph`
       (when one is provided).
    3. If an anomaly is detected and a ``compiler_v2`` is available,
       re-plans the *remaining* steps in-place and continues execution.
    4. Emits v2 events at each decision point.

    The full task is **never** restarted; only remaining (not-yet-executed)
    steps are mutated.

    Args:
        sandbox: :class:`~orchestrator.sandbox.SandboxEnvironment` to execute
            in.  When *None* a temporary sandbox is created automatically.
        event_callback: Optional synchronous callback for all events.
        compiler_v2: Optional :class:`~conversation_controller.compiler_v2.CompilerV2`
            instance used for re-planning.  When *None*, re-planning is
            disabled (anomalies are still detected and emitted).
        state_graph: Optional :class:`~runtime.project_state_graph.ProjectStateGraph`
            for persistent memory.  When *None*, state tracking is skipped.
        max_replan_attempts: Maximum number of times the loop may trigger a
            re-plan within a single run.  Guards against infinite re-planning.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment | None = None,
        event_callback: EventCallback | None = None,
        compiler_v2=None,
        state_graph=None,
        max_replan_attempts: int = 3,
    ) -> None:
        self._sandbox = sandbox or SandboxEnvironment()
        self._event_callback = event_callback
        self._compiler_v2 = compiler_v2
        self._state_graph = state_graph
        self._max_replan_attempts = max_replan_attempts
        self._events_emitted = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task_graph: TaskGraph) -> RunResult:
        """Execute *task_graph* with reactive mid-execution adaptation.

        Steps are executed one-by-one using an internal
        :class:`~orchestrator.runner.OrchestratorRunner`.  After each step
        the result is inspected; anomalies trigger partial re-planning.

        Completed step outputs are always preserved.  Only remaining steps
        may be rewritten.

        Args:
            task_graph: A validated :class:`~conversation_controller.schema.TaskGraph`.

        Returns:
            A :class:`~orchestrator.result.RunResult` identical in shape to
            the one produced by the v1 runner.
        """
        start_ms = time.monotonic() * 1000

        # Load state graph context if available
        if self._state_graph is not None:
            ctx = self._state_graph.get_context()
            self._emit_thinking(
                task_graph.task_id,
                f"Loading project state: {self._state_graph.summary()}",
                agent="orchestrator",
            )
            self._emit(
                ProjectStateUpdatedEvent(
                    task_id=task_graph.task_id,
                    payload={"context": ctx, "phase": "pre_run"},
                )
            )

        # Topological order from v1 runner helper (re-use via delegation)
        _runner_ref = OrchestratorRunner(
            sandbox=self._sandbox,
            event_callback=self._event_callback,
        )
        ordered_steps: list[ExecutionStep] = _runner_ref._topological_sort(  # noqa: SLF001
            task_graph.execution_plan
        )

        all_step_results: list[StepResult] = []
        failure_counts: dict[str, int] = {}
        replan_count = 0
        remaining_steps = list(ordered_steps)

        while remaining_steps:
            step = remaining_steps.pop(0)

            # Run a single-step sub-graph via the v1 runner so we reuse all
            # its event emission / retry / tool-dispatch logic exactly.
            single_step_graph = task_graph.model_copy(
                update={
                    "execution_plan": [step],
                    "constraints": task_graph.constraints.model_copy(
                        update={"max_execution_steps": 1}
                    ),
                }
            )
            sub_runner = OrchestratorRunner(
                sandbox=self._sandbox,
                event_callback=self._event_callback,
            )
            sub_result = sub_runner.run(single_step_graph)
            self._events_emitted += sub_result.events_emitted

            # Extract single step result
            step_result = (
                sub_result.step_results[0]
                if sub_result.step_results
                else StepResult(step_id=step.step_id, status="skipped")
            )
            all_step_results.append(step_result)

            # Update failure counter
            step_key = str(step.step_id)
            if step_result.status == "failure":
                failure_counts[step_key] = failure_counts.get(step_key, 0) + 1

            # Update project state graph
            if self._state_graph is not None:
                exec_record = {
                    "status": step_result.status,
                    "duration_ms": step_result.duration_ms,
                    "error": step_result.error,
                }
                self._state_graph.update_execution(step.step_id, exec_record)
                if step_result.status == "failure" and step_result.error:
                    self._state_graph.record_failure(
                        step.step_id, step_result.error, context={"step": step.action}
                    )
                self._emit(
                    ProjectStateUpdatedEvent(
                        task_id=task_graph.task_id,
                        step_id=step.step_id,
                        payload={"summary": self._state_graph.summary()},
                    )
                )

            # Anomaly detection
            anomaly = _detect_anomaly(step, step_result, failure_counts)

            if anomaly.detected:
                self._emit(
                    ExecutionAnomalyDetectedEvent(
                        task_id=task_graph.task_id,
                        step_id=step.step_id,
                        payload={
                            "anomaly_type": anomaly.anomaly_type,
                            "details": anomaly.details,
                            "confidence": anomaly.confidence,
                        },
                    )
                )
                self._emit_thinking(
                    task_graph.task_id,
                    f"Anomaly detected after step {step.step_id}: {anomaly.details}",
                    agent="orchestrator",
                )

                # Trigger re-planning of remaining steps
                if (
                    remaining_steps
                    and self._compiler_v2 is not None
                    and replan_count < self._max_replan_attempts
                ):
                    replan_count += 1
                    remaining_steps = self._replan_remaining(
                        task_graph,
                        step,
                        remaining_steps,
                        anomaly,
                    )
                elif replan_count >= self._max_replan_attempts:
                    self._emit_thinking(
                        task_graph.task_id,
                        f"Max re-plan attempts ({self._max_replan_attempts}) reached; "
                        "continuing with original steps.",
                        agent="orchestrator",
                    )

        # Determine final run status
        success_count = sum(1 for r in all_step_results if r.status == "success")
        failure_count = sum(1 for r in all_step_results if r.status == "failure")
        status = "completed" if failure_count == 0 else "failed"

        return RunResult(
            task_id=task_graph.task_id,
            status=status,
            steps_completed=success_count,
            steps_total=len(ordered_steps),
            step_results=all_step_results,
            duration_ms=time.monotonic() * 1000 - start_ms,
            events_emitted=self._events_emitted,
        )

    # ------------------------------------------------------------------
    # Re-planning
    # ------------------------------------------------------------------

    def _replan_remaining(
        self,
        task_graph: TaskGraph,
        failed_step: ExecutionStep,
        remaining_steps: list[ExecutionStep],
        anomaly: AnomalyDetection,
    ) -> list[ExecutionStep]:
        """Attempt to re-plan *remaining_steps* given the detected anomaly.

        The compiler_v2 is invoked on the remaining execution plan only.
        Completed steps are preserved as-is.  The rewritten steps replace the
        remaining list in-place.

        Args:
            task_graph: The original task graph (for context).
            failed_step: The step that triggered re-planning.
            remaining_steps: Steps that have not yet been executed.
            anomaly: The detected anomaly context.

        Returns:
            Updated list of remaining steps (possibly reordered or annotated).
        """
        self._emit_thinking(
            task_graph.task_id,
            f"Re-planning {len(remaining_steps)} remaining step(s) due to: "
            f"{anomaly.anomaly_type}.",
            agent="orchestrator",
        )

        try:
            # Build a minimal sub-graph from remaining steps
            sub_graph = task_graph.model_copy(
                update={"execution_plan": remaining_steps}
            )
            enhanced = self._compiler_v2.enhance(sub_graph)
            new_steps = [s.to_execution_step() for s in enhanced.enhanced_execution_plan]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReactiveLoop re-planning failed: %s", exc)
            # Fall back to original remaining steps
            new_steps = remaining_steps

        self._emit(
            TaskGraphRewrittenEvent(
                task_id=task_graph.task_id,
                step_id=failed_step.step_id,
                payload={
                    "rewritten_steps": len(new_steps),
                    "reason": anomaly.details,
                    "remaining_steps": [s.step_id for s in new_steps],
                },
            )
        )
        return new_steps

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _emit(self, event: OrchestratorEvent) -> None:
        self._events_emitted += 1
        if self._event_callback is not None:
            self._event_callback(event)

    def _emit_thinking(self, task_id: str, message: str, agent: str = "orchestrator") -> None:
        self._emit(
            AgentThinkingEvent(
                task_id=task_id,
                payload={"message": message, "agent": agent},
            )
        )
