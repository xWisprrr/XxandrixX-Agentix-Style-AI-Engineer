from __future__ import annotations

import logging
import os
from typing import Any, Dict

from openai import AsyncOpenAI

from backend.core.task_schema import TaskStep
from backend.tools.filesystem import FileSystemTool

logger = logging.getLogger(__name__)

CODER_SYSTEM_PROMPT = """You are an expert software engineer. Write production-quality code to accomplish a given step.

Guidelines:
- Write complete, runnable code — no placeholders or TODOs
- Use print() statements to show progress/results in Python
- console.log() in JavaScript
- Include all necessary imports
- Handle errors gracefully
- If creating files, use relative paths within the workspace
- Keep code concise but complete

When writing files to disk in Python, use relative paths. The working directory will be set to the workspace.
Return ONLY the code — no markdown fences, no explanation.
"""


class Coder:
    def __init__(self) -> None:
        self._client = None
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self._fs = FileSystemTool()

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    async def execute_step(
        self,
        step: TaskStep,
        workspace_path: str,
        context: Dict[str, Any],
    ) -> str:
        context_summary = ""
        if context:
            parts = []
            for step_id, info in context.items():
                parts.append(f"- {info['name']}: output='{info.get('output', '')[:200]}', files={info.get('files', [])}")
            context_summary = "Previous steps:\n" + "\n".join(parts)

        user_prompt = f"""Step: {step.name}
Description: {step.description}
Language: {step.language}
Workspace directory: {workspace_path}
{context_summary}

Write the {step.language} code to accomplish this step."""

        if step.expected_output:
            user_prompt += f"\nExpected output should contain: {step.expected_output}"

        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": CODER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            code = response.choices[0].message.content or ""
            # Strip markdown code fences if present
            code = _strip_code_fences(code)
            return code

        except Exception as exc:
            logger.exception("Coder LLM call failed: %s", exc)
            lang = step.language
            if lang == "python":
                return f"print('Step: {step.name}\\nDescription: {step.description}')"
            elif lang in ("javascript", "node"):
                return f"console.log('Step: {step.name}');"
            else:
                return f"echo 'Step: {step.name}'"


def _strip_code_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
