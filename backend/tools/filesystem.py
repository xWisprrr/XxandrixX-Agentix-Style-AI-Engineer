from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

import aiofiles

logger = logging.getLogger(__name__)


class FileSystemTool:
    async def write_file(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(content)
        logger.debug("Wrote file: %s (%d bytes)", path, len(content))

    async def read_file(self, path: str) -> str:
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            return await fh.read()

    def list_files(self, workspace: str) -> List[str]:
        safe_root = os.path.realpath(workspace)
        result = []
        for root, dirs, files in os.walk(safe_root):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fname.startswith("."):
                    full_path = os.path.join(root, fname)
                    # Ensure the resolved path is still within the workspace
                    resolved = os.path.realpath(full_path)
                    if resolved.startswith(safe_root):
                        result.append(os.path.relpath(resolved, safe_root))
        return sorted(result)

    def create_directory(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        logger.debug("Created directory: %s", path)

    def delete_file(self, path: str) -> bool:
        try:
            os.remove(path)
            logger.debug("Deleted file: %s", path)
            return True
        except OSError as exc:
            logger.warning("Could not delete %s: %s", path, exc)
            return False

    def file_exists(self, path: str) -> bool:
        return os.path.isfile(path)
