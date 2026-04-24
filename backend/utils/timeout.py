from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_timeout(coro: Awaitable[T], seconds: float) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        logger.warning("Coroutine timed out after %.1fs", seconds)
        raise
