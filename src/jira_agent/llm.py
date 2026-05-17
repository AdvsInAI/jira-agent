from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from .config import Config


class LLMClient:
    """Thin wrapper over an OpenAI-compatible endpoint.

    Swap point: change LLM_BASE_URL and LLM_MODEL in .env to point at any
    OpenAI-compatible provider (OpenRouter, vLLM, Ollama, Together, Groq).
    Tool-call format is shared.
    """

    def __init__(self, config: Config):
        self._client = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._model = config.llm_model

    def chat(self, messages, tools=None) -> ChatCompletionMessage:
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message
