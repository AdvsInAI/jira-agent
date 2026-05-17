"""Interactive CLI: a REPL that pipes user input through the Agent.

Tool calls are surfaced inline so you can watch the agent's reasoning step
by step.

Run: uv run jira-agent
  (or: uv run python -m jira_agent.cli)
"""

import atexit
import json
import readline
import sys
from pathlib import Path

from .agent import Agent
from .config import load_config

HISTORY_FILE = Path.home() / ".jira_agent_history"
HISTORY_LENGTH = 1000


def _setup_readline() -> None:
    try:
        readline.read_history_file(HISTORY_FILE)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(HISTORY_LENGTH)
    readline.parse_and_bind("tab: self-insert")
    atexit.register(_save_history)


def _save_history() -> None:
    try:
        readline.write_history_file(HISTORY_FILE)
    except OSError:
        pass


def _show_tool_call(name: str, args: dict, result: dict) -> None:
    args_str = json.dumps(args, ensure_ascii=False)
    print(f"  -> {name}({args_str})", file=sys.stderr)
    if result.get("ok"):
        preview = json.dumps(result["result"], ensure_ascii=False)
        if len(preview) > 300:
            preview = preview[:300] + "..."
        print(f"  <- ok: {preview}", file=sys.stderr)
    else:
        print(f"  <- error: {result.get('error')}", file=sys.stderr)


def main() -> None:
    cfg = load_config()
    _setup_readline()
    agent = Agent(cfg, on_tool_call=_show_tool_call)

    print(f"Jira agent ready. Model: {cfg.llm_model}")
    print("Type a request. Ctrl+D or /exit to quit.\n")

    exit_commands = {"/exit", "/quit"}
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input in exit_commands:
            break
        try:
            reply = agent.chat(user_input)
        except KeyboardInterrupt:
            print("\n(interrupted)", file=sys.stderr)
            continue
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            continue
        print(f"\n{reply}\n")


if __name__ == "__main__":
    main()
