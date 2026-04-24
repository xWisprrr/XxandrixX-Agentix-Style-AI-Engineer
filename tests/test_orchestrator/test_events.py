"""Tests for orchestrator event models."""

from __future__ import annotations

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


class TestOrchestratorEventBase:
    """OrchestratorEvent base model."""

    def test_timestamp_auto_generated(self) -> None:
        event = RunStartedEvent(task_id="abc", payload={})
        assert event.timestamp != ""

    def test_to_dict_returns_plain_dict(self) -> None:
        event = RunStartedEvent(task_id="abc", payload={"x": 1})
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["event_type"] == "run_started"
        assert d["task_id"] == "abc"

    def test_step_id_optional(self) -> None:
        event = RunStartedEvent(task_id="abc")
        assert event.step_id is None

        event_with_step = StepStartedEvent(task_id="abc", step_id=3)
        assert event_with_step.step_id == 3


class TestEventTypes:
    """Each event subclass has the correct event_type literal."""

    def _check(self, cls: type[OrchestratorEvent], expected_type: str) -> None:
        instance = cls(task_id="t1")
        assert instance.event_type == expected_type

    def test_run_started(self) -> None:
        self._check(RunStartedEvent, "run_started")

    def test_run_completed(self) -> None:
        self._check(RunCompletedEvent, "run_completed")

    def test_run_failed(self) -> None:
        self._check(RunFailedEvent, "run_failed")

    def test_stop_condition(self) -> None:
        self._check(StopConditionEvent, "stop_condition_hit")

    def test_step_started(self) -> None:
        self._check(StepStartedEvent, "step_started")

    def test_step_completed(self) -> None:
        self._check(StepCompletedEvent, "step_completed")

    def test_step_failed(self) -> None:
        self._check(StepFailedEvent, "step_failed")

    def test_tool_called(self) -> None:
        self._check(ToolCalledEvent, "tool_called")

    def test_tool_result(self) -> None:
        self._check(ToolResultEvent, "tool_result")

    def test_file_mutated(self) -> None:
        self._check(FileMutatedEvent, "file_mutated")

    def test_command_output(self) -> None:
        self._check(CommandOutputEvent, "command_output")

    def test_payload_default_empty_dict(self) -> None:
        event = RunStartedEvent(task_id="x")
        assert event.payload == {}
