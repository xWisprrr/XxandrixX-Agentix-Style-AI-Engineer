"""Shared data models for the Agentix system."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"


class EventType(str, Enum):
    # Chat messages
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    # Agent status
    AGENT_STATUS = "agent_status"
    # File operations
    FILE_CREATED = "file_created"
    FILE_UPDATED = "file_updated"
    FILE_TREE = "file_tree"
    # Execution
    EXECUTION_START = "execution_start"
    EXECUTION_OUTPUT = "execution_output"
    EXECUTION_ERROR = "execution_error"
    EXECUTION_DONE = "execution_done"
    # Planning
    PLAN_CREATED = "plan_created"
    PLAN_STEP_START = "plan_step_start"
    PLAN_STEP_DONE = "plan_step_done"
    # System
    ERROR = "error"
    DONE = "done"
    HEARTBEAT = "heartbeat"


class ProjectState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    CODING = "coding"
    EXECUTING = "executing"
    DEBUGGING = "debugging"
    COMPLETE = "complete"
    ERROR = "error"


class WSMessage(BaseModel):
    """Message sent/received over WebSocket."""

    event: EventType
    data: Any = None
    agent: Optional[AgentRole] = None
    timestamp: float = Field(default_factory=time.time)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    agent: Optional[AgentRole] = None
    timestamp: float = Field(default_factory=time.time)


class PlanStep(BaseModel):
    index: int
    title: str
    description: str
    status: str = "pending"  # pending | active | done | failed


class ProjectPlan(BaseModel):
    goal: str
    steps: list[PlanStep]
    created_at: float = Field(default_factory=time.time)


class GeneratedFile(BaseModel):
    path: str
    content: str
    language: str = "text"


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    duration: float = 0.0


class IncomingUserMessage(BaseModel):
    message: str
    project_id: Optional[str] = None
