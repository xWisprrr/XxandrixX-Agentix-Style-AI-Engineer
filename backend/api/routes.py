from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any, Dict

import aiofiles
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.websocket import manager
from backend.core.conversation import ConversationController
from backend.core.orchestrator import Orchestrator
from backend.core.task_schema import AgentEvent, ConversationMessage
from backend.memory.session_memory import SessionMemory
from backend.tools.filesystem import FileSystemTool

logger = logging.getLogger(__name__)

router = APIRouter()

_conversation = ConversationController()
_orchestrator = Orchestrator()
_session_memory = SessionMemory()
_fs = FileSystemTool()


class ChatRequest(BaseModel):
    session_id: str
    message: str


def _workspace_path(session_id: str) -> str:
    # Sanitize session_id to prevent path traversal
    safe_id = os.path.basename(session_id)
    base = os.path.abspath(os.getenv("WORKSPACE_DIR", "./workspaces"))
    return os.path.join(base, safe_id)


async def _run_task_background(session_id: str, message: str) -> None:
    history = _session_memory.get_history(session_id)

    async def emit(event: AgentEvent) -> None:
        await manager.send_event(session_id, event)

    try:
        task = await _conversation.parse_message(message, history)
        workspace = _workspace_path(session_id)
        task.workspace_path = workspace

        _session_memory.add_message(
            session_id, ConversationMessage(role="user", content=message)
        )

        task = await _orchestrator.run_task(task, session_id, emit)

        if task.result_summary:
            _session_memory.add_message(
                session_id,
                ConversationMessage(role="assistant", content=task.result_summary),
            )

    except Exception as exc:
        logger.exception("Background task failed for session %s: %s", session_id, exc)
        error_event = AgentEvent(
            type="task_error",
            data={"error": str(exc)},
            session_id=session_id,
        )
        await manager.send_event(session_id, error_event)


@router.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> JSONResponse:
    background_tasks.add_task(_run_task_background, request.session_id, request.message)
    return JSONResponse({"status": "accepted", "session_id": request.session_id})


@router.get("/sessions/{session_id}/files")
async def list_files(session_id: str) -> JSONResponse:
    workspace = _workspace_path(session_id)
    # Guard: workspace must be under base dir
    base = os.path.abspath(os.getenv("WORKSPACE_DIR", "./workspaces"))
    if not workspace.startswith(base):
        raise HTTPException(status_code=403, detail="Invalid session")
    if not os.path.isdir(workspace):
        return JSONResponse({"files": []})
    files = _fs.list_files(workspace)
    return JSONResponse({"files": files})


@router.get("/sessions/{session_id}/files/{file_path:path}")
async def read_file(session_id: str, file_path: str) -> JSONResponse:
    workspace = _workspace_path(session_id)
    full_path = os.path.normpath(os.path.join(workspace, file_path))

    # Security: ensure path stays inside workspace
    if not full_path.startswith(os.path.abspath(workspace)):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = await _fs.read_file(full_path)
        return JSONResponse({"path": file_path, "content": content})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str) -> JSONResponse:
    history = _session_memory.get_history(session_id)
    return JSONResponse(
        {"history": [m.model_dump(mode="json") for m in history]}
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    _session_memory.clear_session(session_id)
    workspace = _workspace_path(session_id)
    if os.path.isdir(workspace):
        shutil.rmtree(workspace, ignore_errors=True)
    manager.disconnect(session_id)
    return JSONResponse({"status": "deleted", "session_id": session_id})
