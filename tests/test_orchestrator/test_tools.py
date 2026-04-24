"""Tests for ToolDispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from conversation_controller.schema import ToolCall
from orchestrator.sandbox import SandboxEnvironment
from orchestrator.tools import ToolDispatcher


def make_dispatcher(tmp_path: Path) -> ToolDispatcher:
    sb = SandboxEnvironment(work_dir=tmp_path)
    return ToolDispatcher(sb)


class TestFilesystemWrite:
    def test_writes_file(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.write", args={"path": "out.txt", "content": "hi"})
        result = d.dispatch(tc)
        assert result.status == "success"
        assert (tmp_path / "out.txt").read_text() == "hi"

    def test_output_includes_bytes_written(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.write", args={"path": "f.txt", "content": "abc"})
        result = d.dispatch(tc)
        assert result.output["bytes_written"] == 3

    def test_missing_path_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.write", args={"content": "data"})
        result = d.dispatch(tc)
        assert result.status == "failure"
        assert result.error is not None

    def test_creates_subdirectories(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.write", args={"path": "a/b/c.py", "content": "#"})
        result = d.dispatch(tc)
        assert result.status == "success"
        assert (tmp_path / "a" / "b" / "c.py").exists()


class TestFilesystemRead:
    def test_reads_file(self, tmp_path: Path) -> None:
        (tmp_path / "r.txt").write_text("read me")
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.read", args={"path": "r.txt"})
        result = d.dispatch(tc)
        assert result.status == "success"
        assert result.output["content"] == "read me"

    def test_missing_file_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.read", args={"path": "ghost.txt"})
        result = d.dispatch(tc)
        assert result.status == "failure"

    def test_missing_path_arg_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="filesystem.read", args={})
        result = d.dispatch(tc)
        assert result.status == "failure"


class TestTerminalRun:
    def test_echo_succeeds(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="terminal.run", args={"command": "echo ok"})
        result = d.dispatch(tc)
        assert result.status == "success"
        assert "ok" in result.output["stdout"]

    def test_failing_command_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="terminal.run", args={"command": "exit 1"})
        result = d.dispatch(tc)
        assert result.status == "failure"

    def test_missing_command_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="terminal.run", args={})
        result = d.dispatch(tc)
        assert result.status == "failure"

    def test_returncode_in_output(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="terminal.run", args={"command": "echo x"})
        result = d.dispatch(tc)
        assert result.output["returncode"] == 0


class TestBrowserOpen:
    def test_records_url(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall(tool="browser.open", args={"url": "https://example.com"})
        result = d.dispatch(tc)
        assert result.status == "success"
        assert result.output["url"] == "https://example.com"
        assert "sandbox" in result.output["note"].lower()


class TestUnknownTool:
    def test_unknown_tool_returns_failure(self, tmp_path: Path) -> None:
        d = make_dispatcher(tmp_path)
        tc = ToolCall.__new__(ToolCall)
        # Bypass validation to set unsupported tool name
        object.__setattr__(tc, "tool", "nonexistent.tool")
        object.__setattr__(tc, "args", {})
        result = d.dispatch(tc)
        assert result.status == "failure"
        assert "Unknown tool" in result.error
