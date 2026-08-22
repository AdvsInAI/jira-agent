"""Asynchronous OpenAI-compatible LLM client with per-call telemetry."""

import time

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

from .config import LLMConfig


class LLMClient:
    def __init__(self, config: LLMConfig):
        self._client = AsyncOpenAI(
            api_key=config.llm_api_key, base_url=config.llm_base_url
        )
        self._model = config.llm_model

    async def chat(self, messages, tools=None) -> tuple[ChatCompletionMessage, dict]:
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        started = time.monotonic()
        response = await self._client.chat.completions.create(**kwargs)
        usage = response.usage
        telemetry = {
            "model": self._model,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "latency_ms": (time.monotonic() - started) * 1000,
        }
        return response.choices[0].message, telemetry
