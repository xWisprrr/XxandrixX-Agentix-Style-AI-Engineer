from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.task_schema import ConversationMessage

logger = logging.getLogger(__name__)


class SessionMemory:
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._messages: Dict[str, List[ConversationMessage]] = defaultdict(list)

    def store(self, session_id: str, key: str, value: Any) -> None:
        self._store[session_id][key] = value
        logger.debug("Stored key=%r for session=%s", key, session_id)

    def retrieve(self, session_id: str, key: str) -> Optional[Any]:
        return self._store[session_id].get(key)

    def get_all(self, session_id: str) -> Dict[str, Any]:
        return dict(self._store[session_id])

    def get_history(self, session_id: str) -> List[ConversationMessage]:
        return list(self._messages[session_id])

    def add_message(self, session_id: str, message: ConversationMessage) -> None:
        self._messages[session_id].append(message)

    def clear_session(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        self._messages.pop(session_id, None)
        logger.info("Cleared session: %s", session_id)

    def list_sessions(self) -> List[str]:
        sessions = set(self._store.keys()) | set(self._messages.keys())
        return list(sessions)
