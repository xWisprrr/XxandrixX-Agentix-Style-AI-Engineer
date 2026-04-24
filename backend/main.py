"""
Agentix — Real-time Autonomous Software Engineering System
FastAPI application with WebSocket support for real-time communication.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.agents.orchestrator import Orchestrator, Session
from backend.models import EventType, IncomingUserMessage, WSMessage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agentix")

app = FastAPI(title="Agentix", description="Real-time Autonomous Software Engineering System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# In-memory session store
_sessions: dict[str, Session] = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend UI."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>Agentix</h1><p>Frontend not found. Run from project root.</p>")


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(_sessions)}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time bidirectional communication.
    
    Client sends: {"message": "Build me a task manager app"}
    Server sends: stream of WSMessage JSON objects
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: session={session_id}")

    # Create or reuse session
    if session_id not in _sessions:
        _sessions[session_id] = Session(session_id)
    session = _sessions[session_id]

    async def emit(msg: WSMessage):
        """Send a WSMessage to this WebSocket client."""
        try:
            await websocket.send_text(msg.model_dump_json())
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")

    # Send welcome message
    await emit(WSMessage(
        event=EventType.AGENT_MESSAGE,
        data={
            "content": "👋 Welcome to Agentix! I'm your AI software engineering team. Tell me what you want to build, and I'll plan, code, execute, and debug it in real time.",
            "agent": "orchestrator",
        },
    ))

    orchestrator = Orchestrator(session=session, emit=emit)
    current_task: asyncio.Task | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"message": raw}

            user_message = payload.get("message", "").strip()
            if not user_message:
                continue

            logger.info(f"[{session_id}] User: {user_message[:100]}")

            # Cancel any running build task if user sends a new message
            if current_task and not current_task.done():
                current_task.cancel()
                try:
                    await current_task
                except asyncio.CancelledError:
                    pass

            # Run orchestrator in background task so we can receive more messages
            current_task = asyncio.create_task(
                orchestrator.handle_message(user_message)
            )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
        if current_task and not current_task.done():
            current_task.cancel()
    except Exception as e:
        logger.error(f"WebSocket error [{session_id}]: {e}", exc_info=True)
        try:
            await emit(WSMessage(event=EventType.ERROR, data={"message": str(e)}))
        except Exception:
            pass


@app.get("/sessions/{session_id}/files")
async def list_session_files(session_id: str):
    """List all generated files for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"files": []}
    return {
        "project_id": session.project_id,
        "state": session.state,
        "files": list(session.files.keys()),
    }


@app.get("/sessions/{session_id}/files/{file_path:path}")
async def get_session_file(session_id: str, file_path: str):
    """Get the content of a specific generated file."""
    session = _sessions.get(session_id)
    if not session or file_path not in session.files:
        return {"error": "File not found"}
    return {"path": file_path, "content": session.files[file_path]}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
