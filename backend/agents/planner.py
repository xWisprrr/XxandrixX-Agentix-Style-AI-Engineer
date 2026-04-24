"""Planner agent — converts a user goal into a structured project plan."""
from __future__ import annotations

import json
import re

from backend.llm.client import chat_completion
from backend.models import AgentRole, PlanStep, ProjectPlan

SYSTEM_PROMPT = """You are a senior software architect and project planner.
Given a user's goal, you produce a concrete, ordered list of engineering steps to build it.

Each step must be actionable and focused on building software, e.g.:
- Define project structure and dependencies
- Build database models and schema
- Implement authentication system
- Create REST API routes
- Build frontend UI components
- Write integration tests
- Add error handling and validation

Respond ONLY with valid JSON in this format (no markdown fences):
{
  "steps": [
    {"title": "Step title", "description": "What will be built in this step"},
    ...
  ]
}

Keep steps focused. Aim for 4–8 steps. Each step should produce tangible files.
"""


async def create_plan(goal: str, history: list[dict]) -> ProjectPlan:
    """Ask the LLM to create a structured project plan."""
    messages = [
        *history[-6:],  # last few turns for context
        {"role": "user", "content": f"Create a detailed engineering plan for: {goal}"},
    ]
    response = await chat_completion(messages, system_prompt=SYSTEM_PROMPT, temperature=0.3)
    steps = _parse_steps(response)
    return ProjectPlan(goal=goal, steps=steps)


def _parse_steps(raw: str) -> list[PlanStep]:
    """Parse JSON plan from LLM response."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    try:
        data = json.loads(text)
        raw_steps = data.get("steps", [])
        return [
            PlanStep(
                index=i,
                title=s.get("title", f"Step {i+1}"),
                description=s.get("description", ""),
            )
            for i, s in enumerate(raw_steps)
        ]
    except (json.JSONDecodeError, KeyError):
        # Fallback: create a generic plan
        return [
            PlanStep(index=0, title="Setup project structure", description="Create directories and configuration files"),
            PlanStep(index=1, title="Implement core logic", description="Write the main application code"),
            PlanStep(index=2, title="Add tests", description="Write tests for the implementation"),
        ]
