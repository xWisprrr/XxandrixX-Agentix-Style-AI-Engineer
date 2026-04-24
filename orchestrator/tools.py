"""ToolDispatcher: routes TaskGraph tool_calls to sandbox operations.

Each tool maps to a concrete sandbox action:
- ``filesystem.write`` → :meth:`SandboxEnvironment.write_file`
- ``filesystem.read``  → :meth:`SandboxEnvironment.read_file`
- ``terminal.run``     → :meth:`SandboxEnvironment.run_command`
- ``browser.open``     → records the URL (browser cannot run in sandbox)
"""

from __future__ import annotations

import logging
from typing import Any

from conversation_controller.schema import ToolCall
from orchestrator.result import ToolResult
from orchestrator.sandbox import SandboxEnvironment

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches :class:`ToolCall` objects to sandboxed implementations.

    Args:
        sandbox: The :class:`SandboxEnvironment` in which file and command
            operations are executed.
    """

    def __init__(self, sandbox: SandboxEnvironment) -> None:
        self._sandbox = sandbox
        self._handlers: dict[str, Any] = {
            "filesystem.write": self._filesystem_write,
            "filesystem.read": self._filesystem_read,
            "terminal.run": self._terminal_run,
            "browser.open": self._browser_open,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """Dispatch a single tool call and return its result.

        Args:
            tool_call: The :class:`ToolCall` instance from the TaskGraph.

        Returns:
            A :class:`ToolResult` describing success or failure.
        """
        handler = self._handlers.get(tool_call.tool)
        if handler is None:
            return ToolResult(
                tool=tool_call.tool,
                args=tool_call.args,
                status="failure",
                error=f"Unknown tool: {tool_call.tool!r}",
            )

        logger.debug("Dispatching tool=%s args=%s", tool_call.tool, tool_call.args)
        try:
            output = handler(tool_call.args)
            return ToolResult(
                tool=tool_call.tool,
                args=tool_call.args,
                status="success",
                output=output,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool %s failed: %s", tool_call.tool, exc)
            return ToolResult(
                tool=tool_call.tool,
                args=tool_call.args,
                status="failure",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _filesystem_write(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write content to a file inside the sandbox.

        Expected args: ``{"path": "<relative path>", "content": "<text>"}``
        """
        path: str = args.get("path", "")
        content: str = args.get("content", "")

        if not path:
            raise ValueError("filesystem.write requires 'path' arg")

        written_path = self._sandbox.write_file(path, content)
        return {"path": str(written_path), "bytes_written": len(content.encode())}

    def _filesystem_read(self, args: dict[str, Any]) -> dict[str, Any]:
        """Read a file from the sandbox.

        Expected args: ``{"path": "<relative path>"}``
        """
        path: str = args.get("path", "")

        if not path:
            raise ValueError("filesystem.read requires 'path' arg")

        content = self._sandbox.read_file(path)
        return {"path": path, "content": content, "bytes_read": len(content.encode())}

    def _terminal_run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a shell command inside the sandbox.

        Expected args: ``{"command": "<shell command>", "cwd": "<optional subdir>"}``
        """
        command: str = args.get("command", "")
        cwd: str | None = args.get("cwd")

        if not command:
            raise ValueError("terminal.run requires 'command' arg")

        result = self._sandbox.run_command(command, cwd=cwd)

        if result.timed_out:
            raise TimeoutError(f"Command timed out: {command!r}")

        if not result.success:
            raise RuntimeError(
                f"Command exited with code {result.returncode}: {result.stderr.strip()}"
            )

        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _browser_open(self, args: dict[str, Any]) -> dict[str, Any]:
        """Record a browser-open intent (no real browser in sandbox).

        Expected args: ``{"url": "<URL>"}``
        """
        url: str = args.get("url", "")
        logger.info("browser.open: %s (recorded, not executed in sandbox)", url)
        return {"url": url, "note": "browser.open recorded; not executed in sandbox"}
