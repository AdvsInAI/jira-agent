"""Interactive Jira agent CLI with approvals and per-turn tracing."""

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
from .observability import tracer_from_env

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
    print(f"  -> {name}({json.dumps(args, ensure_ascii=False)})", file=sys.stderr)
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
        print("Approve? [y/N] ", end="", file=sys.stderr, flush=True)
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in {"y", "yes"}


def _tracing_state_line(tracer) -> str:
    return f"tracing: on -> {tracer.path}" if tracer.enabled else "tracing: off"


def _handle_trace_command(tracer, sub: str) -> None:
    """Implement the /trace slash command family.

    /trace          → toggle on/off and print the new state (with old state
                      hinted so the user knows what just happened)
    /trace status   → print current state, path, and lifetime event count
    """
    if not sub:
        was_on = tracer.enabled
        if tracer.toggle():
            print(f"tracing: on -> {tracer.path} (was off)", file=sys.stderr)
        else:
            assert was_on
            print("tracing: off (was on)", file=sys.stderr)
    elif sub == "status":
        state = "on" if tracer.enabled else "off"
        print(
            f"tracing: {state} -> {tracer.path}  "
            f"({tracer.event_count} events this session)",
            file=sys.stderr,
        )
    else:
        print(f"unknown /trace subcommand: {sub!r}", file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-driven Jira agent")
    parser.add_argument(
        "--yolo", action="store_true",
        help="run Jira write tools without asking for confirmation",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    config = load_config()
    _setup_readline()
    tracer = tracer_from_env()
    approver = (lambda tool, call_args: True) if args.yolo else _confirm_tool_call

    async with Agent(
        config, on_tool_call=_show_tool_call, approve_tool=approver, tracer=tracer
    ) as agent:
        print(f"Jira agent ready. Model: {config.llm.llm_model}")
        print(_tracing_state_line(tracer))
        if args.yolo:
            print("WARNING: --yolo enabled; Jira writes will not be confirmed.")
        print("Type a request. Ctrl+D or /exit to quit.\n")

        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input in {"/exit", "/quit"}:
                break
            if user_input.startswith("/"):
                head, _, tail = user_input.partition(" ")
                if head == "/trace":
                    _handle_trace_command(tracer, tail.strip())
                else:
                    print(f"unknown command: {head}", file=sys.stderr)
                continue
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
