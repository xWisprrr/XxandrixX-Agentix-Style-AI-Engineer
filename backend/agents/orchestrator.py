"""Orchestrator — the central agent loop that coordinates all other agents."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Callable

from backend.agents.coder import generate_files
from backend.agents.debugger import fix_errors
from backend.agents.planner import create_plan
from backend.llm.client import chat_completion
from backend.models import (
    AgentRole,
    ChatMessage,
    EventType,
    ExecutionResult,
    GeneratedFile,
    ProjectPlan,
    ProjectState,
    WSMessage,
)
from backend.sandbox.executor import execute_project, install_dependencies, run_tests

# Max debug attempts before giving up
MAX_DEBUG_ATTEMPTS = int(os.getenv("MAX_DEBUG_ATTEMPTS", "3"))
PROJECTS_BASE = Path(os.getenv("PROJECTS_DIR", "projects"))

CONVERSATION_SYSTEM = """You are Agentix — a senior AI software engineer.
You understand user requests, ask clarifying questions when needed, and build real software.
You are direct, concise, and professional. When the user gives you a task, confirm your plan
and begin building immediately. Keep responses short (1-3 sentences) unless the user asks for detail.
You can also answer mid-build direction changes, modifications, and questions."""


class Session:
    """Holds state for one user/project session."""

    def __init__(self, session_id: str):
        self.id = session_id
        self.project_id = str(uuid.uuid4())[:8]
        self.project_dir = PROJECTS_BASE / self.project_id
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state = ProjectState.IDLE
        self.history: list[dict] = []  # LLM message history
        self.files: dict[str, str] = {}  # path -> content
        self.plan: ProjectPlan | None = None
        self._running_task: asyncio.Task | None = None

    def add_user_message(self, content: str):
        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.history.append({"role": "assistant", "content": content})


class Orchestrator:
    """
    Coordinates the full planning → coding → execution → debugging loop
    and streams real-time events to the caller via an async callback.
    """

    def __init__(self, session: Session, emit: Callable[[WSMessage], asyncio.Future]):
        self.session = session
        self.emit = emit

    # ── Public entry points ───────────────────────────────────────────────────

    async def handle_message(self, user_text: str):
        """Process a user chat message."""
        self.session.add_user_message(user_text)
        await self._emit(EventType.USER_MESSAGE, {"content": user_text}, AgentRole.ORCHESTRATOR)

        if self.session.state in (ProjectState.IDLE, ProjectState.COMPLETE, ProjectState.ERROR):
            # Check if this is a build request or a conversational message
            is_build_request = await self._classify_intent(user_text)
            if is_build_request:
                await self._run_build_loop(user_text)
            else:
                await self._conversational_reply(user_text)
        else:
            # Mid-build user message — acknowledge and queue
            reply = await self._conversational_reply(user_text, mid_build=True)

    async def handle_modify(self, instruction: str):
        """Handle a mid-session modification request."""
        await self.handle_message(instruction)

    # ── Build loop ────────────────────────────────────────────────────────────

    async def _run_build_loop(self, goal: str):
        """The main planning → coding → execution → debugging cycle."""
        session = self.session

        # 1. PLAN
        session.state = ProjectState.PLANNING
        await self._emit(EventType.AGENT_STATUS, {"agent": AgentRole.PLANNER, "status": "Planning architecture…"}, AgentRole.PLANNER)

        try:
            plan = await create_plan(goal, session.history)
        except Exception as exc:
            await self._emit(EventType.ERROR, {"message": f"Planning failed: {exc}"})
            session.state = ProjectState.ERROR
            return

        session.plan = plan
        await self._emit(
            EventType.PLAN_CREATED,
            {"goal": plan.goal, "steps": [s.model_dump() for s in plan.steps]},
            AgentRole.PLANNER,
        )
        await self._emit(
            EventType.AGENT_MESSAGE,
            {
                "content": f"I've planned {len(plan.steps)} steps to build this. Starting now…",
                "agent": AgentRole.PLANNER,
            },
            AgentRole.PLANNER,
        )
        session.add_assistant_message(f"I've created a {len(plan.steps)}-step plan to build: {goal}")

        # 2. CODE each step
        session.state = ProjectState.CODING
        for step in plan.steps:
            step.status = "active"
            await self._emit(
                EventType.PLAN_STEP_START,
                {"step": step.model_dump()},
                AgentRole.CODER,
            )
            await self._emit(
                EventType.AGENT_STATUS,
                {"agent": AgentRole.CODER, "status": f"Writing code: {step.title}"},
                AgentRole.CODER,
            )

            try:
                generated_files, explanation = await generate_files(
                    goal=plan.goal,
                    plan=plan,
                    step=step,
                    existing_files=session.files,
                    history=session.history,
                )
            except Exception as exc:
                await self._emit(EventType.ERROR, {"message": f"Code generation failed at step {step.index+1}: {exc}"})
                step.status = "failed"
                continue

            # Write files to disk
            for gf in generated_files:
                await self._write_file(gf)

            step.status = "done"
            await self._emit(
                EventType.PLAN_STEP_DONE,
                {"step": step.model_dump(), "explanation": explanation, "files": [f.path for f in generated_files]},
                AgentRole.CODER,
            )
            await self._emit(
                EventType.AGENT_MESSAGE,
                {"content": f"✅ Step {step.index+1} done: {explanation}", "agent": AgentRole.CODER},
                AgentRole.CODER,
            )

        # 3. INSTALL dependencies
        if any(f.endswith("requirements.txt") or f.endswith("package.json") for f in session.files):
            await self._emit(EventType.AGENT_STATUS, {"agent": AgentRole.ORCHESTRATOR, "status": "Installing dependencies…"})
            install_result = await install_dependencies(session.project_dir)
            await self._emit(
                EventType.EXECUTION_OUTPUT,
                {"stdout": install_result.stdout, "stderr": install_result.stderr, "phase": "install"},
            )

        # 4. EXECUTE → OBSERVE → DEBUG loop
        session.state = ProjectState.EXECUTING
        exec_result: ExecutionResult | None = None
        debug_attempts = 0

        while debug_attempts <= MAX_DEBUG_ATTEMPTS:
            await self._emit(
                EventType.EXECUTION_START,
                {"attempt": debug_attempts + 1, "project_dir": str(session.project_dir)},
            )
            await self._emit(
                EventType.AGENT_STATUS,
                {"agent": AgentRole.TESTER, "status": f"Running project (attempt {debug_attempts+1})…"},
                AgentRole.TESTER,
            )

            exec_result = await execute_project(session.project_dir)

            await self._emit(
                EventType.EXECUTION_OUTPUT,
                {
                    "stdout": exec_result.stdout,
                    "stderr": exec_result.stderr,
                    "exit_code": exec_result.exit_code,
                    "timed_out": exec_result.timed_out,
                    "duration": exec_result.duration,
                    "phase": "run",
                },
            )

            if exec_result.exit_code == 0 or exec_result.timed_out:
                # Success (or a long-running server that timed out cleanly)
                break

            # Failure — debug
            if debug_attempts >= MAX_DEBUG_ATTEMPTS:
                await self._emit(
                    EventType.AGENT_MESSAGE,
                    {"content": f"⚠️ Reached maximum debug attempts ({MAX_DEBUG_ATTEMPTS}). The project may need manual review.", "agent": AgentRole.DEBUGGER},
                    AgentRole.DEBUGGER,
                )
                break

            debug_attempts += 1
            session.state = ProjectState.DEBUGGING
            await self._emit(
                EventType.AGENT_STATUS,
                {"agent": AgentRole.DEBUGGER, "status": f"Debugging errors (attempt {debug_attempts})…"},
                AgentRole.DEBUGGER,
            )

            fixed_files, root_cause, fix_desc = await fix_errors(
                goal=goal,
                existing_files=session.files,
                execution_result=exec_result,
                attempt=debug_attempts,
                history=session.history,
            )

            if not fixed_files:
                await self._emit(
                    EventType.AGENT_MESSAGE,
                    {"content": f"🔍 Root cause: {root_cause}. Could not auto-fix.", "agent": AgentRole.DEBUGGER},
                    AgentRole.DEBUGGER,
                )
                break

            await self._emit(
                EventType.AGENT_MESSAGE,
                {"content": f"🔍 Root cause: {root_cause}\n🔧 Fix: {fix_desc}", "agent": AgentRole.DEBUGGER},
                AgentRole.DEBUGGER,
            )
            for gf in fixed_files:
                await self._write_file(gf)

            session.state = ProjectState.EXECUTING

        # 5. FINAL STATUS
        if exec_result and (exec_result.exit_code == 0 or exec_result.timed_out):
            session.state = ProjectState.COMPLETE
            final_msg = (
                f"🎉 Project built successfully! All {len(plan.steps)} steps complete. "
                f"{'The server ran (timeout is normal for long-running servers).' if exec_result.timed_out else 'Execution finished cleanly.'}"
            )
        else:
            session.state = ProjectState.ERROR
            final_msg = (
                f"⚠️ Project built with {len(session.files)} files, but execution had issues. "
                "The files are ready in the project directory — you may need to review the errors above."
            )

        session.add_assistant_message(final_msg)
        await self._emit(
            EventType.AGENT_MESSAGE,
            {"content": final_msg, "agent": AgentRole.ORCHESTRATOR},
            AgentRole.ORCHESTRATOR,
        )
        await self._emit(EventType.DONE, {"project_id": session.project_id, "state": session.state})

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _classify_intent(self, text: str) -> bool:
        """Return True if the message is a build/code request."""
        trigger_words = [
            "build", "create", "make", "write", "generate", "develop",
            "implement", "code", "app", "application", "website", "api",
            "service", "tool", "script", "program", "saas", "dashboard",
        ]
        lower = text.lower()
        return any(w in lower for w in trigger_words)

    async def _conversational_reply(self, text: str, mid_build: bool = False) -> str:
        """Generate a short conversational reply."""
        extra = " The build is currently in progress. Acknowledge the user's message and let them know you'll consider their feedback." if mid_build else ""
        messages = [
            *self.session.history[-8:],
        ]
        reply = await chat_completion(
            messages,
            system_prompt=CONVERSATION_SYSTEM + extra,
            temperature=0.5,
            max_tokens=256,
        )
        self.session.add_assistant_message(reply)
        await self._emit(
            EventType.AGENT_MESSAGE,
            {"content": reply, "agent": AgentRole.ORCHESTRATOR},
            AgentRole.ORCHESTRATOR,
        )
        return reply

    async def _write_file(self, gf: GeneratedFile):
        """Write a generated file to disk and emit an event."""
        full_path = self.session.project_dir / gf.path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(gf.content, encoding="utf-8")
        self.session.files[gf.path] = gf.content

        # Determine if it's new or updated
        is_new = gf.path not in self.session.files
        event = EventType.FILE_CREATED if is_new else EventType.FILE_UPDATED
        await self._emit(
            event,
            {
                "path": gf.path,
                "language": gf.language,
                "content": gf.content,
                "size": len(gf.content),
            },
            AgentRole.CODER,
        )
        # Always update session files map
        self.session.files[gf.path] = gf.content
        # Emit updated file tree
        await self._emit_file_tree()

    async def _emit_file_tree(self):
        """Emit the current file tree."""
        await self._emit(
            EventType.FILE_TREE,
            {"files": list(self.session.files.keys())},
        )

    async def _emit(self, event: EventType, data: dict = None, agent: AgentRole = None):
        msg = WSMessage(event=event, data=data or {}, agent=agent)
        await self.emit(msg)
