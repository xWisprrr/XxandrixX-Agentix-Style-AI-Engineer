from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from backend.core.task_schema import ExecutionResult
from backend.execution.command_runner import CommandRunner
from backend.execution.runtime import Runtime

logger = logging.getLogger(__name__)


class Sandbox:
    def __init__(self) -> None:
        self._runner = CommandRunner()
        self._runtime = Runtime()
        self._timeout = int(os.getenv("SANDBOX_TIMEOUT", "30"))

    async def run(
        self,
        code: str,
        language: str,
        workspace_path: str,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        timeout = timeout or self._timeout
        os.makedirs(workspace_path, exist_ok=True)

        # Write code to a temp file inside workspace so relative file ops work
        ext = self._runtime.get_extension(language)
        code_file = os.path.join(workspace_path, f"_step_runner{ext}")

        try:
            with open(code_file, "w", encoding="utf-8") as fh:
                fh.write(code)

            # Track files before execution
            files_before = _list_files(workspace_path)

            command = self._runtime.get_command(language, code_file)
            result = await self._runner.run(
                command=command,
                cwd=workspace_path,
                timeout=timeout,
            )

            # Track new files
            files_after = _list_files(workspace_path)
            new_files = [
                f for f in files_after
                if f not in files_before and not os.path.basename(f).startswith("_step_runner")
            ]

            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                files_created=new_files,
                timed_out=result.timed_out,
            )

        except Exception as exc:
            logger.exception("Sandbox.run failed: %s", exc)
            return ExecutionResult(
                stderr=str(exc),
                exit_code=1,
            )
        finally:
            # Clean up runner script but keep workspace files
            if os.path.exists(code_file):
                try:
                    os.remove(code_file)
                except OSError:
                    pass


def _list_files(directory: str) -> List[str]:
    result = []
    for root, _, files in os.walk(directory):
        for fname in files:
            result.append(os.path.join(root, fname))
    return result
