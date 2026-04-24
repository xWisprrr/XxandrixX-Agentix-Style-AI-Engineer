"""ProjectStateGraph: structured runtime memory model for Agentix.

This module maintains a persistent, in-process model of the evolving project
state across an entire execution run.  It is designed to be read by the
Orchestrator before execution begins, updated after each step, and queried by
the Debugger and Coder agents to obtain rich context.

Architecture
------------

The graph stores four primary data structures:

* **File nodes** — per-file metadata including content snapshot, inferred
  dependencies (imports / includes), and last-execution record.
* **Execution history** — ordered list of step outcomes with timestamps,
  stdout/stderr snapshots, and exit codes.
* **Failure history map** — per-step list of failure records so the Debugger
  can see the full error evolution for a given step.
* **Artifact registry** — ephemeral outputs (logs, test reports, coverage
  files) keyed by step ID.

Usage::

    from runtime.project_state_graph import ProjectStateGraph

    graph = ProjectStateGraph()

    # Record a new file
    graph.add_file("src/app.py", content="# app", dependencies=["src/models.py"])

    # After a step executes
    graph.update_execution(step_id=1, result={"status": "success", "stdout": "OK"})

    # After a step fails
    graph.record_failure(step_id=2, error="ImportError: ...", context={"attempt": 1})

    # Query full context for injection into prompts
    ctx = graph.get_context()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStateGraph:
    """Structured runtime memory that tracks an evolving software project.

    All public methods are safe to call from multiple threads provided that
    only one writer operates at a time.  The class is intentionally kept
    free of external dependencies so it can be used from any layer of the
    system.

    Integration points:

    * **Orchestrator** — reads :meth:`get_context` before execution starts;
      calls :meth:`update_execution` and :meth:`add_file` after each step.
    * **Debugger** — calls :meth:`get_failure_history` to obtain the full
      failure context for a step before generating a fix.
    * **Coder** — calls :meth:`get_context` to obtain existing file list and
      dependency graph to avoid redundant generation.
    """

    def __init__(self) -> None:
        # path → FileNode dict
        self._files: dict[str, dict[str, Any]] = {}
        # Ordered list of execution records
        self._execution_history: list[dict[str, Any]] = []
        # step_id (str) → list[FailureRecord]
        self._failure_history: dict[str, list[dict[str, Any]]] = {}
        # step_id (str) → list of artifact dicts
        self._artifacts: dict[str, list[dict[str, Any]]] = {}
        # Detected entry point files (e.g. main.py, app.py, index.js)
        self._entry_points: list[str] = []
        # Currently active/relevant module paths
        self._active_modules: list[str] = []

    # ------------------------------------------------------------------
    # File graph
    # ------------------------------------------------------------------

    def add_file(
        self,
        path: str,
        content: str = "",
        dependencies: list[str] | None = None,
    ) -> None:
        """Record a file in the project graph.

        If the file already exists its content and dependencies are updated
        in-place; the original creation timestamp is preserved.

        Args:
            path: Project-relative file path (e.g. ``"src/app.py"``).
            content: Current file content (may be empty for binary files).
            dependencies: List of other file paths this file depends on
                (e.g. explicit imports).  When *None* the existing dependency
                list is retained for updates, or initialised to ``[]`` for
                new files.
        """
        if path in self._files:
            node = self._files[path]
            node["content"] = content
            node["last_modified"] = _now_iso()
            if dependencies is not None:
                node["dependencies"] = dependencies
        else:
            self._files[path] = {
                "path": path,
                "content": content,
                "dependencies": dependencies or [],
                "created_at": _now_iso(),
                "last_modified": _now_iso(),
                "execution_count": 0,
                "last_execution": None,
            }
            self._detect_entry_point(path, content)

        logger.debug("ProjectStateGraph.add_file: %s", path)

    def get_file(self, path: str) -> dict[str, Any] | None:
        """Return the file node for *path*, or *None* if not tracked."""
        return self._files.get(path)

    def list_files(self) -> list[str]:
        """Return all tracked file paths, sorted."""
        return sorted(self._files.keys())

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return a mapping of ``path → [dependency paths]``."""
        return {path: list(node["dependencies"]) for path, node in self._files.items()}

    # ------------------------------------------------------------------
    # Execution history
    # ------------------------------------------------------------------

    def update_execution(
        self,
        step_id: int | str,
        result: dict[str, Any],
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record the outcome of executing a step.

        Args:
            step_id: The step identifier from the TaskGraph.
            result: Execution outcome dict.  Expected keys: ``status``
                (``"success"`` | ``"failure"``), ``stdout``, ``stderr``,
                ``exit_code``, ``duration_ms``.  Unknown keys are stored
                as-is.
            artifacts: Optional list of artifact dicts (e.g. log files,
                test reports).  Each dict should have at least a ``"path"``
                key.
        """
        step_key = str(step_id)
        record = {
            "step_id": step_key,
            "timestamp": _now_iso(),
            "result": result,
        }
        self._execution_history.append(record)

        if artifacts:
            existing = self._artifacts.setdefault(step_key, [])
            existing.extend(artifacts)

        # Update per-file execution counters for files touched by this step
        status = result.get("status", "unknown")
        for path, node in self._files.items():
            if path in str(result):
                node["execution_count"] = node.get("execution_count", 0) + 1
                node["last_execution"] = {
                    "step_id": step_key,
                    "status": status,
                    "timestamp": _now_iso(),
                }

        logger.debug("ProjectStateGraph.update_execution: step=%s status=%s", step_key, status)

    def get_execution_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return execution history, newest first.

        Args:
            limit: Maximum number of records to return.  *None* returns all.
        """
        history = list(reversed(self._execution_history))
        if limit is not None:
            history = history[:limit]
        return history

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    def record_failure(
        self,
        step_id: int | str,
        error: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a step failure in the failure history map.

        Multiple failures for the same step are accumulated so the Debugger
        can see the full error evolution.

        Args:
            step_id: The step identifier from the TaskGraph.
            error: The error message or exception string.
            context: Optional additional context (e.g. attempt number,
                relevant file content snippet, stack trace).
        """
        step_key = str(step_id)
        failures = self._failure_history.setdefault(step_key, [])
        failures.append({
            "timestamp": _now_iso(),
            "error": error,
            "context": context or {},
            "attempt": len(failures) + 1,
        })
        logger.warning(
            "ProjectStateGraph.record_failure: step=%s attempt=%d error=%s",
            step_key,
            len(failures),
            error[:120],
        )

    def get_failure_history(self, step_id: int | str) -> list[dict[str, Any]]:
        """Return all recorded failures for *step_id*.

        Args:
            step_id: The step identifier to look up.

        Returns:
            List of failure records, oldest first.  Empty list when the step
            has no recorded failures.
        """
        return list(self._failure_history.get(str(step_id), []))

    def get_all_failures(self) -> dict[str, list[dict[str, Any]]]:
        """Return the complete failure history map (step_id → failures)."""
        return {k: list(v) for k, v in self._failure_history.items()}

    def has_repeated_failure(self, step_id: int | str, threshold: int = 2) -> bool:
        """Return True when *step_id* has failed at least *threshold* times."""
        return len(self._failure_history.get(str(step_id), [])) >= threshold

    # ------------------------------------------------------------------
    # Active modules / entry points
    # ------------------------------------------------------------------

    def set_active_modules(self, modules: list[str]) -> None:
        """Set the list of currently active module paths."""
        self._active_modules = list(modules)

    def set_entry_points(self, entry_points: list[str]) -> None:
        """Explicitly set the project entry points."""
        self._entry_points = list(entry_points)

    # ------------------------------------------------------------------
    # Context snapshot
    # ------------------------------------------------------------------

    def get_context(self) -> dict[str, Any]:
        """Return a serialisable snapshot of the current project state.

        This dict is suitable for injecting into LLM prompts, logging, or
        streaming to the frontend via a ``project_state_updated`` event.

        Returns:
            A dict containing:

            * ``files`` — sorted list of tracked file paths.
            * ``dependency_graph`` — path → [dependency paths].
            * ``entry_points`` — detected or explicitly set entry points.
            * ``active_modules`` — currently active module paths.
            * ``recent_executions`` — last 5 execution records.
            * ``failure_summary`` — per-step failure counts.
            * ``artifact_keys`` — step IDs that have associated artifacts.
        """
        failure_summary = {
            step_id: len(failures)
            for step_id, failures in self._failure_history.items()
            if failures
        }
        return {
            "files": self.list_files(),
            "dependency_graph": self.get_dependency_graph(),
            "entry_points": list(self._entry_points),
            "active_modules": list(self._active_modules),
            "recent_executions": self.get_execution_history(limit=5),
            "failure_summary": failure_summary,
            "artifact_keys": list(self._artifacts.keys()),
            "total_files": len(self._files),
            "total_executions": len(self._execution_history),
        }

    def summary(self) -> str:
        """Return a short human-readable summary for logging / narration."""
        file_count = len(self._files)
        exec_count = len(self._execution_history)
        fail_steps = len(self._failure_history)
        return (
            f"{file_count} file(s) tracked | "
            f"{exec_count} execution(s) recorded | "
            f"{fail_steps} step(s) with failures"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    _ENTRY_POINT_NAMES = frozenset({
        "main.py", "app.py", "server.py", "run.py", "index.js",
        "index.ts", "main.go", "main.rs", "main.rb", "main.java",
        "manage.py", "wsgi.py", "asgi.py",
    })

    def _detect_entry_point(self, path: str, content: str) -> None:
        """Heuristically add *path* to entry points list."""
        filename = path.split("/")[-1].lower()
        if filename in self._ENTRY_POINT_NAMES:
            if path not in self._entry_points:
                self._entry_points.append(path)
