from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from .config import Config

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMClient:
    """Thin wrapper over an OpenAI-compatible endpoint.

    Swap point: change base_url/model to point at any OpenAI-compatible
    provider (vLLM, Ollama, Together, Groq). Tool-call format is shared.
    """

    def __init__(self, config: Config):
        self._client = OpenAI(
            api_key=config.openrouter_api_key,
            base_url=OPENROUTER_BASE_URL,
        )
        self._model = config.openrouter_model

    def chat(self, messages, tools=None) -> ChatCompletionMessage:
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message
