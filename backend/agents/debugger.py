from __future__ import annotations

import logging
import os
from typing import Any, Dict

from openai import AsyncOpenAI

from backend.core.task_schema import TaskStep

logger = logging.getLogger(__name__)

DEBUGGER_SYSTEM_PROMPT = """You are an expert software debugger. Given broken code and an error message, fix the code.

Return ONLY the corrected code — no markdown fences, no explanation.
Ensure the fix addresses the root cause of the error.
Keep as much of the original logic as possible.
"""


class Debugger:
    def __init__(self) -> None:
        self._client = None
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    async def fix(
        self,
        step: TaskStep,
        error: str,
        context: Dict[str, Any],
    ) -> TaskStep:
        prompt = f"""Step: {step.name}
Description: {step.description}
Language: {step.language}

Broken code:
{step.code}

Error:
{error[:2000]}

Fix the code so it runs correctly."""

        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": DEBUGGER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            fixed_code = response.choices[0].message.content or step.code or ""
            fixed_code = _strip_code_fences(fixed_code)
            step.code = fixed_code

        except Exception as exc:
            logger.exception("Debugger LLM call failed: %s", exc)

        return step


def _strip_code_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
