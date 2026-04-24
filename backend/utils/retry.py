from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> T:
    last_exc: Optional[Exception] = None
    current_delay = delay

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt,
                    max_attempts,
                    exc,
                    current_delay,
                )
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error("All %d attempts failed. Last error: %s", max_attempts, exc)

    raise last_exc  # type: ignore[misc]
