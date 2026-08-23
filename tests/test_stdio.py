from types import SimpleNamespace

import pytest

import jira_agent.mcp_client as mcp_client_module
from jira_agent.config import JiraConfig
from jira_agent.mcp_client import MCPToolClient


class FailingClient:
    async def call_tool(self, name, arguments):
        raise ConnectionError("transport closed")


class EmptyResultClient:
    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            is_error=False, structured_content=None, content=[]
        )


@pytest.mark.asyncio
async def test_packaged_stdio_server_discovers_tools_without_network() -> None:
    adapter = MCPToolClient.for_jira(
        JiraConfig(
            "https://example.atlassian.net",
            "user@example.com",
            "dummy-token",
        )
    )

    async with adapter:
        names = [schema["function"]["name"] for schema in adapter.openai_schemas]

    assert names == [
        "create_issue",
        "search_issues",
        "transition_issue",
        "add_comment",
        "assign_issue",
    ]


@pytest.mark.asyncio
async def test_transport_failure_becomes_tool_error_envelope() -> None:
    adapter = object.__new__(MCPToolClient)
    adapter._client = FailingClient()

    result = await adapter.call("search_issues", {"jql": "project = TEST"})

    assert result == {
        "ok": False,
        "error": "ConnectionError: transport closed",
        "error_type": "ConnectionError",
    }


@pytest.mark.asyncio
async def test_empty_successful_tool_result_is_none() -> None:
    adapter = object.__new__(MCPToolClient)
    adapter._client = EmptyResultClient()
    assert await adapter.call("empty", {}) == {"ok": True, "result": None}


def test_jira_subprocess_forwards_network_environment(monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.example")
    monkeypatch.setenv("SSL_CERT_FILE", "/certs/company.pem")
    monkeypatch.setattr(
        mcp_client_module,
        "stdio_client",
        lambda params: captured.setdefault("params", params),
    )
    monkeypatch.setattr(
        mcp_client_module,
        "Client",
        lambda server, mode: SimpleNamespace(),
    )

    MCPToolClient.for_jira(
        JiraConfig("https://jira.example", "user@example.com", "token")
    )

    environment = captured["params"].env
    assert environment["HTTPS_PROXY"] == "https://proxy.example"
    assert environment["SSL_CERT_FILE"] == "/certs/company.pem"
    assert environment["JIRA_API_TOKEN"] == "token"
