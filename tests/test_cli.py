import builtins

from mcp.types import Tool

from jira_agent.cli import _confirm_tool_call


def test_confirmation_defaults_to_no(monkeypatch) -> None:
    tool = Tool(name="create_issue", title="Create", inputSchema={"type": "object"})
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert _confirm_tool_call(tool, {"summary": "Example"}) is False


def test_confirmation_accepts_yes(monkeypatch) -> None:
    tool = Tool(name="create_issue", title="Create", inputSchema={"type": "object"})
    monkeypatch.setattr(builtins, "input", lambda prompt: "YES")
    assert _confirm_tool_call(tool, {"summary": "Example"}) is True


def test_confirmation_interrupt_declines(monkeypatch) -> None:
    tool = Tool(name="create_issue", title="Create", inputSchema={"type": "object"})

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    assert _confirm_tool_call(tool, {}) is False
