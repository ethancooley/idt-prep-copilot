"""How the agent reaches the chart: always through the MCP tools.

`MCPChartClient` launches the MCP server as a subprocess and talks to it over stdio, exactly as Claude
Desktop does. `InProcessChartClient` calls the same server object directly, which keeps tests fast.
Both return the same tool definitions and the same JSON, so the agent cannot tell them apart.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Protocol

# The agent never needs to browse other participants.
HIDDEN_TOOLS = {"list_participants"}


class ChartClient(Protocol):
    async def tools(self) -> list[dict]: ...
    async def call(self, name: str, arguments: dict) -> Any: ...


def _to_anthropic(tool: Any) -> dict:
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


def _parse(result: Any) -> Any:
    texts = [getattr(c, "text", "") for c in result.content]
    if result.is_error:
        return {"error": "".join(texts)}
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]  # list results are wrapped as {"result": [...]}
    if structured:
        return structured
    try:
        return json.loads("".join(texts)) if len(texts) == 1 else [json.loads(t) for t in texts]
    except json.JSONDecodeError:
        return "".join(texts)


class InProcessChartClient:
    def __init__(self):
        from idt_copilot.chart import server
        self._server = server.server

    async def tools(self) -> list[dict]:
        return [_to_anthropic(t) for t in await self._server.list_tools() if t.name not in HIDDEN_TOOLS]

    async def call(self, name: str, arguments: dict) -> Any:
        try:
            result = await self._server.call_tool(name, arguments)
        except Exception as e:  # ToolError: hand the message back to the model, as MCP would
            return {"error": str(e)}
        return _parse(result)


class MCPChartClient:
    """Use as `async with MCPChartClient() as chart: ...`."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        self._stack = AsyncExitStack()
        self._session = None

    async def __aenter__(self) -> "MCPChartClient":
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = dict(os.environ)
        if self.database_url:
            env["DATABASE_URL"] = self.database_url
        params = StdioServerParameters(command=sys.executable, args=["-m", "idt_copilot.chart.server"], env=env)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def tools(self) -> list[dict]:
        listed = await self._session.list_tools()
        return [_to_anthropic(t) for t in listed.tools if t.name not in HIDDEN_TOOLS]

    async def call(self, name: str, arguments: dict) -> Any:
        return _parse(await self._session.call_tool(name, arguments))
