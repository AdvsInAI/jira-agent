"""Interactive Jira agent CLI with MCP-backed tools and write approval."""

import argparse
import asyncio
import atexit
import json
import readline
import sys
from pathlib import Path

from mcp.types import Tool

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


def _confirm_tool_call(tool: Tool | None, args: dict) -> bool:
    label = (tool.title or tool.name) if tool is not None else "Unknown tool"
    name = tool.name if tool is not None else "unknown"
    print(f"\nProposed Jira write: {label} ({name})", file=sys.stderr)
    print(json.dumps(args, ensure_ascii=False, indent=2), file=sys.stderr)
    try:
        answer = input("Approve? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in {"y", "yes"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-driven Jira agent")
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="run Jira write tools without asking for confirmation",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    config = load_config()
    _setup_readline()
    approver = (lambda tool, call_args: True) if args.yolo else _confirm_tool_call

    async with Agent(
        config,
        on_tool_call=_show_tool_call,
        approve_tool=approver,
    ) as agent:
        print(f"Jira agent ready. Model: {config.llm.llm_model}")
        if args.yolo:
            print("WARNING: --yolo enabled; Jira writes will not be confirmed.")
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
                reply = await agent.chat(user_input)
            except KeyboardInterrupt:
                print("\n(interrupted)", file=sys.stderr)
                continue
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                continue
            print(f"\n{reply}\n")


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
