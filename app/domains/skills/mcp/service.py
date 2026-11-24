from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.utils import slugify
from app.domains.skills.mcp.client import (
    MCPError,
    ensure_command_allowed,
    list_remote_tools,
)
from app.domains.skills.mcp.models import MCPServer
from app.domains.skills.tools.models import Tool


def validate_server_config(transport: str, command: str | None, url: str | None) -> None:
    if transport == "stdio":
        if not command:
            raise MCPError("stdio 传输必须提供 command")
        ensure_command_allowed(command)
    elif transport in {"sse", "streamable_http"}:
        if not url:
            raise MCPError(f"{transport} 传输必须提供 url")
    else:
        raise MCPError(f"不支持的传输方式: {transport}")


async def sync_server_tools(
    db: AsyncSession,
    server: MCPServer,
    tenant_id: int,
    user_id: int | None,
) -> dict:
    """拉取远端工具列表并同步到本地 tools 表（按 server + slug 生成稳定编码）。"""
    remote_tools = await list_remote_tools(server)

    created = 0
    updated = 0
    for item in remote_tools:
        remote_name = str(item["name"])
        code = f"mcp_{server.id}_{slugify(remote_name)}"[:64]
        tool = await db.scalar(select(Tool).where(Tool.tenant_id == tenant_id, Tool.code == code))
        if tool is None:
            tool = Tool(
                tenant_id=tenant_id,
                code=code,
                created_by=user_id,
            )
            db.add(tool)
            created += 1
        else:
            updated += 1

        tool.name = remote_name[:128]
        tool.tool_type = "mcp"
        tool.description = str(item.get("description") or "")
        tool.parameters_schema = item.get("input_schema") or {}
        tool.config = {"mcp_server_id": server.id, "mcp_tool": remote_name}
        tool.mcp_server = server.code
        tool.source = "mcp"
        await db.flush()

    server.tool_count = len(remote_tools)
    server.last_connected_at = utcnow()
    server.last_error = None
    await db.flush()

    return {
        "server_id": server.id,
        "tool_count": len(remote_tools),
        "created": created,
        "updated": updated,
        "tools": remote_tools,
    }
