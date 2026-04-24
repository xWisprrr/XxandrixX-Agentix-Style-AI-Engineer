from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional

from backend.core.task_schema import CommandResult

logger = logging.getLogger(__name__)


class CommandRunner:
    async def run(
        self,
        command: List[str],
        cwd: Optional[str] = None,
        timeout: int = 30,
        env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=run_env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return CommandResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    exit_code=proc.returncode or 0,
                    timed_out=False,
                )

            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                logger.warning("Command timed out after %ds: %s", timeout, command)
                return CommandResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    exit_code=124,
                    timed_out=True,
                )

        except FileNotFoundError as exc:
            logger.error("Command not found: %s — %s", command[0], exc)
            return CommandResult(
                stderr=f"Command not found: {command[0]}",
                exit_code=127,
            )
        except Exception as exc:
            logger.exception("CommandRunner.run failed: %s", exc)
            return CommandResult(
                stderr=str(exc),
                exit_code=1,
            )
