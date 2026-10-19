"""MCP tools as LangChain tools, on the MCP Python SDK 2.x.

(langchain-mcp-adapters still pins mcp<2.0, so the agent carries this adapter instead.) Servers are
stateless streamable HTTP, so each tool call opens its own short session: nothing to keep alive,
and every call carries the agent's token and the skill header for the server and OPA to check."""
import json
from contextlib import asynccontextmanager

from langchain_core.tools import StructuredTool, ToolException
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


@asynccontextmanager
async def session(url: str, headers: dict):
    async with streamable_http_client(url, http_client=create_mcp_http_client(headers=headers)) as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            yield s


def _result_text(res) -> str:
    data = res.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if data is not None:
        return json.dumps(data, default=str)
    return "".join(getattr(c, "text", "") for c in res.content)


async def load_tools(server: str, url: str, headers: dict, allowed: set[str]) -> list[StructuredTool]:
    """The server's tools that are in `allowed`, as LangChain tools named like the MCP tools."""
    async with session(url, headers) as s:
        listed = (await s.list_tools()).tools

    def make(t):
        async def call(**kwargs):
            async with session(url, headers) as s2:
                res = await s2.call_tool(t.name, kwargs)
            text = _result_text(res)
            if res.is_error:
                raise ToolException(text)  # handled: the model sees the error text and the skill's error table applies
            return text
        return StructuredTool(name=t.name, description=t.description or "", args_schema=t.input_schema,
                              coroutine=call, handle_tool_error=True, metadata={"server": server})

    return [make(t) for t in listed if t.name in allowed]
