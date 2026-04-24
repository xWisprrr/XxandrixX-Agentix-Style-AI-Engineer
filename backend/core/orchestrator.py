from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from backend.agents.coder import Coder
from backend.agents.debugger import Debugger
from backend.agents.planner import Planner
from backend.agents.tester import Tester
from backend.core.state_machine import StateMachine, TaskState
from backend.core.task_schema import AgentEvent, ExecutionResult, Task, TaskStatus, StepStatus
from backend.execution.sandbox import Sandbox

if TYPE_CHECKING:
    from backend.core.conversation import ConversationController

logger = logging.getLogger(__name__)

EventEmitter = Callable[[AgentEvent], Awaitable[None]]


class Orchestrator:
    def __init__(self) -> None:
        self._planner = Planner()
        self._coder = Coder()
        self._tester = Tester()
        self._debugger = Debugger()
        self._sandbox = Sandbox()
        self._max_retries = int(os.getenv("MAX_RETRIES", "1"))

    async def run_task(
        self,
        task: Task,
        session_id: str,
        event_emitter: EventEmitter,
    ) -> Task:
        sm = StateMachine()

        async def emit(event_type: str, data: Dict[str, Any]) -> None:
            event = AgentEvent(type=event_type, data=data, session_id=session_id)
            try:
                await event_emitter(event)
            except Exception:
                logger.exception("Failed to emit event %s", event_type)

        workspace = task.workspace_path or os.path.join(
            os.getenv("WORKSPACE_DIR", "./workspaces"), session_id
        )
        os.makedirs(workspace, exist_ok=True)
        task.workspace_path = workspace

        try:
            # PLANNING
            sm.transition(TaskState.PLANNING)
            task.status = TaskStatus.PLANNING
            await emit("agent_status", {"agent": "planner", "state": "active"})

            task.steps = await self._planner.create_steps(task)
            await emit("plan", {"steps": [s.model_dump() for s in task.steps]})
            await emit("agent_status", {"agent": "planner", "state": "idle"})

            # EXECUTING
            sm.transition(TaskState.EXECUTING)
            task.status = TaskStatus.EXECUTING

            context: Dict[str, Any] = {}

            for step in task.steps:
                await emit("step_start", {"step_id": step.id, "name": step.name})
                await emit("agent_status", {"agent": "coder", "state": "active"})

                step.status = StepStatus.RUNNING
                retries = 0

                while retries <= self._max_retries:
                    # Code generation
                    try:
                        step.code = await self._coder.execute_step(step, workspace, context)
                    except Exception as exc:
                        logger.exception("Coder failed on step %s", step.id)
                        step.code = f"# Coder failed: {exc}\nprint('Step failed during code generation')"

                    await emit("agent_status", {"agent": "coder", "state": "idle"})

                    # Sandbox execution
                    if sm.can_transition(TaskState.TESTING):
                        sm.transition(TaskState.TESTING)
                    await emit("agent_status", {"agent": "tester", "state": "active"})

                    result: ExecutionResult = await self._sandbox.run(
                        code=step.code,
                        language=step.language,
                        workspace_path=workspace,
                    )

                    if result.stdout:
                        await emit("log", {"level": "info", "message": result.stdout})
                    if result.stderr:
                        await emit("log", {"level": "error", "message": result.stderr})

                    for created_file in result.files_created:
                        await emit("file_created", {"path": created_file})

                    # Validation
                    passed = await self._tester.validate(step, result)
                    await emit("agent_status", {"agent": "tester", "state": "idle"})

                    if passed:
                        step.status = StepStatus.COMPLETE
                        step.output = result.stdout
                        step.files_created = result.files_created
                        context[step.id] = {
                            "name": step.name,
                            "output": result.stdout,
                            "files": result.files_created,
                        }
                        await emit("step_complete", {
                            "step_id": step.id,
                            "name": step.name,
                            "output": result.stdout,
                        })
                        break
                    else:
                        if retries < self._max_retries:
                            # DEBUGGING
                            if sm.can_transition(TaskState.DEBUGGING):
                                sm.transition(TaskState.DEBUGGING)
                            await emit("agent_status", {"agent": "debugger", "state": "active"})

                            error_info = result.stderr or f"Exit code {result.exit_code}"
                            step = await self._debugger.fix(step, error_info, context)

                            await emit("agent_status", {"agent": "debugger", "state": "idle"})
                            if sm.can_transition(TaskState.EXECUTING):
                                sm.transition(TaskState.EXECUTING)
                            retries += 1
                        else:
                            step.status = StepStatus.FAILED
                            step.error = result.stderr or f"Exit code {result.exit_code}"
                            await emit("step_error", {
                                "step_id": step.id,
                                "name": step.name,
                                "error": step.error,
                            })
                            break

            # Generate summary
            summary = await self._generate_summary(task, session_id)
            task.result_summary = summary
            task.status = TaskStatus.COMPLETE
            task.completed_at = datetime.utcnow()

            if sm.can_transition(TaskState.COMPLETE):
                sm.transition(TaskState.COMPLETE)

            await emit("chat_response", {"message": summary})
            await emit("task_complete", {"task_id": task.id, "summary": summary})

        except Exception as exc:
            logger.exception("Orchestrator fatal error: %s", exc)
            task.status = TaskStatus.ERROR
            if sm.can_transition(TaskState.ERROR):
                sm.transition(TaskState.ERROR)
            await emit("task_error", {"error": str(exc)})

        return task

    async def _generate_summary(self, task: Task, session_id: str) -> str:
        completed = [s for s in task.steps if s.status == StepStatus.COMPLETE]
        failed = [s for s in task.steps if s.status == StepStatus.FAILED]

        lines = [f"## Task Complete: {task.title}", ""]
        if completed:
            lines.append(f"✅ Completed {len(completed)}/{len(task.steps)} steps:")
            for s in completed:
                lines.append(f"  - **{s.name}**")
                if s.files_created:
                    for f in s.files_created:
                        lines.append(f"    - Created: `{f}`")
        if failed:
            lines.append(f"\n⚠️ {len(failed)} step(s) failed:")
            for s in failed:
                lines.append(f"  - **{s.name}**: {s.error}")

        return "\n".join(lines)
