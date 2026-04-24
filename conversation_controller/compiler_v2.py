"""CompilerV2: execution-aware TaskGraph compiler (v2).

This module upgrades the v1 ConversationController into an execution-aware
compiler.  It post-processes a compiled :class:`~conversation_controller.schema.TaskGraph`
to add:

* per-step risk scoring (low / medium / high)
* dependency inference between steps
* runtime feasibility checks per step type
* sandbox-awareness heuristics
* dynamic step splitting when a step is too broad

The output is an :class:`EnhancedTaskGraph` that is a strict superset of the
original :class:`TaskGraph` — the existing :class:`OrchestratorRunner` remains
fully compatible because it reads only ``execution_plan``, which is preserved
unchanged, while the new ``enhanced_execution_plan`` carries the enriched data.

Usage::

    from conversation_controller.compiler_v2 import CompilerV2

    compiler = CompilerV2(llm_client=my_client)
    enhanced = compiler.compile("Build a Flask CRUD API with auth")
    for step in enhanced.enhanced_execution_plan:
        print(step.step_id, step.risk, step.execution_notes)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from conversation_controller.controller import ConversationController
from conversation_controller.schema import ExecutionStep, TaskGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk classification helpers
# ---------------------------------------------------------------------------

_HIGH_RISK_PATTERNS = re.compile(
    r"\b(auth|authentication|password|secret|token|jwt|oauth|payment|billing|"
    r"credit.?card|stripe|charge|delete|drop|truncate|rm\s+-rf|destroy|wipe|"
    r"migrate|migration|sudo|chmod|chown|root|admin)\b",
    re.IGNORECASE,
)

_MEDIUM_RISK_PATTERNS = re.compile(
    r"\b(install|pip|npm|yarn|apt|brew|curl|wget|http|https|network|socket|"
    r"database|db|sql|mongo|redis|subprocess|exec|eval|env|environment|"
    r"config|secret|credential|key|certificate)\b",
    re.IGNORECASE,
)

_INFEASIBLE_IN_SANDBOX = re.compile(
    r"\b(browser|chrome|firefox|selenium|playwright|display|gui|xvfb|xdg|"
    r"dbus|systemd|service|daemon|cron|docker|podman|kubectl|k8s|vagrant|"
    r"virtualbox|vmware)\b",
    re.IGNORECASE,
)

_NETWORK_REQUIRED = re.compile(
    r"\b(curl|wget|pip\s+install|npm\s+install|yarn|apt-get|brew\s+install|"
    r"requests\.get|fetch|http|https|socket\.connect)\b",
    re.IGNORECASE,
)

# Max token estimate before a step is considered "too large" to split
_SPLIT_ACTION_LENGTH = 200


# ---------------------------------------------------------------------------
# Enhanced models
# ---------------------------------------------------------------------------


class EnhancedExecutionStep(BaseModel):
    """An :class:`ExecutionStep` enriched with compiler-v2 metadata.

    The ``id`` field is a convenience alias for ``step_id`` and matches the
    output schema described in the problem spec.  All original ``ExecutionStep``
    fields are preserved so the orchestrator can continue to consume the
    ``execution_plan`` list of plain :class:`ExecutionStep` objects.
    """

    # Original ExecutionStep fields (copied so this model is self-contained)
    step_id: int
    type: Literal["architecture", "code", "test", "exec", "modify", "debug"] = "code"
    action: str = ""
    target: str = ""
    depends_on: list[int] = Field(default_factory=list)

    # v2 additions
    id: str = ""
    risk: Literal["low", "medium", "high"] = "low"
    execution_notes: str = ""
    feasible_in_sandbox: bool = True
    split_from: int | None = None  # original step_id if this was split

    def to_execution_step(self) -> ExecutionStep:
        """Convert back to a plain :class:`ExecutionStep` for v1 compatibility."""
        return ExecutionStep(
            step_id=self.step_id,
            type=self.type,
            action=self.action,
            target=self.target,
            depends_on=self.depends_on,
        )


class EnhancedTaskGraph(TaskGraph):
    """A :class:`TaskGraph` extended with the v2 enhanced execution plan.

    The original ``execution_plan`` list is preserved intact so that
    :class:`~orchestrator.runner.OrchestratorRunner` v1 continues to work
    without modification.  The ``enhanced_execution_plan`` carries the same
    steps with additional metadata.
    """

    enhanced_execution_plan: list[EnhancedExecutionStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CompilerV2
# ---------------------------------------------------------------------------


class CompilerV2:
    """Execution-aware TaskGraph compiler.

    Wraps :class:`~conversation_controller.controller.ConversationController`
    and enriches its output with risk scores, dependency annotations, sandbox
    feasibility notes, and optional step splitting.

    Args:
        llm_client: Passed directly to the underlying v1 controller.
        model: LLM model name used by the v1 controller.
        max_step_action_length: Steps whose ``action`` field exceeds this
            character count are candidates for splitting.
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: str = "gpt-4o",
        max_step_action_length: int = _SPLIT_ACTION_LENGTH,
    ) -> None:
        self._v1 = ConversationController(llm_client=llm_client, model=model)
        self._max_action_len = max_step_action_length

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, raw_message: str) -> EnhancedTaskGraph:
        """Compile *raw_message* into an :class:`EnhancedTaskGraph`.

        Steps:
        1. Delegates compilation to the v1 controller.
        2. Enriches each step with risk score, feasibility notes, and
           inferred dependencies.
        3. Optionally splits overly broad steps.
        4. Wraps the result in :class:`EnhancedTaskGraph`.

        Args:
            raw_message: The verbatim user message.

        Returns:
            An :class:`EnhancedTaskGraph` compatible with both v1 and v2
            orchestrators.
        """
        base_graph = self._v1.compile(raw_message)
        return self.enhance(base_graph)

    def enhance(self, task_graph: TaskGraph) -> EnhancedTaskGraph:
        """Enrich an existing :class:`TaskGraph` produced by v1.

        This is the core enrichment pass.  It can also be called directly
        to upgrade a v1 graph without going through the LLM again.

        Args:
            task_graph: A fully validated v1 :class:`TaskGraph`.

        Returns:
            An :class:`EnhancedTaskGraph` with populated
            ``enhanced_execution_plan``.
        """
        raw_steps = task_graph.execution_plan
        enhanced: list[EnhancedExecutionStep] = []

        for step in raw_steps:
            # 1. Score risk
            risk = self._score_risk(step, task_graph)

            # 2. Feasibility checks
            feasible, notes = self._check_feasibility(step, task_graph)

            # 3. Infer explicit dependency IDs
            deps = list(step.depends_on)
            inferred = self._infer_dependencies(step, raw_steps, enhanced)
            for d in inferred:
                if d not in deps:
                    deps.append(d)

            base_enhanced = EnhancedExecutionStep(
                step_id=step.step_id,
                type=step.type,
                action=step.action,
                target=step.target,
                depends_on=deps,
                id=str(step.step_id),
                risk=risk,
                execution_notes=notes,
                feasible_in_sandbox=feasible,
            )

            # 4. Dynamic splitting
            sub_steps = self._maybe_split(base_enhanced)
            enhanced.extend(sub_steps)

        data = task_graph.model_dump()
        data["enhanced_execution_plan"] = [s.model_dump() for s in enhanced]
        result = EnhancedTaskGraph.model_validate(data)
        logger.info(
            "CompilerV2 enhanced task_id=%s steps=%d → enhanced_steps=%d",
            result.task_id,
            len(raw_steps),
            len(enhanced),
        )
        return result

    def reset_memory(self) -> None:
        """Clear the underlying v1 controller memory."""
        self._v1.reset_memory()

    @property
    def memory(self):
        """Expose the v1 controller memory for compatibility."""
        return self._v1.memory

    # ------------------------------------------------------------------
    # Risk scoring
    # ------------------------------------------------------------------

    def _score_risk(self, step: ExecutionStep, graph: TaskGraph) -> Literal["low", "medium", "high"]:
        """Assign a risk level to *step* based on heuristics.

        Priority: high > medium > low.  The graph-level ``risk_level`` acts
        as a floor (a graph marked high elevates all steps).
        """
        combined = f"{step.action} {step.target} {step.type}"
        if _HIGH_RISK_PATTERNS.search(combined):
            return "high"
        if graph.risk_level == "high":
            return "high"
        if _MEDIUM_RISK_PATTERNS.search(combined):
            return "medium"
        if step.type in ("exec",):
            return "medium"
        if graph.risk_level == "medium":
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Feasibility checks
    # ------------------------------------------------------------------

    def _check_feasibility(
        self, step: ExecutionStep, graph: TaskGraph
    ) -> tuple[bool, str]:
        """Return ``(feasible, notes)`` for *step* given sandbox constraints.

        When ``require_sandbox_execution`` is True in the graph constraints,
        steps that require a real browser, GUI, or persistent system service
        are flagged as potentially infeasible.
        """
        notes_parts: list[str] = []
        feasible = True

        if graph.constraints.require_sandbox_execution:
            combined = f"{step.action} {step.target}"
            if _INFEASIBLE_IN_SANDBOX.search(combined):
                feasible = False
                notes_parts.append(
                    "WARNING: step may require a GUI/browser/system-service "
                    "that is not available in a headless sandbox."
                )
            if _NETWORK_REQUIRED.search(combined):
                notes_parts.append(
                    "NOTE: step may require outbound network access; ensure "
                    "sandbox allows it or pre-stage dependencies."
                )

        if step.type == "exec":
            notes_parts.append(
                "exec step: verify command idempotency before retrying."
            )
        elif step.type == "test":
            notes_parts.append(
                "test step: expected to exit 0 on success; non-zero triggers retry."
            )
        elif step.type == "debug":
            notes_parts.append(
                "debug step: inspect prior step outputs before applying fix."
            )

        return feasible, " | ".join(notes_parts) if notes_parts else "No special notes."

    # ------------------------------------------------------------------
    # Dependency inference
    # ------------------------------------------------------------------

    def _infer_dependencies(
        self,
        step: ExecutionStep,
        all_steps: list[ExecutionStep],
        already_enhanced: list[EnhancedExecutionStep],
    ) -> list[int]:
        """Infer implicit dependencies for *step* by scanning prior step targets.

        A dependency is inferred when a prior step's ``target`` appears inside
        the current step's ``action`` text (e.g. step 2's action references
        ``main.py`` which step 1 creates → 2 depends on 1).
        """
        inferred: list[int] = []
        for prior in all_steps:
            if prior.step_id >= step.step_id:
                continue
            if not prior.target:
                continue
            # Normalise the filename (strip path prefix for matching)
            filename = prior.target.split("/")[-1]
            if filename and filename in step.action:
                inferred.append(prior.step_id)
        return inferred

    # ------------------------------------------------------------------
    # Dynamic step splitting
    # ------------------------------------------------------------------

    def _maybe_split(self, step: EnhancedExecutionStep) -> list[EnhancedExecutionStep]:
        """Split *step* into sub-steps if its action description is too broad.

        Splitting is purely syntactic — the original step is broken on
        sentence-boundary markers (';', '.  ', ' and then ', ' then ').
        Each sub-step inherits the parent's risk and feasibility but gets a
        fractional ``step_id`` suffix encoded in the ``id`` field (e.g.
        "3.1", "3.2") while the numeric ``step_id`` stays unchanged so the
        v1 orchestrator dependency graph is not disturbed.
        """
        if len(step.action) <= self._max_action_len:
            return [step]

        # Split on natural language delimiters
        parts = re.split(r";\s*|\.\s{2,}|\band then\b|\bthen\b", step.action)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            return [step]

        sub_steps: list[EnhancedExecutionStep] = []
        for idx, part in enumerate(parts, start=1):
            sub = EnhancedExecutionStep(
                step_id=step.step_id,
                type=step.type,
                action=part,
                target=step.target,
                depends_on=step.depends_on if idx == 1 else [step.step_id],
                id=f"{step.step_id}.{idx}",
                risk=step.risk,
                execution_notes=step.execution_notes
                + f" | Sub-step {idx}/{len(parts)} split from original.",
                feasible_in_sandbox=step.feasible_in_sandbox,
                split_from=step.step_id,
            )
            sub_steps.append(sub)

        logger.debug(
            "Split step_id=%d into %d sub-steps", step.step_id, len(sub_steps)
        )
        return sub_steps
