"""Tests for OrchestratorRunner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conversation_controller.schema import (
    Constraints,
    ExecutionStep,
    FollowUpMemory,
    TaskGraph,
    ToolCall,
)
from orchestrator.events import OrchestratorEvent
from orchestrator.result import RunResult
from orchestrator.runner import OrchestratorRunner
from orchestrator.sandbox import SandboxEnvironment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_graph(**kwargs: Any) -> TaskGraph:
    """Build a minimal TaskGraph with sensible defaults for testing."""
    defaults: dict[str, Any] = {
        "mode": "build",
        "execution_plan": [],
        "tool_calls": [],
        "constraints": Constraints(
            max_execution_steps=20,
            max_debug_retries_per_error=0,
            no_infinite_loops=True,
            require_sandbox_execution=True,
            deterministic_output_required=True,
        ),
        "stop_conditions": [
            "max_steps_exceeded",
            "critical_build_failure",
            "repeated_test_failure_after_retry",
            "user_interrupt",
        ],
        "success_criteria": [],
        "follow_up_memory": FollowUpMemory(),
    }
    defaults.update(kwargs)
    return TaskGraph(**defaults)


def make_write_step(step_id: int, target: str, depends_on: list[int] | None = None) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        type="code",
        action=f"create {target}",
        target=target,
        depends_on=depends_on or [],
    )


def make_write_call(path: str, content: str = "# placeholder") -> ToolCall:
    return ToolCall(tool="filesystem.write", args={"path": path, "content": content})


def make_exec_step(step_id: int, action: str) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        type="exec",
        action=action,
        target="",
    )


def make_exec_call(command: str) -> ToolCall:
    return ToolCall(tool="terminal.run", args={"command": command})


def collect_events(runner: OrchestratorRunner, graph: TaskGraph) -> tuple[RunResult, list[OrchestratorEvent]]:
    events: list[OrchestratorEvent] = []
    runner._event_callback = events.append
    result = runner.run(graph)
    return result, events


# ---------------------------------------------------------------------------
# Basic run behaviour
# ---------------------------------------------------------------------------


class TestRunnerBasic:
    def test_empty_plan_completes(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph()
        result = runner.run(graph)
        assert result.status == "completed"
        assert result.steps_completed == 0
        assert result.steps_total == 0

    def test_single_write_step_succeeds(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "main.py")],
            tool_calls=[make_write_call("main.py", "# main")],
        )
        result = runner.run(graph)
        assert result.status == "completed"
        assert result.steps_completed == 1
        assert (tmp_path / "main.py").read_text() == "# main"

    def test_multiple_sequential_steps(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[
                make_write_step(1, "a.py"),
                make_write_step(2, "b.py"),
            ],
            tool_calls=[
                make_write_call("a.py", "# a"),
                make_write_call("b.py", "# b"),
            ],
        )
        result = runner.run(graph)
        assert result.status == "completed"
        assert result.steps_completed == 2
        assert (tmp_path / "a.py").exists()
        assert (tmp_path / "b.py").exists()

    def test_run_result_has_task_id(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph()
        result = runner.run(graph)
        assert result.task_id == graph.task_id


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestEventEmission:
    def test_run_started_and_completed_emitted(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph()
        result, events = collect_events(runner, graph)
        types = [e.event_type for e in events]
        assert "run_started" in types
        assert "run_completed" in types

    def test_step_events_emitted_for_each_step(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "f.py")],
            tool_calls=[make_write_call("f.py")],
        )
        result, events = collect_events(runner, graph)
        types = [e.event_type for e in events]
        assert "step_started" in types
        assert "step_completed" in types

    def test_tool_called_and_result_emitted(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "x.py")],
            tool_calls=[make_write_call("x.py")],
        )
        result, events = collect_events(runner, graph)
        types = [e.event_type for e in events]
        assert "tool_called" in types
        assert "tool_result" in types

    def test_file_mutated_event_on_write(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "g.py")],
            tool_calls=[make_write_call("g.py")],
        )
        result, events = collect_events(runner, graph)
        types = [e.event_type for e in events]
        assert "file_mutated" in types

    def test_command_output_event_on_terminal_run(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_exec_step(1, "echo hi")],
            tool_calls=[make_exec_call("echo hi")],
        )
        result, events = collect_events(runner, graph)
        types = [e.event_type for e in events]
        assert "command_output" in types

    def test_events_emitted_count_in_result(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph()
        result, events = collect_events(runner, graph)
        assert result.events_emitted == len(events)


# ---------------------------------------------------------------------------
# Stop conditions
# ---------------------------------------------------------------------------


class TestStopConditions:
    def test_max_steps_exceeded_stops_run(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        # 3 steps but max = 2
        graph = make_graph(
            execution_plan=[
                make_write_step(1, "a.py"),
                make_write_step(2, "b.py"),
                make_write_step(3, "c.py"),
            ],
            tool_calls=[
                make_write_call("a.py"),
                make_write_call("b.py"),
                make_write_call("c.py"),
            ],
            constraints=Constraints(max_execution_steps=2, max_debug_retries_per_error=0),
        )
        result, events = collect_events(runner, graph)
        assert result.status == "stopped"
        assert result.stop_reason == "max_steps_exceeded"
        stop_events = [e for e in events if e.event_type == "stop_condition_hit"]
        assert len(stop_events) >= 1

    def test_critical_failure_stops_run(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        # A failing command with no retries triggers critical_build_failure
        graph = make_graph(
            execution_plan=[make_exec_step(1, "exit 1")],
            tool_calls=[make_exec_call("exit 1")],
            constraints=Constraints(max_debug_retries_per_error=0),
        )
        result, events = collect_events(runner, graph)
        assert result.status == "failed"
        assert result.stop_reason == "critical_build_failure"

    def test_user_interrupt_stops_run(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        runner.stop()  # request stop before run starts
        graph = make_graph(
            execution_plan=[make_write_step(1, "f.py")],
            tool_calls=[make_write_call("f.py")],
        )
        result = runner.run(graph)
        assert result.status == "stopped"
        assert result.stop_reason == "user_interrupt"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    def test_step_retried_on_failure(self, tmp_path: Path) -> None:
        """A failing step is retried up to max_debug_retries_per_error times."""
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        # exit 1 will always fail — with 1 retry, step should fail after 2 attempts
        graph = make_graph(
            execution_plan=[make_exec_step(1, "exit 1")],
            tool_calls=[make_exec_call("exit 1")],
            constraints=Constraints(max_debug_retries_per_error=1),
            stop_conditions=["repeated_test_failure_after_retry"],
        )
        result, events = collect_events(runner, graph)
        step_results = result.step_results
        assert len(step_results) == 1
        assert step_results[0].status == "failure"
        assert step_results[0].retries >= 1

    def test_successful_retry_counts_as_success(self, tmp_path: Path) -> None:
        """
        A step that succeeds on first try (retries=0) should record success.
        """
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "ok.py")],
            tool_calls=[make_write_call("ok.py", "# ok")],
            constraints=Constraints(max_debug_retries_per_error=1),
        )
        result = runner.run(graph)
        assert result.status == "completed"
        assert result.step_results[0].retries == 0


# ---------------------------------------------------------------------------
# Topological ordering
# ---------------------------------------------------------------------------


class TestTopologicalOrdering:
    def test_dependency_respected(self, tmp_path: Path) -> None:
        """Step 2 depends on step 1 — step 1 must be executed first."""
        sb = SandboxEnvironment(work_dir=tmp_path)
        execution_order: list[int] = []

        def on_event(event: OrchestratorEvent) -> None:
            if event.event_type == "step_started":
                execution_order.append(event.step_id)

        runner = OrchestratorRunner(sandbox=sb, event_callback=on_event)
        graph = make_graph(
            # Declare step 2 first to ensure ordering is by depends_on, not list order
            execution_plan=[
                make_write_step(2, "b.py", depends_on=[1]),
                make_write_step(1, "a.py"),
            ],
            tool_calls=[
                make_write_call("a.py"),
                make_write_call("b.py"),
            ],
        )
        runner.run(graph)
        assert execution_order == [1, 2]

    def test_no_deps_ordered_by_step_id(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        execution_order: list[int] = []

        def on_event(event: OrchestratorEvent) -> None:
            if event.event_type == "step_started":
                execution_order.append(event.step_id)

        runner = OrchestratorRunner(sandbox=sb, event_callback=on_event)
        graph = make_graph(
            execution_plan=[
                make_write_step(3, "c.py"),
                make_write_step(1, "a.py"),
                make_write_step(2, "b.py"),
            ],
            tool_calls=[
                make_write_call("a.py"),
                make_write_call("b.py"),
                make_write_call("c.py"),
            ],
        )
        runner.run(graph)
        assert execution_order == [1, 2, 3]


# ---------------------------------------------------------------------------
# Implicit step actions
# ---------------------------------------------------------------------------


class TestImplicitActions:
    def test_exec_step_runs_action_as_command(self, tmp_path: Path) -> None:
        """An exec step with no matching tool_call derives terminal.run implicitly."""
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_exec_step(1, "echo implicit")],
            tool_calls=[],  # no explicit tool calls
        )
        result, events = collect_events(runner, graph)
        assert result.status == "completed"
        cmd_events = [e for e in events if e.event_type == "command_output"]
        assert any("implicit" in e.payload.get("stdout", "") for e in cmd_events)

    def test_code_step_creates_placeholder_file(self, tmp_path: Path) -> None:
        """A code step with no matching tool_call writes a placeholder file."""
        sb = SandboxEnvironment(work_dir=tmp_path)
        runner = OrchestratorRunner(sandbox=sb)
        graph = make_graph(
            execution_plan=[make_write_step(1, "placeholder.py")],
            tool_calls=[],
        )
        result = runner.run(graph)
        assert result.status == "completed"
        assert (tmp_path / "placeholder.py").exists()
