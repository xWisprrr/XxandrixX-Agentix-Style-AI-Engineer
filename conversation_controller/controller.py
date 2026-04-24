"""ConversationController: compiles natural language into executable TaskGraph plans."""

from __future__ import annotations

import json
import logging
from typing import Any

from conversation_controller.memory import ConversationMemory
from conversation_controller.prompts import SYSTEM_PROMPT, build_user_prompt
from conversation_controller.schema import TaskGraph

logger = logging.getLogger(__name__)


class ConversationController:
    """Compiles a raw user message into a validated TaskGraph.

    This class is the bridge between the Chat UI and the Orchestrator. It is
    NOT an agent — it is a deterministic compiler that calls an LLM once per
    user message and produces a structured, validated execution plan.

    Args:
        llm_client: An OpenAI-compatible client instance (duck-typed). If None,
            the controller attempts to instantiate ``openai.OpenAI()``.
        model: The LLM model name to use for compilation.
    """

    def __init__(self, llm_client: Any = None, model: str = "gpt-4o") -> None:
        """Initialise the controller with an optional LLM client and model name."""
        self._model = model
        self._memory = ConversationMemory()

        if llm_client is not None:
            self._client = llm_client
        else:
            try:
                import openai  # noqa: PLC0415

                self._client = openai.OpenAI()
                logger.debug("Initialised default openai.OpenAI() client.")
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(
                    "No llm_client provided and openai.OpenAI() could not be created. "
                    "Pass an explicit llm_client or set OPENAI_API_KEY."
                ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, raw_message: str) -> TaskGraph:
        """Compile a raw user message into a validated TaskGraph.

        The method:
        1. Builds the prompt from ``prompts.py``.
        2. Calls the LLM with JSON mode enabled.
        3. Parses and validates the response with ``TaskGraph.model_validate``.
        4. Updates memory with the ``follow_up_memory`` field from the result.

        Args:
            raw_message: The verbatim message from the user.

        Returns:
            A fully validated :class:`TaskGraph` instance.

        Raises:
            ValueError: If the LLM response cannot be parsed or validated.
        """
        memory_context = self._memory.to_context()
        user_prompt = build_user_prompt(raw_message, memory_context)

        logger.debug("Calling LLM model=%s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_json: str = response.choices[0].message.content
        logger.debug("LLM raw response (first 200 chars): %s", raw_json[:200])

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

        task_graph = TaskGraph.model_validate(data)
        self._memory.update(task_graph.follow_up_memory.model_dump())
        logger.info("Compiled TaskGraph task_id=%s", task_graph.task_id)
        return task_graph

    def reset_memory(self) -> None:
        """Clear the conversation memory."""
        self._memory.reset()
        logger.debug("ConversationController memory reset.")

    @property
    def memory(self) -> ConversationMemory:
        """The current :class:`ConversationMemory` instance."""
        return self._memory
