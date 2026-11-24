"""MCP 客户端：连接 stdio / SSE / Streamable HTTP Server 并调用工具。"""

from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from app.core.config import settings
from app.domains.skills.mcp.models import MCPServer


class MCPError(Exception):
    """MCP 连接或调用失败。"""


def ensure_command_allowed(command: str) -> None:
    allowed = settings.mcp_allowed_command_list
    if not allowed:
        return
    name = Path(command).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in allowed:
        raise MCPError(f"命令不在白名单内: {name}（允许: {', '.join(allowed)}）")


@asynccontextmanager
async def _transport(server: MCPServer):
    if server.transport == "stdio":
        if not server.command:
            raise MCPError("stdio 传输缺少 command")
        ensure_command_allowed(server.command)
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args or []),
            env=dict(server.env) if server.env else None,
            cwd=server.cwd,
        )
        async with stdio_client(params) as streams:
            yield streams
    elif server.transport == "sse":
        if not server.url:
            raise MCPError("sse 传输缺少 url")
        async with sse_client(server.url, headers=server.headers or None) as streams:
            yield streams
    elif server.transport in {"streamable_http", "http"}:
        if not server.url:
            raise MCPError("streamable_http 传输缺少 url")
        http_client = create_mcp_http_client(headers=server.headers or None)
        async with http_client:
            async with streamable_http_client(server.url, http_client=http_client) as streams:
                yield streams
    else:
        raise MCPError(f"不支持的传输方式: {server.transport}")


@asynccontextmanager
async def open_mcp_session(server: MCPServer):
    if server.status != "active":
        raise MCPError("MCP Server 已停用")
    try:
        async with _transport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=30) as session:
                await session.initialize()
                yield session
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"MCP 连接失败: {exc}") from exc


def _tool_to_dict(tool) -> dict:
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "input_schema": schema,
    }


def _content_to_dict(item) -> dict:
    if hasattr(item, "model_dump"):
        try:
            return item.model_dump(mode="json")
        except TypeError:
            return item.model_dump()
    if isinstance(item, dict):
        return item
    return {"text": str(item)}


async def list_remote_tools(server: MCPServer) -> list[dict]:
    async with open_mcp_session(server) as session:
        result = await session.list_tools()
    return [_tool_to_dict(tool) for tool in (getattr(result, "tools", None) or [])]


async def call_remote_tool(server: MCPServer, tool_name: str, arguments: dict) -> dict:
    async with open_mcp_session(server) as session:
        result = await session.call_tool(
            tool_name,
            arguments,
            read_timeout_seconds=60,
        )

    content = [_content_to_dict(item) for item in (getattr(result, "content", None) or [])]
    if getattr(result, "is_error", False):
        texts = [item.get("text") for item in content if isinstance(item.get("text"), str)]
        raise MCPError("MCP 工具执行失败: " + ("; ".join(texts) or "未知错误"))

    structured = getattr(result, "structured_content", None)
    if hasattr(structured, "model_dump"):
        structured = structured.model_dump(mode="json")

    return {"content": content, "structured_content": structured}
