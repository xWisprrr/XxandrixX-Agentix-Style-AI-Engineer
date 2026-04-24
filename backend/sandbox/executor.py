"""Sandbox executor — runs generated code in a subprocess."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import textwrap
import time
from pathlib import Path

from backend.models import ExecutionResult

# Seconds before we kill a running process
EXECUTION_TIMEOUT = int(os.getenv("EXECUTION_TIMEOUT", "30"))


async def execute_project(project_dir: Path) -> ExecutionResult:
    """
    Detect the project type and run it with an appropriate command.
    Returns stdout, stderr, exit code, and timing info.
    """
    start = time.monotonic()
    cmd, env = _detect_run_command(project_dir)
    if cmd is None:
        return ExecutionResult(
            stdout="",
            stderr="No runnable entry point found. Looking for main.py, index.js, package.json, etc.",
            exit_code=1,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=EXECUTION_TIMEOUT
            )
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            timed_out = True

        duration = time.monotonic() - start
        return ExecutionResult(
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
            exit_code=proc.returncode or 0,
            timed_out=timed_out,
            duration=duration,
        )
    except Exception as exc:
        return ExecutionResult(
            stdout="",
            stderr=f"Executor error: {exc}",
            exit_code=1,
            duration=time.monotonic() - start,
        )


async def install_dependencies(project_dir: Path) -> ExecutionResult:
    """Install project dependencies before running."""
    start = time.monotonic()
    cmd = _detect_install_command(project_dir)
    if cmd is None:
        return ExecutionResult(stdout="No dependency file found, skipping install.", stderr="", exit_code=0)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=120
        )
    except asyncio.TimeoutError:
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
    duration = time.monotonic() - start
    return ExecutionResult(
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        exit_code=proc.returncode or 0,
        duration=duration,
    )


async def run_tests(project_dir: Path) -> ExecutionResult:
    """Run tests if a test framework is detected."""
    start = time.monotonic()
    cmd = _detect_test_command(project_dir)
    if cmd is None:
        return ExecutionResult(stdout="No test command detected.", stderr="", exit_code=0)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=60
        )
    except asyncio.TimeoutError:
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
    duration = time.monotonic() - start
    return ExecutionResult(
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        exit_code=proc.returncode or 0,
        duration=duration,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_run_command(project_dir: Path):
    """Return (cmd_list, env_dict) or (None, None) if nothing found."""
    if (project_dir / "main.py").exists():
        return [sys.executable, "main.py"], None
    if (project_dir / "app.py").exists():
        return [sys.executable, "app.py"], None
    if (project_dir / "server.py").exists():
        return [sys.executable, "server.py"], None
    if (project_dir / "package.json").exists():
        if shutil.which("node"):
            pkg = _read_json(project_dir / "package.json")
            if pkg and "scripts" in pkg and "start" in pkg["scripts"]:
                return ["npm", "start"], None
            if (project_dir / "index.js").exists():
                return ["node", "index.js"], None
    if (project_dir / "index.js").exists() and shutil.which("node"):
        return ["node", "index.js"], None
    # Fallback: run any .py file found at top level
    py_files = list(project_dir.glob("*.py"))
    if py_files:
        return [sys.executable, py_files[0].name], None
    return None, None


def _detect_install_command(project_dir: Path):
    if (project_dir / "requirements.txt").exists():
        return [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"]
    if (project_dir / "package.json").exists() and shutil.which("npm"):
        return ["npm", "install", "--silent"]
    return None


def _detect_test_command(project_dir: Path):
    if (project_dir / "pytest.ini").exists() or (project_dir / "setup.cfg").exists():
        return [sys.executable, "-m", "pytest", "-v"]
    test_files = list(project_dir.glob("test_*.py")) + list(project_dir.glob("*_test.py"))
    if test_files:
        return [sys.executable, "-m", "pytest", "-v"]
    if (project_dir / "package.json").exists() and shutil.which("npm"):
        pkg = _read_json(project_dir / "package.json")
        if pkg and "scripts" in pkg and "test" in pkg["scripts"]:
            return ["npm", "test"]
    return None


def _read_json(path: Path):
    import json
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
