"""
Tests for the Agentix system.
Run with: pytest tests/ -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Models ────────────────────────────────────────────────────────────────────

from backend.models import (
    AgentRole,
    EventType,
    ExecutionResult,
    GeneratedFile,
    PlanStep,
    ProjectPlan,
    ProjectState,
    WSMessage,
)


class TestModels:
    def test_ws_message_creation(self):
        msg = WSMessage(event=EventType.AGENT_MESSAGE, data={"content": "hello"}, agent=AgentRole.PLANNER)
        assert msg.event == "agent_message"
        assert msg.data["content"] == "hello"
        assert msg.agent == "planner"
        assert msg.id  # auto-generated uuid

    def test_ws_message_json_serializable(self):
        msg = WSMessage(event=EventType.FILE_CREATED, data={"path": "main.py"})
        json_str = msg.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["event"] == "file_created"

    def test_project_plan(self):
        plan = ProjectPlan(
            goal="build a todo app",
            steps=[
                PlanStep(index=0, title="Setup", description="Create project structure"),
                PlanStep(index=1, title="Implement", description="Write logic"),
            ],
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].status == "pending"
        assert plan.steps[1].index == 1

    def test_plan_step_status_transitions(self):
        step = PlanStep(index=0, title="Step 1", description="Do something")
        step.status = "active"
        assert step.status == "active"
        step.status = "done"
        assert step.status == "done"

    def test_generated_file(self):
        gf = GeneratedFile(path="src/main.py", content='print("hi")', language="python")
        assert gf.path == "src/main.py"
        assert gf.language == "python"

    def test_execution_result(self):
        result = ExecutionResult(stdout="hello\n", stderr="", exit_code=0, duration=0.5)
        assert result.exit_code == 0
        assert not result.timed_out

    def test_project_states(self):
        for state in ProjectState:
            assert isinstance(state.value, str)


# ── Agents: Planner ──────────────────────────────────────────────────────────

from backend.agents.planner import _parse_steps


class TestPlanner:
    def test_parse_valid_json(self):
        raw = json.dumps({
            "steps": [
                {"title": "Setup", "description": "Create project structure"},
                {"title": "Build API", "description": "Write endpoints"},
                {"title": "Tests", "description": "Write tests"},
            ]
        })
        steps = _parse_steps(raw)
        assert len(steps) == 3
        assert steps[0].title == "Setup"
        assert steps[1].title == "Build API"
        assert steps[2].index == 2

    def test_parse_json_with_markdown_fences(self):
        raw = "```json\n" + json.dumps({"steps": [{"title": "Step 1", "description": "Do it"}]}) + "\n```"
        steps = _parse_steps(raw)
        assert len(steps) == 1
        assert steps[0].title == "Step 1"

    def test_parse_invalid_json_returns_fallback(self):
        steps = _parse_steps("this is not valid json at all")
        assert len(steps) == 3  # fallback always returns 3 steps
        assert all(isinstance(s, PlanStep) for s in steps)

    def test_parse_empty_steps(self):
        raw = json.dumps({"steps": []})
        steps = _parse_steps(raw)
        assert steps == []

    def test_step_indices(self):
        raw = json.dumps({"steps": [
            {"title": f"Step {i}", "description": f"Description {i}"} for i in range(5)
        ]})
        steps = _parse_steps(raw)
        for i, step in enumerate(steps):
            assert step.index == i


# ── Agents: Coder ────────────────────────────────────────────────────────────

from backend.agents.coder import _guess_language, _lang_to_ext, _parse_files, _summarize_existing


class TestCoder:
    def test_guess_language_python(self):
        assert _guess_language("main.py") == "python"
        assert _guess_language("src/app.py") == "python"

    def test_guess_language_javascript(self):
        assert _guess_language("index.js") == "javascript"

    def test_guess_language_typescript(self):
        assert _guess_language("app.ts") == "typescript"

    def test_guess_language_html(self):
        assert _guess_language("index.html") == "html"

    def test_guess_language_json(self):
        assert _guess_language("package.json") == "json"

    def test_guess_language_unknown(self):
        assert _guess_language("Makefile") == "text"

    def test_lang_to_ext(self):
        assert _lang_to_ext("python") == ".py"
        assert _lang_to_ext("javascript") == ".js"
        assert _lang_to_ext("html") == ".html"
        assert _lang_to_ext("unknown") == ".txt"

    def test_parse_files_valid(self):
        raw = json.dumps({
            "files": [
                {"path": "main.py", "language": "python", "content": 'print("hello")'},
                {"path": "requirements.txt", "language": "text", "content": "fastapi\nuvicorn"},
            ],
            "explanation": "Created project structure"
        })
        files, explanation = _parse_files(raw)
        assert len(files) == 2
        assert files[0].path == "main.py"
        assert files[0].content == 'print("hello")'
        assert files[1].path == "requirements.txt"
        assert explanation == "Created project structure"

    def test_parse_files_with_markdown_fences(self):
        inner = json.dumps({
            "files": [{"path": "app.py", "language": "python", "content": "x = 1"}],
            "explanation": "Done"
        })
        raw = f"```json\n{inner}\n```"
        files, explanation = _parse_files(raw)
        assert len(files) == 1
        assert files[0].path == "app.py"

    def test_parse_files_missing_content_skipped(self):
        raw = json.dumps({
            "files": [
                {"path": "main.py"},  # missing content
                {"path": "app.py", "content": "valid"},
            ],
            "explanation": "test"
        })
        files, _ = _parse_files(raw)
        # Only the file with both path and content is included
        assert len(files) == 1
        assert files[0].path == "app.py"

    def test_summarize_existing_empty(self):
        summary = _summarize_existing({})
        assert "None" in summary

    def test_summarize_existing_with_files(self):
        summary = _summarize_existing({"main.py": "print('hello')", "README.md": "# Project"})
        assert "main.py" in summary
        assert "README.md" in summary


# ── Agents: Debugger ─────────────────────────────────────────────────────────

from backend.agents.debugger import _parse_fix


class TestDebugger:
    def test_parse_fix_valid(self):
        raw = json.dumps({
            "root_cause": "Missing import statement",
            "fix_description": "Added 'import os' at the top",
            "files": [{"path": "main.py", "language": "python", "content": "import os\nprint(os.getcwd())"}]
        })
        files, root_cause, fix_desc = _parse_fix(raw)
        assert len(files) == 1
        assert root_cause == "Missing import statement"
        assert "import os" in fix_desc

    def test_parse_fix_invalid_json(self):
        files, root_cause, fix_desc = _parse_fix("not json")
        assert files == []
        assert "Parse error" in root_cause

    def test_parse_fix_empty_files(self):
        raw = json.dumps({
            "root_cause": "Unknown",
            "fix_description": "Cannot fix",
            "files": []
        })
        files, root_cause, fix_desc = _parse_fix(raw)
        assert files == []
        assert root_cause == "Unknown"


# ── Sandbox: Executor ─────────────────────────────────────────────────────────

from backend.sandbox.executor import (
    _detect_install_command,
    _detect_run_command,
    execute_project,
)


class TestExecutor:
    def test_detect_main_py(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "main.py").write_text('print("hello")')
            cmd, env = _detect_run_command(p)
            assert cmd is not None
            assert "main.py" in cmd

    def test_detect_app_py_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "app.py").write_text('print("app")')
            cmd, env = _detect_run_command(p)
            assert cmd is not None
            assert "app.py" in cmd

    def test_detect_no_entry_point(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            cmd, env = _detect_run_command(p)
            assert cmd is None

    def test_detect_requirements_txt(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "requirements.txt").write_text("requests")
            cmd = _detect_install_command(p)
            assert cmd is not None
            assert "requirements.txt" in cmd

    def test_detect_no_deps(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            cmd = _detect_install_command(p)
            assert cmd is None

    @pytest.mark.asyncio
    async def test_execute_success(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "main.py").write_text('print("hello from sandbox")')
            result = await execute_project(p)
            assert result.exit_code == 0
            assert "hello from sandbox" in result.stdout
            assert result.duration > 0

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "main.py").write_text("raise ValueError('deliberate error')")
            result = await execute_project(p)
            assert result.exit_code != 0
            assert "ValueError" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_no_entry_point(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            result = await execute_project(p)
            assert result.exit_code == 1
            assert "No runnable entry point" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_multiline_output(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "main.py").write_text("\n".join(f'print("{i}")' for i in range(5)))
            result = await execute_project(p)
            assert result.exit_code == 0
            for i in range(5):
                assert str(i) in result.stdout


# ── Orchestrator: Session ──────────────────────────────────────────────────────

from backend.agents.orchestrator import Session


class TestSession:
    def test_session_creation(self):
        session = Session("test-session")
        assert session.id == "test-session"
        assert session.state == ProjectState.IDLE
        assert session.files == {}
        assert session.history == []
        assert session.plan is None

    def test_session_project_dir_created(self):
        session = Session("dir-test")
        assert session.project_dir.exists()
        # Cleanup
        import shutil
        shutil.rmtree(str(session.project_dir), ignore_errors=True)

    def test_session_add_messages(self):
        session = Session("msg-test")
        session.add_user_message("build a REST API")
        session.add_assistant_message("I'll build it now")
        assert len(session.history) == 2
        assert session.history[0] == {"role": "user", "content": "build a REST API"}
        assert session.history[1] == {"role": "assistant", "content": "I'll build it now"}


# ── FastAPI App ────────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient

from backend.main import app


class TestApp:
    def setup_method(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "sessions" in data

    def test_root_serves_html(self):
        response = self.client.get("/")
        assert response.status_code == 200
        # Should return HTML content
        assert "text/html" in response.headers.get("content-type", "")

    def test_session_files_empty(self):
        response = self.client.get("/sessions/nonexistent-session/files")
        assert response.status_code == 200
        assert response.json()["files"] == []

    def test_static_css_served(self):
        response = self.client.get("/static/style.css")
        assert response.status_code == 200

    def test_static_js_served(self):
        response = self.client.get("/static/app.js")
        assert response.status_code == 200

    def test_websocket_connection(self):
        with self.client.websocket_connect("/ws/test-session-123") as ws:
            # Should receive welcome message
            data = ws.receive_json()
            assert data["event"] == "agent_message"
            assert "Welcome" in data["data"]["content"]

    def test_websocket_multiple_connections(self):
        """Multiple sessions should be independent."""
        with self.client.websocket_connect("/ws/session-a") as ws_a:
            welcome_a = ws_a.receive_json()
            assert welcome_a["event"] == "agent_message"

        with self.client.websocket_connect("/ws/session-b") as ws_b:
            welcome_b = ws_b.receive_json()
            assert welcome_b["event"] == "agent_message"
