import time

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

    def chat(self, messages, tools=None) -> tuple[ChatCompletionMessage, dict]:
        """Run a chat completion and report per-call telemetry.

        Returns ``(message, telemetry)`` where ``telemetry`` is a dict
        with ``model``, ``prompt_tokens``, ``completion_tokens``, and
        ``latency_ms``. Some local servers (vLLM, Ollama) omit ``usage``;
        the ``getattr`` fallbacks turn that into zeros rather than an
        AttributeError so the Tracer always has something to record.
        """
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        t0 = time.monotonic()
        resp = self._client.chat.completions.create(**kwargs)
        latency_ms = (time.monotonic() - t0) * 1000
        usage = resp.usage
        telemetry = {
            "model": self._model,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "latency_ms": latency_ms,
        }
        return resp.choices[0].message, telemetry
