from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.skills.agents.models import Agent
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.schemas import EmployeeOut


async def get_employee(db: AsyncSession, tenant_id: int, employee_id: int) -> DigitalEmployee:
    employee = await db.scalar(
        select(DigitalEmployee).where(
            DigitalEmployee.id == employee_id,
            DigitalEmployee.tenant_id == tenant_id,
        )
    )
    if employee is None:
        raise NotFoundError("数字员工不存在")
    return employee


async def get_agent(
    db: AsyncSession,
    tenant_id: int,
    agent_id: int | None,
    *,
    active_only: bool = False,
) -> Agent | None:
    if not agent_id:
        return None
    conditions = [Agent.id == agent_id, Agent.tenant_id == tenant_id]
    if active_only:
        conditions.append(Agent.status == "active")
    return await db.scalar(select(Agent).where(*conditions))


async def require_agent(
    db: AsyncSession, tenant_id: int, agent_id: int
) -> Agent:
    agent = await get_agent(db, tenant_id, agent_id, active_only=True)
    if agent is None:
        raise BadRequestError("Agent 不存在或已停用")
    return agent


async def employee_agent_map(
    db: AsyncSession, employees: list[DigitalEmployee]
) -> dict[int, Agent]:
    agent_ids = {employee.agent_id for employee in employees if employee.agent_id}
    if not agent_ids:
        return {}
    rows = list(
        (
            await db.scalars(
                select(Agent).where(Agent.id.in_(agent_ids))
            )
        ).all()
    )
    return {agent.id: agent for agent in rows}


def serialize_employee(
    employee: DigitalEmployee, agent: Agent | None = None
) -> dict:
    data = EmployeeOut.model_validate(employee).model_dump(mode="json")
    if agent is not None:
        data["agent_name"] = agent.name
        data["agent_code"] = agent.code
    return data


async def ensure_employee_exists(db: AsyncSession, tenant_id: int, employee_id: int | None) -> None:
    if employee_id is not None:
        await get_employee(db, tenant_id, employee_id)


def bound_knowledge_base_ids(employee: DigitalEmployee | None) -> list[int]:
    """员工已绑定的知识库 ID；未配置时返回空列表（表示不限制）。"""
    if employee is None:
        return []
    config = employee.config or {}
    values = config.get("knowledge_base_ids") or []
    if not isinstance(values, list):
        values = [values]
    result: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result
