"""Smoke test: confirm the OpenRouter key + configured model are reachable.

Run: uv run python scripts/ping_llm.py
"""

from jira_agent.config import load_config
from jira_agent.llm import LLMClient


def main() -> None:
    cfg = load_config()
    llm = LLMClient(cfg)
    print(f"Model: {cfg.openrouter_model}")
    print("Sending: 'Reply with exactly: pong'")
    msg = llm.chat([{"role": "user", "content": "Reply with exactly: pong"}])
    print(f"Got: {msg.content!r}")


if __name__ == "__main__":
    main()
