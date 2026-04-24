"""Result models produced by the OrchestratorRunner after execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """The outcome of a single tool invocation."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "failure"] = "success"
    output: Any = None
    error: str | None = None


class StepResult(BaseModel):
    """The outcome of executing a single :class:`ExecutionStep`."""

    step_id: int
    status: Literal["success", "failure", "skipped"] = "success"
    tool_results: list[ToolResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    retries: int = 0


class RunResult(BaseModel):
    """The complete outcome of an orchestrator run over a full TaskGraph."""

    task_id: str
    status: Literal["completed", "failed", "stopped"] = "completed"
    stop_reason: str | None = None
    steps_completed: int = 0
    steps_total: int = 0
    step_results: list[StepResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    events_emitted: int = 0
