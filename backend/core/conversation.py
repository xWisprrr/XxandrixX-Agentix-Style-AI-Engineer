from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from openai import AsyncOpenAI

from backend.core.task_schema import ConversationMessage, Task, TaskStep

logger = logging.getLogger(__name__)

PARSE_SYSTEM_PROMPT = """You are an AI software engineering assistant. Your job is to parse user messages into structured engineering tasks.

Given a user message and conversation history, return a JSON object with the following structure:
{
  "title": "Short task title",
  "description": "Detailed description of what needs to be accomplished",
  "steps": [
    {
      "name": "Step name",
      "description": "What this step does",
      "language": "python|javascript|bash",
      "expected_output": "What successful output looks like (optional)"
    }
  ]
}

Rules:
- Break complex tasks into 2-6 concrete, executable steps
- Each step should produce runnable code or a command
- Choose the most appropriate language per step
- Be specific about expected outputs when possible
- Return ONLY valid JSON, no markdown, no explanation
"""


class ConversationController:
    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    async def parse_message(
        self,
        user_message: str,
        history: Optional[List[ConversationMessage]] = None,
    ) -> Task:
        history = history or []

        messages = [{"role": "system", "content": PARSE_SYSTEM_PROMPT}]
        for msg in history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)

            steps = [
                TaskStep(
                    name=s.get("name", f"Step {i + 1}"),
                    description=s.get("description", ""),
                    language=s.get("language", "python"),
                    expected_output=s.get("expected_output"),
                )
                for i, s in enumerate(data.get("steps", []))
            ]

            if not steps:
                steps = [
                    TaskStep(
                        name="Execute task",
                        description=data.get("description", user_message),
                        language="python",
                    )
                ]

            return Task(
                title=data.get("title", "Untitled Task"),
                description=data.get("description", user_message),
                steps=steps,
            )

        except Exception as exc:
            logger.exception("Failed to parse user message into task: %s", exc)
            return Task(
                title="User Request",
                description=user_message,
                steps=[
                    TaskStep(
                        name="Execute request",
                        description=user_message,
                        language="python",
                    )
                ],
            )
