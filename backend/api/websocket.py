from __future__ import annotations

import logging
from typing import Dict

from fastapi import WebSocket

from backend.core.task_schema import AgentEvent

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info("WebSocket connected: session=%s", session_id)

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        logger.info("WebSocket disconnected: session=%s", session_id)

    async def send_event(self, session_id: str, event: AgentEvent) -> None:
        websocket = self._connections.get(session_id)
        if not websocket:
            logger.debug("No WebSocket for session=%s, dropping event %s", session_id, event.type)
            return
        try:
            payload = event.model_dump(mode="json")
            await websocket.send_json(payload)
        except Exception as exc:
            logger.warning("Failed to send event to session=%s: %s", session_id, exc)
            self.disconnect(session_id)

    async def broadcast(self, event: AgentEvent) -> None:
        for session_id in list(self._connections.keys()):
            await self.send_event(session_id, event)

    def is_connected(self, session_id: str) -> bool:
        return session_id in self._connections

    def active_sessions(self) -> list:
        return list(self._connections.keys())


# Singleton instance used across the application
manager = ConnectionManager()
