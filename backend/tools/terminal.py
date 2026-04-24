from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Optional

logger = logging.getLogger(__name__)


class TerminalTool:
    async def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=os.environ.copy(),
            )

            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                output = stdout_bytes.decode("utf-8", errors="replace")
                logger.debug("Terminal command %r exited %d", command, proc.returncode)
                return output

            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                return f"[timeout after {timeout}s]\n"

        except Exception as exc:
            logger.exception("TerminalTool.execute failed: %s", exc)
            return f"[error: {exc}]\n"
