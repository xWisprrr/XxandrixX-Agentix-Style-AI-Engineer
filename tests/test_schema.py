"""Tests for schema validation and defaults."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from conversation_controller.schema import (
    Constraints,
    ExecutionStep,
    TaskGraph,
    UserIntent,
)


class TestTaskGraphAutoFields:
    """TaskGraph auto-generates task_id and timestamp when not provided."""

    def test_auto_generates_task_id(self) -> None:
        graph = TaskGraph()
        assert graph.task_id != ""
        uuid.UUID(graph.task_id)  # raises if not a valid UUID

    def test_auto_generates_timestamp(self) -> None:
        graph = TaskGraph()
        assert graph.timestamp != ""
        # Must be parseable as ISO-8601
        datetime.fromisoformat(graph.timestamp)

    def test_explicit_task_id_preserved(self) -> None:
        custom_id = str(uuid.uuid4())
        graph = TaskGraph(task_id=custom_id)
        assert graph.task_id == custom_id

    def test_explicit_timestamp_preserved(self) -> None:
        custom_ts = "2024-01-01T00:00:00+00:00"
        graph = TaskGraph(timestamp=custom_ts)
        assert graph.timestamp == custom_ts

    def test_two_instances_have_different_task_ids(self) -> None:
        g1 = TaskGraph()
        g2 = TaskGraph()
        assert g1.task_id != g2.task_id


class TestConstraintsDefaults:
    """Constraints model has correct default values."""

    def test_default_max_execution_steps(self) -> None:
        c = Constraints()
        assert c.max_execution_steps == 20

    def test_default_max_debug_retries(self) -> None:
        c = Constraints()
        assert c.max_debug_retries_per_error == 1

    def test_default_no_infinite_loops(self) -> None:
        c = Constraints()
        assert c.no_infinite_loops is True

    def test_default_require_sandbox(self) -> None:
        c = Constraints()
        assert c.require_sandbox_execution is True

    def test_default_deterministic(self) -> None:
        c = Constraints()
        assert c.deterministic_output_required is True


class TestModeLiterals:
    """Mode field rejects invalid values."""

    @pytest.mark.parametrize("valid_mode", ["build", "modify", "debug", "refactor", "explain"])
    def test_valid_modes(self, valid_mode: str) -> None:
        graph = TaskGraph(mode=valid_mode)  # type: ignore[arg-type]
        assert graph.mode == valid_mode

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskGraph(mode="fly")  # type: ignore[arg-type]


class TestExecutionStepDefaults:
    """ExecutionStep has expected defaults."""

    def test_depends_on_defaults_to_empty_list(self) -> None:
        step = ExecutionStep(step_id=1, action="create main.py", target="main.py")
        assert step.depends_on == []

    def test_depends_on_can_be_set(self) -> None:
        step = ExecutionStep(step_id=2, action="run tests", target="tests/", depends_on=[1])
        assert step.depends_on == [1]


class TestUserIntentLiterals:
    """UserIntent intent_type rejects invalid values."""

    @pytest.mark.parametrize(
        "valid_type",
        ["new_project", "feature_add", "bug_fix", "refactor_request", "explanation_request"],
    )
    def test_valid_intent_types(self, valid_type: str) -> None:
        intent = UserIntent(intent_type=valid_type)  # type: ignore[arg-type]
        assert intent.intent_type == valid_type

    def test_invalid_intent_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            UserIntent(intent_type="unknown")  # type: ignore[arg-type]


class TestTaskGraphStopConditions:
    """TaskGraph default stop_conditions are correct."""

    def test_default_stop_conditions(self) -> None:
        graph = TaskGraph()
        assert "max_steps_exceeded" in graph.stop_conditions
        assert "critical_build_failure" in graph.stop_conditions
        assert "repeated_test_failure_after_retry" in graph.stop_conditions
        assert "user_interrupt" in graph.stop_conditions
