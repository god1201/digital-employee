from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, or_, select

from app.core.base import utcnow
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.knowledge.models import KnowledgeBase
from app.domains.workforce.employees.analytics import (
    token_usage,
    token_usage_csv,
    workbench,
)
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.schemas import (
    EmployeeCreate,
    EmployeeKnowledgeBasesUpdate,
    EmployeeUpdate,
)
from app.domains.workforce.employees.service import (
    bound_knowledge_base_ids,
    employee_agent_map,
    get_agent,
    get_employee,
    require_agent,
    serialize_employee,
)
from app.domains.workforce.projects.service import employee_projects

router = APIRouter(prefix="/digital-employees", tags=["数字员工"])


@router.get("", summary="数字员工列表")
async def list_employees(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    status: str | None = None,
):
    conditions = [DigitalEmployee.tenant_id == current_user.tenant_id]
    if keyword:
        conditions.append(
            or_(
                DigitalEmployee.name.ilike(f"%{keyword}%"),
                DigitalEmployee.code.ilike(f"%{keyword}%"),
            )
        )
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
    agents = await employee_agent_map(db, items)
    return paged(
        [
            serialize_employee(item, agents.get(item.agent_id or 0))
            for item in items
        ],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建数字员工")
async def create_employee(
    payload: EmployeeCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    exists = await db.scalar(
        select(DigitalEmployee.id).where(
            DigitalEmployee.tenant_id == current_user.tenant_id,
            DigitalEmployee.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("员工编码已存在")

    values = payload.model_dump()
    agent = None
    if values.get("agent_id"):
        agent = await require_agent(
            db, current_user.tenant_id, int(values["agent_id"])
        )
        if not values.get("model_name"):
            values["model_name"] = agent.model_name

    employee = DigitalEmployee(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **values,
    )
    db.add(employee)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="employee.create",
        resource_type="digital_employee",
        resource_id=employee.id,
        detail={
            "name": employee.name,
            "code": employee.code,
            "status": employee.status,
            "agent_id": employee.agent_id,
        },
        ip_address=client_ip(request),
    )
    return success(serialize_employee(employee, agent))


@router.get("/{employee_id}", summary="数字员工详情")
async def get_employee_detail(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    agent = await get_agent(db, current_user.tenant_id, employee.agent_id)
    return success(serialize_employee(employee, agent))


@router.get("/{employee_id}/workbench", summary="员工工作台")
async def employee_workbench(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(await workbench(db, employee))


@router.get("/{employee_id}/token-usage", summary="员工 Token 明细")
async def employee_token_usage(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(30, ge=1, le=90),
    source: str | None = Query(None),
    project_id: int | None = Query(None),
    tool_code: str | None = Query(None),
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(
        await token_usage(
            db,
            employee,
            days=days,
            source=source,
            project_id=project_id,
            tool_code=tool_code,
        )
    )


@router.get("/{employee_id}/token-usage/export", summary="导出员工 Token 明细 CSV")
async def employee_token_usage_export(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(30, ge=1, le=90),
    source: str | None = Query(None),
    project_id: int | None = Query(None),
    tool_code: str | None = Query(None),
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    content = await token_usage_csv(
        db,
        employee,
        days=days,
        source=source,
        project_id=project_id,
        tool_code=tool_code,
    )
    filename = f"token-usage-{employee.code}-{utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{employee_id}/projects", summary="员工参与的项目"
)
async def employee_project_list(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(
        await employee_projects(db, current_user.tenant_id, employee.id)
    )


@router.get(
    "/{employee_id}/knowledge-bases",
    summary="员工知识库绑定",
)
async def list_employee_knowledge_bases(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    bound_ids = bound_knowledge_base_ids(employee)
    bound_set = set(bound_ids)
    bases = list(
        (
            await db.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.tenant_id == current_user.tenant_id)
                .order_by(KnowledgeBase.id)
            )
        ).all()
    )
    return success(
        {
            "employee_id": employee.id,
            "bound_ids": bound_ids,
            "restricted": bool(bound_ids),
            "items": [
                {
                    "id": base.id,
                    "name": base.name,
                    "code": base.code,
                    "status": base.status,
                    "bound": base.id in bound_set,
                }
                for base in bases
            ],
        }
    )


@router.put(
    "/{employee_id}/knowledge-bases",
    summary="设置员工知识库绑定（空列表表示不限制）",
)
async def update_employee_knowledge_bases(
    employee_id: int,
    payload: EmployeeKnowledgeBasesUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    requested: list[int] = []
    for item in payload.knowledge_base_ids:
        value = int(item)
        if value > 0 and value not in requested:
            requested.append(value)
    if requested:
        rows = list(
            (
                await db.scalars(
                    select(KnowledgeBase).where(
                        KnowledgeBase.tenant_id == current_user.tenant_id,
                        KnowledgeBase.id.in_(requested),
                        KnowledgeBase.status == "active",
                    )
                )
            ).all()
        )
        found = {base.id for base in rows}
        missing = [item for item in requested if item not in found]
        if missing:
            raise BadRequestError(
                "知识库不存在或未启用: " + ", ".join(str(item) for item in missing)
            )
    config = dict(employee.config or {})
    config["knowledge_base_ids"] = sorted(requested)
    employee.config = config
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="employee.knowledge_bases",
        resource_type="digital_employee",
        resource_id=employee.id,
        detail={"knowledge_base_ids": sorted(requested)},
        ip_address=client_ip(request),
    )
    return success(
        {
            "employee_id": employee.id,
            "bound_ids": sorted(requested),
            "restricted": bool(requested),
        }
    )


@router.patch("/{employee_id}", summary="更新数字员工")
async def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("agent_id") is not None:
        await require_agent(
            db, current_user.tenant_id, int(changes["agent_id"])
        )
    for field, value in changes.items():
        setattr(employee, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="employee.update",
        resource_type="digital_employee",
        resource_id=employee.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    agent = await get_agent(db, current_user.tenant_id, employee.agent_id)
    return success(serialize_employee(employee, agent))


@router.delete("/{employee_id}", summary="停用数字员工")
async def disable_employee(
    employee_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    employee.status = "disabled"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="employee.disable",
        resource_type="digital_employee",
        resource_id=employee.id,
        ip_address=client_ip(request),
    )
    return success(None, "员工已停用")
