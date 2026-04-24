"""Pydantic event models emitted by the OrchestratorRunner.

Events are the primary mechanism for streaming live system behaviour to the
frontend (e.g. over WebSocket).  Each event is a self-contained, immutable
Pydantic model that can be serialised to JSON and pushed directly to a
connected client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


class OrchestratorEvent(BaseModel):
    """Base class for all orchestrator events."""

    event_type: str
    task_id: str
    timestamp: str = Field(default_factory=_now_iso)
    step_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the event to a plain dict suitable for JSON transport."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Run-level events
# ---------------------------------------------------------------------------


class RunStartedEvent(OrchestratorEvent):
    """Emitted once at the very beginning of a run."""

    event_type: Literal["run_started"] = "run_started"


class RunCompletedEvent(OrchestratorEvent):
    """Emitted when all steps finish successfully."""

    event_type: Literal["run_completed"] = "run_completed"


class RunFailedEvent(OrchestratorEvent):
    """Emitted when the run terminates due to a step or constraint failure."""

    event_type: Literal["run_failed"] = "run_failed"


class StopConditionEvent(OrchestratorEvent):
    """Emitted when a stop condition is triggered (max_steps_exceeded, user_interrupt, …)."""

    event_type: Literal["stop_condition_hit"] = "stop_condition_hit"


# ---------------------------------------------------------------------------
# Step-level events
# ---------------------------------------------------------------------------


class StepStartedEvent(OrchestratorEvent):
    """Emitted when the runner begins processing a step."""

    event_type: Literal["step_started"] = "step_started"


class StepCompletedEvent(OrchestratorEvent):
    """Emitted when a step finishes without errors."""

    event_type: Literal["step_completed"] = "step_completed"


class StepFailedEvent(OrchestratorEvent):
    """Emitted when a step fails (after all retries are exhausted)."""

    event_type: Literal["step_failed"] = "step_failed"


# ---------------------------------------------------------------------------
# Tool-level events
# ---------------------------------------------------------------------------


class ToolCalledEvent(OrchestratorEvent):
    """Emitted immediately before dispatching a tool call."""

    event_type: Literal["tool_called"] = "tool_called"


class ToolResultEvent(OrchestratorEvent):
    """Emitted after a tool call returns (success or failure)."""

    event_type: Literal["tool_result"] = "tool_result"


# ---------------------------------------------------------------------------
# I/O events
# ---------------------------------------------------------------------------


class FileMutatedEvent(OrchestratorEvent):
    """Emitted whenever a file is created, modified, or deleted."""

    event_type: Literal["file_mutated"] = "file_mutated"


class CommandOutputEvent(OrchestratorEvent):
    """Emitted when a terminal command produces stdout/stderr output."""

    event_type: Literal["command_output"] = "command_output"
