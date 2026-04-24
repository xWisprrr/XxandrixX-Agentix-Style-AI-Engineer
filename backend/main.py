from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.api.websocket import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agentix AI Engineer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
WORKSPACES_DIR = os.getenv("WORKSPACE_DIR", "./workspaces")


@app.on_event("startup")
async def startup() -> None:
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    logger.info("Workspaces directory ready: %s", WORKSPACES_DIR)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await manager.connect(session_id, websocket)
    try:
        while True:
            # Keep the connection alive; all events are server-pushed
            data = await websocket.receive_text()
            logger.debug("WS message from session=%s: %s", session_id, data[:100])
    except WebSocketDisconnect:
        manager.disconnect(session_id)


# Serve frontend static assets
if os.path.isdir(FRONTEND_DIR):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/{full_path:path}")
    async def serve_static(full_path: str) -> FileResponse:
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
