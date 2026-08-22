"""Smoke test: confirm the configured LLM endpoint + model are reachable.

Run: uv run python scripts/ping_llm.py
"""

import asyncio

from jira_agent.config import load_config
from jira_agent.llm import LLMClient


async def _main() -> None:
    cfg = load_config()
    llm = LLMClient(cfg.llm)
    print(f"Endpoint: {cfg.llm.llm_base_url}")
    print(f"Model: {cfg.llm.llm_model}")
    print("Sending: 'Reply with exactly: pong'")
    msg, telemetry = await llm.chat(
        [{"role": "user", "content": "Reply with exactly: pong"}]
    )
    print(f"Got: {msg.content!r}")
    print(
        f"Tokens: prompt={telemetry['prompt_tokens']} "
        f"completion={telemetry['completion_tokens']} "
        f"latency_ms={telemetry['latency_ms']:.0f}"
    )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
