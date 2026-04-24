"""Tests for ConversationController with a mock LLM client."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from conversation_controller.controller import ConversationController
from conversation_controller.schema import TaskGraph


def _make_minimal_task_graph_dict(**overrides: Any) -> dict:
    """Return a minimal valid TaskGraph dict for mock LLM responses."""
    data: dict = {
        "task_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_intent": {
            "raw_message": "Build a hello-world Flask app",
            "intent_type": "new_project",
            "domain": "web",
            "goal_summary": "Create a minimal Flask web application.",
            "implied_features": ["hello world endpoint"],
        },
        "project_state": {
            "project_name": "hello-flask",
            "existing_files": [],
            "current_stack": ["Python", "Flask"],
            "last_step_completed": None,
        },
        "mode": "build",
        "clarification_needed": False,
        "clarifying_questions": [],
        "architecture_plan": {
            "backend": "Flask",
            "frontend": "N/A",
            "database": "N/A",
            "auth_system": "N/A",
            "api_style": "REST",
            "folder_structure": ["app/", "app/main.py"],
            "key_system_components": ["Flask app factory"],
        },
        "execution_plan": [
            {
                "step_id": 1,
                "type": "code",
                "action": "Create main Flask application file",
                "target": "app/main.py",
                "depends_on": [],
            }
        ],
        "file_operations": [
            {
                "operation": "create",
                "path": "app/main.py",
                "change_type": "full_write",
            }
        ],
        "tool_calls": [
            {
                "tool": "filesystem.write",
                "args": {"path": "app/main.py", "content": "# Flask app"},
            }
        ],
        "constraints": {
            "max_execution_steps": 20,
            "max_debug_retries_per_error": 1,
            "no_infinite_loops": True,
            "require_sandbox_execution": True,
            "deterministic_output_required": True,
        },
        "risk_level": "low",
        "stop_conditions": [
            "max_steps_exceeded",
            "critical_build_failure",
            "repeated_test_failure_after_retry",
            "user_interrupt",
        ],
        "success_criteria": ["GET / returns 200"],
        "follow_up_memory": {
            "project_name": "hello-flask",
            "current_stack": ["Python", "Flask"],
            "last_successful_step": 1,
            "known_issues": [],
            "user_preferences": [],
        },
    }
    data.update(overrides)
    return data


def _build_mock_client(response_dict: dict) -> Any:
    """Construct a duck-typed mock LLM client that returns ``response_dict`` as JSON."""
    content = json.dumps(response_dict)
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    completion = SimpleNamespace(choices=[choice])

    class _MockClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs: Any) -> Any:
                    return completion

    return _MockClient()


class TestConversationControllerCompile:
    """Tests for ConversationController.compile()."""

    def test_compile_returns_task_graph(self) -> None:
        mock_data = _make_minimal_task_graph_dict()
        controller = ConversationController(llm_client=_build_mock_client(mock_data))

        result = controller.compile("Build a hello-world Flask app")

        assert isinstance(result, TaskGraph)

    def test_compile_task_id_is_uuid(self) -> None:
        mock_data = _make_minimal_task_graph_dict()
        controller = ConversationController(llm_client=_build_mock_client(mock_data))

        result = controller.compile("Build a hello-world Flask app")

        uuid.UUID(result.task_id)  # raises ValueError if not valid UUID

    def test_compile_mode_matches_response(self) -> None:
        mock_data = _make_minimal_task_graph_dict(mode="build")
        controller = ConversationController(llm_client=_build_mock_client(mock_data))

        result = controller.compile("Build a hello-world Flask app")

        assert result.mode == "build"

    def test_memory_updated_after_compile(self) -> None:
        mock_data = _make_minimal_task_graph_dict()
        controller = ConversationController(llm_client=_build_mock_client(mock_data))

        assert controller.memory.to_context() == {}

        controller.compile("Build a hello-world Flask app")

        ctx = controller.memory.to_context()
        assert ctx.get("project_name") == "hello-flask"
        assert "Python" in ctx.get("current_stack", [])

    def test_memory_accumulates_across_calls(self) -> None:
        mock_data1 = _make_minimal_task_graph_dict()
        mock_data2 = _make_minimal_task_graph_dict(
            follow_up_memory={
                "project_name": "hello-flask",
                "current_stack": ["Python", "Flask", "SQLite"],
                "last_successful_step": 2,
                "known_issues": [],
                "user_preferences": [],
            }
        )
        client1 = _build_mock_client(mock_data1)
        client2 = _build_mock_client(mock_data2)

        controller = ConversationController(llm_client=client1)
        controller.compile("Build a hello-world Flask app")

        controller._client = client2  # swap client for second call
        controller.compile("Add SQLite support")

        ctx = controller.memory.to_context()
        assert "SQLite" in ctx.get("current_stack", [])
        assert ctx.get("last_successful_step") == 2

    def test_compile_invalid_json_raises_value_error(self) -> None:
        class _BadClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs: Any) -> Any:
                        message = SimpleNamespace(content="NOT JSON {{{")
                        choice = SimpleNamespace(message=message)
                        return SimpleNamespace(choices=[choice])

        controller = ConversationController(llm_client=_BadClient())
        with pytest.raises(ValueError, match="invalid JSON"):
            controller.compile("anything")


class TestConversationControllerMemory:
    """Tests for memory management in ConversationController."""

    def test_reset_memory_clears_state(self) -> None:
        mock_data = _make_minimal_task_graph_dict()
        controller = ConversationController(llm_client=_build_mock_client(mock_data))

        controller.compile("Build a hello-world Flask app")
        assert controller.memory.to_context() != {}

        controller.reset_memory()
        assert controller.memory.to_context() == {}

    def test_memory_property_returns_conversation_memory(self) -> None:
        from conversation_controller.memory import ConversationMemory

        controller = ConversationController(llm_client=_build_mock_client({}))
        assert isinstance(controller.memory, ConversationMemory)
