"""Pydantic v2 models for the ConversationController master output schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class UserIntent(BaseModel):
    """Represents the parsed intent from the user's raw message."""

    raw_message: str = ""
    intent_type: Literal[
        "new_project", "feature_add", "bug_fix", "refactor_request", "explanation_request"
    ] = "new_project"
    domain: str = ""
    goal_summary: str = ""
    implied_features: list[str] = Field(default_factory=list)


class ProjectState(BaseModel):
    """Represents the current state of the project being engineered."""

    project_name: str = ""
    existing_files: list[str] = Field(default_factory=list)
    current_stack: list[str] = Field(default_factory=list)
    last_step_completed: int | None = None


class ArchitecturePlan(BaseModel):
    """High-level architecture decisions for the project."""

    backend: str = ""
    frontend: str = ""
    database: str = ""
    auth_system: str = ""
    api_style: str = ""
    folder_structure: list[str] = Field(default_factory=list)
    key_system_components: list[str] = Field(default_factory=list)


class ExecutionStep(BaseModel):
    """A single step in the ordered execution plan."""

    step_id: int = 1
    type: Literal["architecture", "code", "test", "exec", "modify", "debug"] = "code"
    action: str = ""
    target: str = ""
    depends_on: list[int] = Field(default_factory=list)


class FileOperation(BaseModel):
    """Describes a file system operation to be performed."""

    operation: Literal["create", "modify", "delete", "read"] = "create"
    path: str = ""
    change_type: Literal["full_write", "incremental_patch", "append"] = "full_write"


class ToolCall(BaseModel):
    """A tool invocation with its arguments."""

    tool: Literal["filesystem.write", "filesystem.read", "terminal.run", "browser.open"] = (
        "filesystem.write"
    )
    args: dict[str, Any] = Field(default_factory=dict)


class Constraints(BaseModel):
    """Execution constraints for the task graph."""

    max_execution_steps: int = 20
    max_debug_retries_per_error: int = 1
    no_infinite_loops: bool = True
    require_sandbox_execution: bool = True
    deterministic_output_required: bool = True


class FollowUpMemory(BaseModel):
    """Memory persisted across conversation turns."""

    project_name: str = ""
    current_stack: list[str] = Field(default_factory=list)
    last_successful_step: int | None = None
    known_issues: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)


class TaskGraph(BaseModel):
    """Root model: the compiled task graph produced by the ConversationController."""

    task_id: str = Field(default="")
    timestamp: str = Field(default="")
    user_intent: UserIntent = Field(default_factory=UserIntent)
    project_state: ProjectState = Field(default_factory=ProjectState)
    mode: Literal["build", "modify", "debug", "refactor", "explain"] = "build"
    clarification_needed: bool = False
    clarifying_questions: list[str] = Field(default_factory=list)
    architecture_plan: ArchitecturePlan = Field(default_factory=ArchitecturePlan)
    execution_plan: list[ExecutionStep] = Field(default_factory=list)
    file_operations: list[FileOperation] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    risk_level: Literal["low", "medium", "high"] = "low"
    stop_conditions: list[str] = Field(
        default_factory=lambda: [
            "max_steps_exceeded",
            "critical_build_failure",
            "repeated_test_failure_after_retry",
            "user_interrupt",
        ]
    )
    success_criteria: list[str] = Field(default_factory=list)
    follow_up_memory: FollowUpMemory = Field(default_factory=FollowUpMemory)

    @model_validator(mode="before")
    @classmethod
    def auto_fill_id_and_timestamp(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Auto-generate task_id and timestamp if not provided."""
        if not values.get("task_id"):
            values["task_id"] = str(uuid.uuid4())
        if not values.get("timestamp"):
            values["timestamp"] = datetime.now(timezone.utc).isoformat()
        return values
