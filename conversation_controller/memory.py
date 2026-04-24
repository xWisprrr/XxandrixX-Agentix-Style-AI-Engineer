"""ConversationMemory: persists follow_up_memory across conversation turns."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Stores and manages follow_up_memory dicts across conversation turns.

    The memory is updated after each successful compile() call and can be
    serialised into a context dict for injection into subsequent prompts.
    """

    def __init__(self) -> None:
        """Initialise with an empty memory state."""
        self._memory: dict = {}

    def update(self, follow_up_memory: dict) -> None:
        """Merge the latest follow_up_memory into the stored state.

        Args:
            follow_up_memory: The follow_up_memory dict from the latest TaskGraph.
        """
        self._memory.update(follow_up_memory)
        logger.debug("Memory updated: %s", self._memory)

    def to_context(self) -> dict:
        """Return a copy of the memory dict for prompt injection.

        Returns:
            A dict summary of the current memory state.
        """
        return dict(self._memory)

    def reset(self) -> None:
        """Clear all stored memory."""
        self._memory = {}
        logger.debug("Memory reset.")
