"""Tests for StepResult and RunResult models."""

from __future__ import annotations

from orchestrator.result import RunResult, StepResult, ToolResult


class TestToolResult:
    def test_defaults(self) -> None:
        tr = ToolResult(tool="filesystem.write")
        assert tr.status == "success"
        assert tr.output is None
        assert tr.error is None
        assert tr.args == {}

    def test_failure(self) -> None:
        tr = ToolResult(tool="terminal.run", status="failure", error="boom")
        assert tr.status == "failure"
        assert tr.error == "boom"


class TestStepResult:
    def test_defaults(self) -> None:
        sr = StepResult(step_id=1)
        assert sr.status == "success"
        assert sr.tool_results == []
        assert sr.duration_ms == 0.0
        assert sr.error is None
        assert sr.retries == 0

    def test_failure_state(self) -> None:
        sr = StepResult(step_id=2, status="failure", error="oops", retries=1)
        assert sr.status == "failure"
        assert sr.retries == 1


class TestRunResult:
    def test_defaults(self) -> None:
        rr = RunResult(task_id="abc")
        assert rr.status == "completed"
        assert rr.stop_reason is None
        assert rr.steps_completed == 0
        assert rr.step_results == []
        assert rr.events_emitted == 0

    def test_failed_state(self) -> None:
        rr = RunResult(task_id="x", status="failed", stop_reason="critical_build_failure")
        assert rr.status == "failed"
        assert rr.stop_reason == "critical_build_failure"

    def test_stopped_state(self) -> None:
        rr = RunResult(task_id="y", status="stopped", stop_reason="user_interrupt")
        assert rr.status == "stopped"
