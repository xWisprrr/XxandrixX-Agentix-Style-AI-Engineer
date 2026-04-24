from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    DEBUGGING = "debugging"
    COMPLETE = "complete"
    ERROR = "error"


class TaskStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    code: Optional[str] = None
    language: str = "python"
    expected_output: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    output: Optional[str] = None
    files_created: List[str] = Field(default_factory=list)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    steps: List[TaskStep] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    workspace_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    result_summary: Optional[str] = None


class ConversationMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentEvent(BaseModel):
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str


class ExecutionResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    files_created: List[str] = Field(default_factory=list)
    timed_out: bool = False


class CommandResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
