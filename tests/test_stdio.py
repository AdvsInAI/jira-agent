import pytest

from jira_agent.config import JiraConfig
from jira_agent.mcp_client import MCPToolClient


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
