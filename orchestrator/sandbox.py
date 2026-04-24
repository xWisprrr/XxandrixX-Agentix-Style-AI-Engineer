"""SandboxEnvironment: isolated filesystem and command-execution environment.

All file paths are resolved relative to a working directory, protecting the
host system from path-traversal attacks.  Terminal commands run inside the
same directory via :mod:`subprocess` with a configurable timeout.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Output from a sandboxed shell command."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """True when the command exited with code 0 and did not time out."""
        return self.returncode == 0 and not self.timed_out


class SandboxPathError(ValueError):
    """Raised when a requested path escapes the sandbox work directory."""


class SandboxEnvironment:
    """Provides path-safe file operations and sandboxed command execution.

    Args:
        work_dir: Root directory for all sandbox operations.  When *None*, a
            temporary directory is created automatically and deleted on
            :meth:`cleanup` / context-manager exit.
        timeout: Maximum wall-clock seconds allowed for any shell command.
    """

    def __init__(
        self,
        work_dir: str | Path | None = None,
        timeout: int = 30,
    ) -> None:
        self._timeout = timeout
        self._owns_work_dir = work_dir is None

        if work_dir is None:
            self._work_dir = Path(tempfile.mkdtemp(prefix="agentix_sandbox_"))
            logger.debug("Created sandbox work_dir: %s", self._work_dir)
        else:
            self._work_dir = Path(work_dir).resolve()
            self._work_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def work_dir(self) -> Path:
        """The root directory of this sandbox."""
        return self._work_dir

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def resolve_path(self, path: str) -> Path:
        """Return the absolute sandbox path for *path*, rejecting traversal.

        Args:
            path: A relative (or absolute) path to resolve within the sandbox.

        Returns:
            Absolute :class:`~pathlib.Path` guaranteed to be inside
            :attr:`work_dir`.

        Raises:
            SandboxPathError: If the resolved path escapes the sandbox.
        """
        # Strip leading slashes so "/etc/passwd" becomes "etc/passwd"
        normalised = Path(path.lstrip("/\\"))
        resolved = (self._work_dir / normalised).resolve()

        try:
            resolved.relative_to(self._work_dir.resolve())
        except ValueError:
            raise SandboxPathError(
                f"Path {path!r} resolves outside the sandbox: {resolved}"
            )

        return resolved

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str) -> Path:
        """Write *content* to *path* inside the sandbox, creating directories.

        Args:
            path: Sandbox-relative file path.
            content: Text content to write (UTF-8).

        Returns:
            The resolved absolute :class:`~pathlib.Path` of the written file.

        Raises:
            SandboxPathError: If *path* escapes the sandbox.
        """
        abs_path = self.resolve_path(path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        logger.debug("Sandbox write: %s (%d bytes)", abs_path, len(content))
        return abs_path

    def read_file(self, path: str) -> str:
        """Read and return the text content of *path*.

        Args:
            path: Sandbox-relative file path.

        Returns:
            UTF-8 decoded file content.

        Raises:
            SandboxPathError: If *path* escapes the sandbox.
            FileNotFoundError: If the file does not exist.
        """
        abs_path = self.resolve_path(path)
        content = abs_path.read_text(encoding="utf-8")
        logger.debug("Sandbox read: %s (%d bytes)", abs_path, len(content))
        return content

    def delete_file(self, path: str) -> None:
        """Delete *path* from the sandbox.

        Args:
            path: Sandbox-relative file path.

        Raises:
            SandboxPathError: If *path* escapes the sandbox.
            FileNotFoundError: If the file does not exist.
        """
        abs_path = self.resolve_path(path)
        abs_path.unlink()
        logger.debug("Sandbox delete: %s", abs_path)

    def list_files(self) -> list[str]:
        """Return all files in the sandbox as sandbox-relative path strings."""
        result = []
        for root, _dirs, files in os.walk(self._work_dir):
            for fname in files:
                full = Path(root) / fname
                rel = full.relative_to(self._work_dir)
                result.append(str(rel))
        return sorted(result)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def run_command(self, command: str, cwd: str | None = None) -> CommandResult:
        """Execute *command* inside the sandbox via a shell subprocess.

        Args:
            command: Shell command string to execute.
            cwd: Optional subdirectory (relative to sandbox) to run in.
                 Defaults to :attr:`work_dir`.

        Returns:
            A :class:`CommandResult` with stdout, stderr, returncode and
            a ``timed_out`` flag.
        """
        run_cwd = self._work_dir
        if cwd is not None:
            run_cwd = self.resolve_path(cwd)

        logger.debug("Sandbox run_command: %r (cwd=%s)", command, run_cwd)
        timed_out = False

        try:
            proc = subprocess.run(
                command,
                shell=True,  # noqa: S602
                cwd=str(run_cwd),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            returncode = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            logger.warning("Command timed out after %ds: %r", self._timeout, command)

        return CommandResult(
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Remove the sandbox directory if it was auto-created."""
        if self._owns_work_dir and self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)
            logger.debug("Sandbox cleaned up: %s", self._work_dir)

    def __enter__(self) -> "SandboxEnvironment":
        return self

    def __exit__(self, *_: object) -> None:
        self.cleanup()
