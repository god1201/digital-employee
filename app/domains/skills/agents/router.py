from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.agents.models import Agent
from app.domains.skills.agents.runner import AgentError, invoke_agent
from app.domains.skills.agents.schemas import (
    AgentCreate,
    AgentInvokeRequest,
    AgentInvokeResult,
    AgentOut,
    AgentUpdate,
)
from app.domains.skills.tools.models import Tool
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.service import (
    ensure_employee_exists,
    serialize_employee,
)

router = APIRouter(prefix="/agents", tags=["Agent 管理"])


async def _get_agent(db: DbSession, tenant_id: int, agent_id: int) -> Agent:
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if agent is None:
        raise NotFoundError("Agent 不存在")
    return agent


def _validate_agent_config(agent_type: str, protocol: str, endpoint_url: str | None) -> None:
    if agent_type == "internal":
        if protocol != "builtin":
            raise BadRequestError("internal Agent 的 protocol 必须是 builtin")
        return
    if protocol not in {"openai", "http"}:
        raise BadRequestError("第三方 Agent 的 protocol 必须是 openai 或 http")
    if not endpoint_url:
        raise BadRequestError("第三方 Agent 必须提供 endpoint_url")


async def _usage_map(
    db: DbSession, tenant_id: int, agent_ids: list[int]
) -> dict[int, dict]:
    """统计每个 Agent 被哪些数字员工使用。"""
    if not agent_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DigitalEmployee.agent_id,
                DigitalEmployee.name,
                DigitalEmployee.status,
            ).where(
                DigitalEmployee.tenant_id == tenant_id,
                DigitalEmployee.agent_id.in_(agent_ids),
            )
        )
    ).all()
    usage: dict[int, dict] = {}
    for agent_id, name, status in rows:
        bucket = usage.setdefault(
            agent_id, {"count": 0, "active_count": 0, "names": []}
        )
        bucket["count"] += 1
        if status == "active":
            bucket["active_count"] += 1
        bucket["names"].append(name)
    return usage


async def _validate_tools(db: DbSession, tenant_id: int, tool_codes: list[str]) -> None:
    if not tool_codes:
        return
    found = set(
        (
            await db.scalars(
                select(Tool.code).where(
                    Tool.tenant_id == tenant_id,
                    Tool.code.in_(tool_codes),
                )
            )
        ).all()
    )
    missing = [code for code in tool_codes if code not in found]
    if missing:
        raise BadRequestError(f"工具不存在: {', '.join(missing)}")


@router.get("", summary="Agent 列表")
async def list_agents(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    agent_type: str | None = None,
    protocol: str | None = None,
    status: str | None = None,
):
    conditions = [Agent.tenant_id == current_user.tenant_id]
    if keyword:
        conditions.append(or_(Agent.name.ilike(f"%{keyword}%"), Agent.code.ilike(f"%{keyword}%")))
    if agent_type:
        conditions.append(Agent.agent_type == agent_type)
    if protocol:
        conditions.append(Agent.protocol == protocol)
    if status:
        conditions.append(Agent.status == status)

    stmt = select(Agent).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(Agent.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    usage = await _usage_map(db, current_user.tenant_id, [item.id for item in items])
    data = []
    for item in items:
        payload = AgentOut.model_validate(item).model_dump(mode="json")
        info = usage.get(item.id)
        payload["employee_count"] = info["count"] if info else 0
        payload["active_employee_count"] = info["active_count"] if info else 0
        payload["employee_names"] = (info["names"][:5] if info else [])
        data.append(payload)
    return paged(data, total, page, page_size)


@router.post("", summary="注册 Agent")
async def create_agent(
    payload: AgentCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    _validate_agent_config(payload.agent_type, payload.protocol, payload.endpoint_url)
    await _validate_tools(db, current_user.tenant_id, payload.tools)

    exists = await db.scalar(
        select(Agent.id).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("Agent 编码已存在")

    agent = Agent(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(agent)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent.create",
        resource_type="agent",
        resource_id=agent.id,
        detail={"code": agent.code, "type": agent.agent_type, "protocol": agent.protocol},
        ip_address=client_ip(request),
    )
    return success(AgentOut.model_validate(agent).model_dump(mode="json"))


@router.get("/{agent_id}", summary="Agent 详情")
async def get_agent(
    agent_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    agent = await _get_agent(db, current_user.tenant_id, agent_id)
    return success(AgentOut.model_validate(agent).model_dump(mode="json"))


@router.get("/{agent_id}/employees", summary="Agent 使用方（数字员工）")
async def list_agent_employees(
    agent_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
):
    agent = await _get_agent(db, current_user.tenant_id, agent_id)
    conditions = [
        DigitalEmployee.tenant_id == current_user.tenant_id,
        DigitalEmployee.agent_id == agent.id,
    ]
    if status:
        conditions.append(DigitalEmployee.status == status)

    stmt = select(DigitalEmployee).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(DigitalEmployee.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [serialize_employee(item, agent) for item in items],
        total,
        page,
        page_size,
    )


@router.patch("/{agent_id}", summary="更新 Agent")
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    agent = await _get_agent(db, current_user.tenant_id, agent_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(agent, field, value)

    _validate_agent_config(agent.agent_type, agent.protocol, agent.endpoint_url)
    if "tools" in changes:
        await _validate_tools(db, current_user.tenant_id, agent.tools or [])

    agent.version += 1
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent.update",
        resource_type="agent",
        resource_id=agent.id,
        detail={"fields": sorted(changes.keys()), "version": agent.version},
        ip_address=client_ip(request),
    )
    return success(AgentOut.model_validate(agent).model_dump(mode="json"))


@router.delete("/{agent_id}", summary="停用 Agent")
async def disable_agent(
    agent_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    agent = await _get_agent(db, current_user.tenant_id, agent_id)
    agent.status = "disabled"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent.disable",
        resource_type="agent",
        resource_id=agent.id,
        ip_address=client_ip(request),
    )
    return success(None, "Agent 已停用")


@router.post("/{agent_id}/invoke", summary="调用 Agent（调试）")
async def invoke_agent_endpoint(
    agent_id: int,
    payload: AgentInvokeRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    agent = await _get_agent(db, current_user.tenant_id, agent_id)
    if payload.employee_id is not None:
        await ensure_employee_exists(db, current_user.tenant_id, payload.employee_id)

    try:
        result = await invoke_agent(
            db,
            agent,
            tenant_id=current_user.tenant_id,
            employee_id=payload.employee_id or 0,
            input_data=payload.input,
            prompt=payload.prompt,
        )
    except AgentError as exc:
        raise BadRequestError(str(exc)) from exc

    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="agent.invoke",
        resource_type="agent",
        resource_id=agent.id,
        detail={
            "tokens": result.tokens,
            "tool_calls": len(result.tool_calls),
            "latency_ms": result.latency_ms,
        },
        ip_address=client_ip(request),
    )
    response = AgentInvokeResult(
        agent_id=agent.id,
        agent_code=agent.code,
        output=result.output,
        tokens=result.tokens,
        latency_ms=result.latency_ms,
        tool_calls=result.tool_calls,
    )
    return success(response.model_dump(mode="json"))
