"""多员工协作：把参与者编排成 employee 步骤，复用一个父任务实例。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.collaboration.models import CollaborationRun
from app.domains.workforce.collaboration.schemas import CollaborationCreate
from app.domains.workforce.employees.models import DigitalEmployee

MAX_PARTICIPANTS = 10


async def _resolve_employee(
    db: AsyncSession,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    employee_code: str | None = None,
) -> DigitalEmployee:
    employee = None
    if employee_id:
        employee = await db.get(DigitalEmployee, employee_id)
    elif employee_code:
        employee = await db.scalar(
            select(DigitalEmployee).where(
                DigitalEmployee.tenant_id == tenant_id,
                DigitalEmployee.code == employee_code,
            )
        )
    if employee is None or employee.tenant_id != tenant_id:
        raise NotFoundError("协作参与员工不存在")
    return employee


async def create_collaboration(
    db: AsyncSession,
    tenant_id: int,
    payload: CollaborationCreate,
    *,
    user_id: int | None = None,
) -> CollaborationRun:
    owner = await _resolve_employee(
        db, tenant_id, employee_id=payload.owner_employee_id
    )
    if len(payload.participants) > MAX_PARTICIPANTS:
        raise BadRequestError(f"协作参与者最多 {MAX_PARTICIPANTS} 人")

    resolved = []
    for item in payload.participants:
        employee = await _resolve_employee(
            db,
            tenant_id,
            employee_id=item.employee_id,
            employee_code=item.employee_code,
        )
        resolved.append((employee, item.instruction, item.steps))

    employee_steps = []
    for employee, instruction, child_steps in resolved:
        employee_steps.append(
            {
                "name": f"委派 {employee.name}"[:255],
                "type": "employee",
                "employee_id": employee.id,
                "employee_code": employee.code,
                "prompt": (
                    f"{instruction}\n\n协作目标：{payload.goal}\n"
                    "上游结果：{{last.output}}"
                ),
                "description": instruction,
                "arguments": {},
                "child_steps": child_steps,
            }
        )
    steps = []
    if payload.mode == "parallel":
        steps.append(
            {
                "name": "并行协作",
                "type": "parallel",
                "sub_steps": employee_steps,
                "description": payload.goal,
                "arguments": {},
            }
        )
    else:
        steps.extend(employee_steps)
    if payload.summarize:
        steps.append(
            {
                "name": "汇总协作结果",
                "type": "llm",
                "prompt": (
                    f"请汇总以下协作结果并给出结论。\n目标：{payload.goal}\n"
                    + "最后结果：{{last.output}}"
                ),
                "arguments": {},
            }
        )

    instance = TaskInstance(
        tenant_id=tenant_id,
        employee_id=owner.id,
        title=f"协作：{payload.goal[:60]}"[:255],
        task_type="free",
        status="pending",
        input={"request": payload.goal, "collaboration": True},
        output={},
        plan=steps,
        trace_id=uuid.uuid4().hex,
        created_by=user_id,
    )
    db.add(instance)
    await db.flush()

    run = CollaborationRun(
        tenant_id=tenant_id,
        owner_employee_id=owner.id,
        goal=payload.goal,
        mode=payload.mode,
        participants=[
            {
                "employee_id": employee.id,
                "employee_code": employee.code,
                "name": employee.name,
                "instruction": instruction,
                "steps": child_steps,
            }
            for employee, instruction, child_steps in resolved
        ],
        parent_instance_id=instance.id,
        status="pending",
        result={},
        created_by=user_id,
    )
    db.add(run)
    await db.flush()
    return run


async def sync_collaboration(db: AsyncSession, run: CollaborationRun) -> CollaborationRun:
    if run.parent_instance_id is None:
        return run
    instance = await db.get(TaskInstance, run.parent_instance_id)
    if instance is None:
        return run
    if run.status != instance.status:
        run.status = instance.status
    if instance.status == "succeeded" and instance.output:
        run.result = instance.output
    return run


async def get_collaboration(
    db: AsyncSession, tenant_id: int, collaboration_id: int
) -> CollaborationRun:
    run = await db.scalar(
        select(CollaborationRun).where(
            CollaborationRun.id == collaboration_id,
            CollaborationRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise NotFoundError("协作会话不存在")
    return await sync_collaboration(db, run)
