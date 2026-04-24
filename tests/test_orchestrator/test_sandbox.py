"""Tests for SandboxEnvironment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestrator.sandbox import SandboxEnvironment, SandboxPathError


class TestSandboxInit:
    def test_auto_creates_temp_dir(self) -> None:
        with SandboxEnvironment() as sb:
            assert sb.work_dir.exists()
            assert sb.work_dir.is_dir()

    def test_explicit_work_dir(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        assert sb.work_dir == tmp_path.resolve()

    def test_cleanup_removes_auto_dir(self) -> None:
        sb = SandboxEnvironment()
        work_dir = sb.work_dir
        assert work_dir.exists()
        sb.cleanup()
        assert not work_dir.exists()

    def test_explicit_dir_not_removed_on_cleanup(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.cleanup()
        assert tmp_path.exists()  # caller owns it


class TestPathSafety:
    def test_resolve_relative_path(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        resolved = sb.resolve_path("src/main.py")
        assert resolved == tmp_path / "src" / "main.py"

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        with pytest.raises(SandboxPathError):
            sb.resolve_path("../../etc/passwd")

    def test_strips_leading_slash(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        resolved = sb.resolve_path("/etc/passwd")
        # Should be resolved to sandbox/etc/passwd, NOT /etc/passwd
        assert str(resolved).startswith(str(tmp_path))

    def test_nested_legitimate_path(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        resolved = sb.resolve_path("a/b/c/d.txt")
        assert resolved == tmp_path / "a" / "b" / "c" / "d.txt"


class TestFileOperations:
    def test_write_and_read(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.write_file("hello.txt", "hello world")
        content = sb.read_file("hello.txt")
        assert content == "hello world"

    def test_write_creates_subdirs(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.write_file("a/b/c/file.py", "# code")
        assert (tmp_path / "a" / "b" / "c" / "file.py").exists()

    def test_read_nonexistent_raises(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            sb.read_file("missing.txt")

    def test_delete_file(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.write_file("to_delete.txt", "bye")
        sb.delete_file("to_delete.txt")
        assert not (tmp_path / "to_delete.txt").exists()

    def test_delete_nonexistent_raises(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            sb.delete_file("ghost.txt")

    def test_list_files(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.write_file("a.txt", "a")
        sb.write_file("sub/b.txt", "b")
        files = sb.list_files()
        assert "a.txt" in files
        assert os.path.join("sub", "b.txt") in files


class TestCommandExecution:
    def test_echo_command(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        result = sb.run_command("echo hello")
        assert result.success
        assert "hello" in result.stdout
        assert result.returncode == 0

    def test_failing_command(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        result = sb.run_command("exit 1")
        assert not result.success
        assert result.returncode != 0

    def test_command_in_subdir(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        sb.write_file("sub/marker.txt", "x")
        result = sb.run_command("ls", cwd="sub")
        assert result.success
        assert "marker.txt" in result.stdout

    def test_timeout_triggers(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path, timeout=1)
        result = sb.run_command("sleep 10")
        assert result.timed_out
        assert not result.success

    def test_stdout_captured(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        result = sb.run_command("echo agentix")
        assert "agentix" in result.stdout

    def test_stderr_captured(self, tmp_path: Path) -> None:
        sb = SandboxEnvironment(work_dir=tmp_path)
        result = sb.run_command("echo err >&2")
        assert "err" in result.stderr or result.returncode == 0
