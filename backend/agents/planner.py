from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from openai import AsyncOpenAI

from backend.core.task_schema import Task, TaskStep

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are an expert software engineering planner. Given a task description, break it into concrete, executable steps.

Return a JSON object with a "steps" array. Each step must have:
{
  "steps": [
    {
      "name": "Short step name",
      "description": "Detailed description of what code to write or command to run",
      "language": "python|javascript|bash",
      "expected_output": "What stdout should contain on success (optional)"
    }
  ]
}

Rules:
- Each step should be independently executable
- Steps should build on each other logically
- 2-6 steps total is ideal
- Prefer Python unless JavaScript or bash is clearly more appropriate
- Return ONLY valid JSON
"""


class Planner:
    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    async def create_steps(self, task: Task) -> List[TaskStep]:
        prompt = f"Task title: {task.title}\nTask description: {task.description}"
        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)

            steps = []
            for i, s in enumerate(data.get("steps", [])):
                steps.append(
                    TaskStep(
                        name=s.get("name", f"Step {i + 1}"),
                        description=s.get("description", ""),
                        language=s.get("language", "python"),
                        expected_output=s.get("expected_output"),
                    )
                )

            if not steps:
                steps = [
                    TaskStep(
                        name="Execute task",
                        description=task.description,
                        language="python",
                    )
                ]

            return steps

        except Exception as exc:
            logger.exception("Planner failed to create steps: %s", exc)
            return [
                TaskStep(
                    name="Execute task",
                    description=task.description,
                    language="python",
                )
            ]
