"""OpenAI LLM client wrapper."""
from __future__ import annotations

import os
from typing import AsyncIterator

import openai

_client: openai.AsyncOpenAI | None = None


def get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        _client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


MODEL = os.getenv("LLM_MODEL", "gpt-4o")


async def chat_completion(
    messages: list[dict],
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Run a single chat completion and return the full response text."""
    client = get_client()
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    response = await client.chat.completions.create(
        model=MODEL,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def chat_completion_stream(
    messages: list[dict],
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> AsyncIterator[str]:
    """Stream a chat completion, yielding text chunks."""
    client = get_client()
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
