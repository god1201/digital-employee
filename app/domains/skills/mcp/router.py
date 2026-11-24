from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.mcp.client import MCPError
from app.domains.skills.mcp.models import MCPServer
from app.domains.skills.mcp.schemas import (
    MCPServerCreate,
    MCPServerOut,
    MCPServerUpdate,
    MCPSyncResult,
)
from app.domains.skills.mcp.service import sync_server_tools, validate_server_config
from app.domains.skills.tools.models import Tool
from app.domains.skills.tools.schemas import ToolOut

router = APIRouter(prefix="/mcp-servers", tags=["MCP 管理"])


async def _get_server(db: DbSession, tenant_id: int, server_id: int) -> MCPServer:
    server = await db.scalar(
        select(MCPServer).where(
            MCPServer.id == server_id,
            MCPServer.tenant_id == tenant_id,
        )
    )
    if server is None:
        raise NotFoundError("MCP Server 不存在")
    return server


@router.get("", summary="MCP Server 列表")
async def list_servers(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    transport: str | None = None,
    status: str | None = None,
):
    conditions = [MCPServer.tenant_id == current_user.tenant_id]
    if keyword:
        conditions.append(
            or_(MCPServer.name.ilike(f"%{keyword}%"), MCPServer.code.ilike(f"%{keyword}%"))
        )
    if transport:
        conditions.append(MCPServer.transport == transport)
    if status:
        conditions.append(MCPServer.status == status)

    stmt = select(MCPServer).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(MCPServer.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [MCPServerOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="注册 MCP Server")
async def create_server(
    payload: MCPServerCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    try:
        validate_server_config(payload.transport, payload.command, payload.url)
    except MCPError as exc:
        raise BadRequestError(str(exc)) from exc

    exists = await db.scalar(
        select(MCPServer.id).where(
            MCPServer.tenant_id == current_user.tenant_id,
            MCPServer.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("MCP Server 编码已存在")

    server = MCPServer(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(server)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="mcp_server.create",
        resource_type="mcp_server",
        resource_id=server.id,
        detail={"code": server.code, "transport": server.transport},
        ip_address=client_ip(request),
    )
    return success(MCPServerOut.model_validate(server).model_dump(mode="json"))


@router.get("/{server_id}", summary="MCP Server 详情")
async def get_server(
    server_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    server = await _get_server(db, current_user.tenant_id, server_id)
    return success(MCPServerOut.model_validate(server).model_dump(mode="json"))


@router.patch("/{server_id}", summary="更新 MCP Server")
async def update_server(
    server_id: int,
    payload: MCPServerUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    server = await _get_server(db, current_user.tenant_id, server_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(server, field, value)

    try:
        validate_server_config(server.transport, server.command, server.url)
    except MCPError as exc:
        # 抛出后由 get_db 回滚本次修改
        raise BadRequestError(str(exc)) from exc

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="mcp_server.update",
        resource_type="mcp_server",
        resource_id=server.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(MCPServerOut.model_validate(server).model_dump(mode="json"))


@router.delete("/{server_id}", summary="停用 MCP Server 及其工具")
async def disable_server(
    server_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    server = await _get_server(db, current_user.tenant_id, server_id)
    server.status = "disabled"
    tools = list(
        (
            await db.scalars(
                select(Tool).where(
                    Tool.tenant_id == current_user.tenant_id,
                    Tool.mcp_server == server.code,
                )
            )
        ).all()
    )
    for tool in tools:
        tool.enabled = False

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="mcp_server.disable",
        resource_type="mcp_server",
        resource_id=server.id,
        detail={"disabled_tools": len(tools)},
        ip_address=client_ip(request),
    )
    return success(None, "MCP Server 已停用")


@router.post("/{server_id}/sync", summary="连接并同步 MCP 工具")
async def sync_server(
    server_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    server = await _get_server(db, current_user.tenant_id, server_id)
    if server.status != "active":
        raise BadRequestError("MCP Server 已停用")

    try:
        result = await sync_server_tools(
            db,
            server,
            current_user.tenant_id,
            current_user.id,
        )
    except MCPError as exc:
        server.last_error = str(exc)
        await db.flush()
        await db.commit()
        raise BadRequestError(str(exc)) from exc

    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="mcp_server.sync",
        resource_type="mcp_server",
        resource_id=server.id,
        detail={
            "tool_count": result["tool_count"],
            "created": result["created"],
            "updated": result["updated"],
        },
        ip_address=client_ip(request),
    )
    return success(MCPSyncResult(**result).model_dump(mode="json"))


@router.get("/{server_id}/tools", summary="MCP Server 已同步的工具")
async def list_server_tools(
    server_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    server = await _get_server(db, current_user.tenant_id, server_id)
    conditions = [
        Tool.tenant_id == current_user.tenant_id,
        Tool.mcp_server == server.code,
    ]
    stmt = select(Tool).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(stmt.order_by(Tool.id).offset((page - 1) * page_size).limit(page_size))
        ).all()
    )
    return paged(
        [ToolOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )
