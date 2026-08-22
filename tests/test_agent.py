from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import Tool, ToolAnnotations

from jira_agent.agent import Agent, MAX_ITERATIONS
from jira_agent.config import Config, JiraConfig, LLMConfig


def config() -> Config:
    return Config(
        llm=LLMConfig("llm-key", "test-model", "https://llm.example/v1"),
        jira=JiraConfig("https://jira.example", "user@example.com", "token"),
    )


def response(content: str | None = None, tool_name: str | None = None, arguments: str = "{}"):
    tool_calls = None
    if tool_name:
        tool_calls = [
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name=tool_name, arguments=arguments),
            )
        ]
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[tuple[list[dict], list[dict]]] = []

    async def chat(self, messages, tools=None):
        self.requests.append((list(messages), tools))
        return self.responses.pop(0)


class FakeTools:
    def __init__(self) -> None:
        self.search = Tool(
            name="search_issues",
            description="Search",
            inputSchema={"type": "object"},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        self.create = Tool(
            name="create_issue",
            description="Create",
            inputSchema={"type": "object"},
            annotations=ToolAnnotations(readOnlyHint=False),
        )
        self.tools = {tool.name: tool for tool in [self.search, self.create]}
        self.calls: list[tuple[str, dict]] = []
        self.openai_schemas = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.tools.values()
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def get_tool(self, name: str):
        return self.tools.get(name)

    def requires_approval(self, name: str) -> bool:
        tool = self.get_tool(name)
        return not (
            tool
            and tool.annotations
            and tool.annotations.read_only_hint is True
        )

    async def call(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"ok": True, "result": {"called": name}}


@pytest.mark.asyncio
async def test_read_tool_runs_without_approval_and_is_discovered() -> None:
    llm = FakeLLM(
        [
            response(tool_name="search_issues", arguments='{"jql":"project = TEST"}'),
            response(content="Found it."),
        ]
    )
    tools = FakeTools()
    approvals: list[str] = []
    agent = Agent(
        config(),
        llm=llm,
        tools=tools,
        approve_tool=lambda tool, args: approvals.append(tool.name) or True,
    )

    async with agent:
        reply = await agent.chat("Find issues")

    assert reply == "Found it."
    assert approvals == []
    assert tools.calls == [("search_issues", {"jql": "project = TEST"})]
    assert {schema["function"]["name"] for schema in llm.requests[0][1]} == {
        "search_issues",
        "create_issue",
    }


@pytest.mark.asyncio
async def test_declined_write_is_not_called_and_model_receives_error() -> None:
    llm = FakeLLM(
        [
            response(tool_name="create_issue", arguments='{"project_key":"TEST","summary":"New"}'),
            response(content="Cancelled."),
        ]
    )
    tools = FakeTools()
    observed: list[dict] = []
    agent = Agent(
        config(),
        llm=llm,
        tools=tools,
        approve_tool=lambda tool, args: False,
        on_tool_call=lambda name, args, result: observed.append(result),
    )

    async with agent:
        assert await agent.chat("Create one") == "Cancelled."

    assert tools.calls == []
    assert observed[0] == {
        "ok": False,
        "error": "User declined tool call: create_issue",
    }
    tool_message = llm.requests[1][0][-1]
    assert "User declined" in tool_message["content"]


@pytest.mark.asyncio
async def test_approved_write_runs() -> None:
    llm = FakeLLM(
        [
            response(tool_name="create_issue", arguments='{"project_key":"TEST","summary":"New"}'),
            response(content="Created."),
        ]
    )
    tools = FakeTools()
    agent = Agent(
        config(),
        llm=llm,
        tools=tools,
        approve_tool=lambda tool, args: True,
    )

    async with agent:
        assert await agent.chat("Create one") == "Created."

    assert tools.calls == [
        ("create_issue", {"project_key": "TEST", "summary": "New"})
    ]


@pytest.mark.asyncio
async def test_malformed_arguments_still_produce_tool_response() -> None:
    llm = FakeLLM(
        [response(tool_name="search_issues", arguments="{"), response(content="Bad JSON.")]
    )
    tools = FakeTools()
    agent = Agent(config(), llm=llm, tools=tools)

    async with agent:
        assert await agent.chat("Search") == "Bad JSON."

    assert tools.calls == []
    assert "Invalid JSON arguments" in llm.requests[1][0][-1]["content"]


@pytest.mark.asyncio
async def test_iteration_limit_stops_runaway_tool_loop() -> None:
    llm = FakeLLM(
        [response(tool_name="search_issues", arguments='{"jql":"x"}') for _ in range(MAX_ITERATIONS)]
    )
    tools = FakeTools()
    agent = Agent(config(), llm=llm, tools=tools)

    async with agent:
        reply = await agent.chat("Loop")

    assert reply == "(stopped: reached max tool-call iterations)"
    assert len(tools.calls) == MAX_ITERATIONS
