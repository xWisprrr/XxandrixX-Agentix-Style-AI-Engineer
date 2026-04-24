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


# ---------------------------------------------------------------------------
# v2 events — reactive runtime and live agent experience
# ---------------------------------------------------------------------------


class AgentThinkingEvent(OrchestratorEvent):
    """Emitted to stream the agent's reasoning narration to the frontend.

    ``payload`` should contain at least a ``"message"`` key with a short
    human-readable description of what the agent is currently doing, and an
    optional ``"agent"`` key identifying the active agent role
    (e.g. ``"planner"``, ``"coder"``, ``"debugger"``).
    """

    event_type: Literal["agent_thinking"] = "agent_thinking"


class ExecutionAnomalyDetectedEvent(OrchestratorEvent):
    """Emitted when the ReactiveLoop detects an anomaly after a step.

    ``payload`` expected keys:

    * ``anomaly_type`` — one of ``"repeated_failure"``,
      ``"unexpected_output"``, ``"dependency_mismatch"``.
    * ``details`` — human-readable description of the anomaly.
    * ``affected_step_id`` — the step ID that triggered detection.
    """

    event_type: Literal["execution_anomaly_detected"] = "execution_anomaly_detected"


class TaskGraphRewrittenEvent(OrchestratorEvent):
    """Emitted when the ReactiveLoop rewrites remaining TaskGraph steps.

    ``payload`` expected keys:

    * ``rewritten_steps`` — count of steps mutated.
    * ``reason`` — brief explanation of why re-planning was triggered.
    * ``remaining_steps`` — list of step IDs still to be executed.
    """

    event_type: Literal["taskgraph_rewritten"] = "taskgraph_rewritten"


class ProjectStateUpdatedEvent(OrchestratorEvent):
    """Emitted after the ProjectStateGraph is updated.

    ``payload`` should contain the output of
    :meth:`~runtime.project_state_graph.ProjectStateGraph.get_context` or
    a lightweight summary thereof.
    """

    event_type: Literal["project_state_updated"] = "project_state_updated"
