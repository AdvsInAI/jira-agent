"""Smoke test: confirm the configured LLM endpoint + model are reachable.

Run: uv run python scripts/ping_llm.py
"""

from jira_agent.config import load_config
from jira_agent.llm import LLMClient


def main() -> None:
    cfg = load_config()
    llm = LLMClient(cfg)
    print(f"Endpoint: {cfg.llm_base_url}")
    print(f"Model: {cfg.llm_model}")
    print("Sending: 'Reply with exactly: pong'")
    # LLMClient.chat() returns (message, telemetry) since v0.2.0 — see
    # observability.Tracer. The smoke test ignores the telemetry but still
    # has to unpack the tuple.
    msg, telemetry = llm.chat([{"role": "user", "content": "Reply with exactly: pong"}])
    print(f"Got: {msg.content!r}")
    print(
        f"Tokens: prompt={telemetry['prompt_tokens']} "
        f"completion={telemetry['completion_tokens']} "
        f"latency_ms={telemetry['latency_ms']:.0f}"
    )


if __name__ == "__main__":
    main()
