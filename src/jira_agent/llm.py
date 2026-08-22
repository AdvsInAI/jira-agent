from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

from .config import LLMConfig


class LLMClient:
    """Thin wrapper over an OpenAI-compatible endpoint.

    Swap point: change LLM_BASE_URL and LLM_MODEL in .env to point at any
    OpenAI-compatible provider (OpenRouter, vLLM, Ollama, Together, Groq).
    Tool-call format is shared.
    """

    def __init__(self, config: LLMConfig):
        self._client = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._model = config.llm_model

    async def chat(self, messages, tools=None) -> ChatCompletionMessage:
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message
