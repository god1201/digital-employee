from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.tools.models import Tool
from app.domains.skills.tools.schemas import ToolCreate, ToolOut, ToolUpdate

router = APIRouter(prefix="/tools", tags=["工具管理"])


async def _get_tool(db: DbSession, tenant_id: int, tool_id: int) -> Tool:
    tool = await db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
    if tool is None:
        raise NotFoundError("工具不存在")
    return tool


@router.get("", summary="工具列表")
async def list_tools(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    tool_type: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
):
    conditions = [Tool.tenant_id == current_user.tenant_id]
    if tool_type:
        conditions.append(Tool.tool_type == tool_type)
    if enabled is not None:
        conditions.append(Tool.enabled.is_(enabled))
    if keyword:
        conditions.append(or_(Tool.name.ilike(f"%{keyword}%"), Tool.code.ilike(f"%{keyword}%")))

    stmt = select(Tool).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(Tool.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [ToolOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建工具")
async def create_tool(
    payload: ToolCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    exists = await db.scalar(
        select(Tool.id).where(
            Tool.tenant_id == current_user.tenant_id,
            Tool.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("工具编码已存在")

    tool = Tool(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(tool)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="tool.create",
        resource_type="tool",
        resource_id=tool.id,
        detail={"code": tool.code, "type": tool.tool_type, "risk": tool.risk_level},
        ip_address=client_ip(request),
    )
    return success(ToolOut.model_validate(tool).model_dump(mode="json"))


@router.get("/{tool_id}", summary="工具详情")
async def get_tool(
    tool_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    tool = await _get_tool(db, current_user.tenant_id, tool_id)
    return success(ToolOut.model_validate(tool).model_dump(mode="json"))


@router.patch("/{tool_id}", summary="更新工具")
async def update_tool(
    tool_id: int,
    payload: ToolUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    tool = await _get_tool(db, current_user.tenant_id, tool_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(tool, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="tool.update",
        resource_type="tool",
        resource_id=tool.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(ToolOut.model_validate(tool).model_dump(mode="json"))


@router.delete("/{tool_id}", summary="删除工具")
async def delete_tool(
    tool_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    tool = await _get_tool(db, current_user.tenant_id, tool_id)
    await db.delete(tool)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="tool.delete",
        resource_type="tool",
        resource_id=tool_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")
