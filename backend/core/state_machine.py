from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Set


class TaskState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    DEBUGGING = "debugging"
    COMPLETE = "complete"
    ERROR = "error"


# Valid state transitions
_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.IDLE: {TaskState.PLANNING, TaskState.ERROR},
    TaskState.PLANNING: {TaskState.EXECUTING, TaskState.ERROR},
    TaskState.EXECUTING: {TaskState.TESTING, TaskState.DEBUGGING, TaskState.ERROR},
    TaskState.TESTING: {TaskState.COMPLETE, TaskState.DEBUGGING, TaskState.EXECUTING, TaskState.ERROR},
    TaskState.DEBUGGING: {TaskState.EXECUTING, TaskState.ERROR},
    TaskState.COMPLETE: {TaskState.IDLE},
    TaskState.ERROR: {TaskState.IDLE},
}


class StateMachineError(Exception):
    pass


class StateMachine:
    def __init__(self, initial_state: TaskState = TaskState.IDLE) -> None:
        self._state = initial_state
        self._history: List[TaskState] = [initial_state]

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def history(self) -> List[TaskState]:
        return list(self._history)

    def can_transition(self, new_state: TaskState) -> bool:
        return new_state in _TRANSITIONS.get(self._state, set())

    def transition(self, new_state: TaskState) -> None:
        if not self.can_transition(new_state):
            raise StateMachineError(
                f"Invalid transition from {self._state} to {new_state}. "
                f"Allowed: {_TRANSITIONS.get(self._state, set())}"
            )
        self._state = new_state
        self._history.append(new_state)

    def reset(self) -> None:
        self._state = TaskState.IDLE
        self._history = [TaskState.IDLE]

    def is_terminal(self) -> bool:
        return self._state in {TaskState.COMPLETE, TaskState.ERROR}

    def __repr__(self) -> str:
        return f"StateMachine(state={self._state}, history={self._history})"
