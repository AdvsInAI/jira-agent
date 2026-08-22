"""Client-side adapter from MCP tools to OpenAI-compatible tool calls."""

import sys
from typing import Any

from mcp import Client, StdioServerParameters, stdio_client
from mcp.types import TextContent, Tool

from .config import JiraConfig


class MCPToolClient:
    def __init__(self, server: Any, *, mode="auto") -> None:
        self._client = Client(server, mode=mode)
        self._tools: dict[str, Tool] = {}

    @classmethod
    def for_jira(cls, config: JiraConfig) -> "MCPToolClient":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "jira_agent.mcp_server"],
            env={
                "JIRA_BASE_URL": config.jira_base_url,
                "JIRA_EMAIL": config.jira_email,
                "JIRA_API_TOKEN": config.jira_api_token,
            },
        )
        return cls(stdio_client(params))

    async def __aenter__(self) -> "MCPToolClient":
        await self._client.__aenter__()
        try:
            listed = await self._client.list_tools()
            self._tools = {tool.name: tool for tool in listed.tools}
            if not self._tools:
                raise RuntimeError("MCP server advertised no tools")
        except BaseException as exc:
            await self._client.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.__aexit__(exc_type, exc, tb)
        self._tools.clear()

    @property
    def openai_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def requires_approval(self, name: str) -> bool:
        tool = self.get_tool(name)
        return not (
            tool is not None
            and tool.annotations is not None
            and tool.annotations.read_only_hint is True
        )

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        if result.is_error:
            message = _text_content(result.content) or "MCP tool call failed"
            return {"ok": False, "error": message}

        payload: Any = result.structured_content
        if payload is None:
            payload = _text_content(result.content)
        return {"ok": True, "result": payload}


def _text_content(content: list[Any]) -> str:
    return "\n".join(
        block.text for block in content if isinstance(block, TextContent)
    )
