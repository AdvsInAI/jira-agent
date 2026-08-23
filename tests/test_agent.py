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
        return self.responses.pop(0), {
            "model": "test-model",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1.0,
        }


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


class FakeTracer:
    def __init__(self) -> None:
        self.started = 0
        self.ended = 0
        self.llm_calls: list[dict] = []
        self.tool_calls: list[dict] = []

    def start_turn(self) -> None:
        self.started += 1

    def end_turn(self) -> None:
        self.ended += 1

    def record_llm_call(self, **event) -> None:
        self.llm_calls.append(event)

    def record_tool_call(self, **event) -> None:
        self.tool_calls.append(event)


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
async def test_async_mcp_calls_are_traced() -> None:
    llm = FakeLLM([
        response(tool_name="search_issues", arguments='{"jql":"project = TEST"}'),
        response(content="Found it."),
    ])
    tracer = FakeTracer()
    agent = Agent(config(), llm=llm, tools=FakeTools(), tracer=tracer)

    async with agent:
        assert await agent.chat("Find issues") == "Found it."

    assert tracer.started == 1
    assert tracer.ended == 1
    assert len(tracer.llm_calls) == 2
    assert tracer.tool_calls[0]["name"] == "search_issues"
    assert tracer.tool_calls[0]["args"] == {"jql": "project = TEST"}
    assert tracer.tool_calls[0]["ok"] is True


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
        "error_type": "ApprovalDeclined",
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
async def test_unknown_tool_is_rejected_without_prompting_or_dispatch() -> None:
    llm = FakeLLM([
        response(tool_name="delete_everything"),
        response(content="That tool is unavailable."),
    ])
    tools = FakeTools()
    approvals: list[str] = []
    agent = Agent(
        config(),
        llm=llm,
        tools=tools,
        approve_tool=lambda tool, args: approvals.append(tool.name) or True,
    )

    async with agent:
        assert await agent.chat("Delete everything") == "That tool is unavailable."

    assert approvals == []
    assert tools.calls == []
    assert "Unknown tool: delete_everything" in llm.requests[1][0][-1]["content"]


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
    assert agent._messages[-1] == {
        "role": "assistant",
        "content": "(stopped: reached max tool-call iterations)",
    }
    assistant_calls = [
        message for message in agent._messages
        if message["role"] == "assistant" and message.get("tool_calls")
    ]
    tool_responses = [
        message for message in agent._messages if message["role"] == "tool"
    ]
    assert len(assistant_calls) == len(tool_responses) == MAX_ITERATIONS
