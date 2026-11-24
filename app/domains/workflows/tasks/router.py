import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.base import utcnow
from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.attribution import attribute_intervention
from app.domains.learning.implicit import record_abandon
from app.domains.learning.models import FailureAttribution, InterventionDelta
from app.domains.learning.service import compute_diff
from app.domains.workflows.tasks.models import TaskDefinition, TaskInstance, TaskStep
from app.domains.workflows.tasks.schemas import (
    TaskDefinitionCreate,
    TaskDefinitionOut,
    TaskDefinitionUpdate,
    TaskInstanceOut,
    TaskResumeRequest,
    TaskRunRequest,
    TaskStepOut,
)
from app.domains.workforce.employees.service import get_employee
from app.worker.enqueue import enqueue_task

router = APIRouter(prefix="/tasks", tags=["任务体系"])


async def _get_definition(db: DbSession, tenant_id: int, definition_id: int) -> TaskDefinition:
    definition = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == definition_id,
            TaskDefinition.tenant_id == tenant_id,
        )
    )
    if definition is None:
        raise NotFoundError("任务定义不存在")
    return definition


async def _get_instance(db: DbSession, tenant_id: int, instance_id: int) -> TaskInstance:
    instance = await db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == instance_id,
            TaskInstance.tenant_id == tenant_id,
        )
    )
    if instance is None:
        raise NotFoundError("任务实例不存在")
    return instance


@router.get("/definitions", summary="任务定义列表")
async def list_definitions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    task_type: str | None = None,
    enabled: bool | None = None,
):
    conditions = [TaskDefinition.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(TaskDefinition.employee_id == employee_id)
    if task_type:
        conditions.append(TaskDefinition.task_type == task_type)
    if enabled is not None:
        conditions.append(TaskDefinition.enabled.is_(enabled))

    stmt = select(TaskDefinition).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(TaskDefinition.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TaskDefinitionOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/definitions", summary="创建任务定义")
async def create_definition(
    payload: TaskDefinitionCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)

    exists = await db.scalar(
        select(TaskDefinition.id).where(
            TaskDefinition.tenant_id == current_user.tenant_id,
            TaskDefinition.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("任务编码已存在")

    definition = TaskDefinition(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(definition)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=definition.employee_id,
        action="task_definition.create",
        resource_type="task_definition",
        resource_id=definition.id,
        detail={"code": definition.code, "type": definition.task_type},
        ip_address=client_ip(request),
    )
    return success(TaskDefinitionOut.model_validate(definition).model_dump(mode="json"))


@router.patch("/definitions/{definition_id}", summary="更新任务定义")
async def update_definition(
    definition_id: int,
    payload: TaskDefinitionUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    definition = await _get_definition(db, current_user.tenant_id, definition_id)
    changes = payload.model_dump(exclude_unset=True)
    if "employee_id" in changes and changes["employee_id"] is not None:
        await get_employee(db, current_user.tenant_id, changes["employee_id"])
    for field, value in changes.items():
        setattr(definition, field, value)
    definition.version += 1
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="task_definition.update",
        resource_type="task_definition",
        resource_id=definition.id,
        detail={"fields": sorted(changes.keys()), "version": definition.version},
        ip_address=client_ip(request),
    )
    return success(TaskDefinitionOut.model_validate(definition).model_dump(mode="json"))


@router.get("/instances", summary="任务实例列表")
async def list_instances(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    status: str | None = None,
    task_type: str | None = None,
    project_id: int | None = None,
    unlinked: bool = False,
):
    conditions = [TaskInstance.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(TaskInstance.employee_id == employee_id)
    if status:
        conditions.append(TaskInstance.status == status)
    if task_type:
        conditions.append(TaskInstance.task_type == task_type)
    if project_id is not None:
        conditions.append(TaskInstance.project_id == project_id)
    if unlinked:
        conditions.append(TaskInstance.project_id.is_(None))

    stmt = select(TaskInstance).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(TaskInstance.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TaskInstanceOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/instances", summary="发起任务（创建执行实例）")
async def run_task(
    payload: TaskRunRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, payload.employee_id)

    definition: TaskDefinition | None = None
    if payload.definition_id is not None:
        definition = await _get_definition(db, current_user.tenant_id, payload.definition_id)
        if not definition.enabled:
            raise BadRequestError("任务定义已停用")
        if definition.employee_id is not None and definition.employee_id != payload.employee_id:
            raise BadRequestError("任务定义绑定的数字员工与请求不一致")
        if not definition.steps:
            raise BadRequestError("任务定义未配置步骤")

    title = payload.title or (definition.name if definition else "自由任务")
    task_type = definition.task_type if definition else "free"

    instance = TaskInstance(
        tenant_id=current_user.tenant_id,
        definition_id=definition.id if definition else None,
        employee_id=payload.employee_id,
        title=title,
        task_type=task_type,
        status="pending",
        input=payload.input,
        output={},
        next_step_index=0,
        attempt=0,
        max_attempts=payload.max_attempts or settings.task_max_attempts,
        priority=payload.priority,
        trace_id=uuid.uuid4().hex,
        created_by=current_user.id,
    )
    db.add(instance)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=instance.employee_id,
        action="task.run",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={"title": instance.title, "task_type": task_type},
        ip_address=client_ip(request),
        trace_id=instance.trace_id,
    )
    # 提交后由 Worker 原子领取执行；Celery 模式下直接投递
    await db.commit()
    if settings.use_celery:
        enqueue_task(instance.id, 0)
    return success(TaskInstanceOut.model_validate(instance).model_dump(mode="json"))


@router.get("/instances/{instance_id}", summary="任务详情（含步骤轨迹）")
async def get_instance(
    instance_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await _get_instance(db, current_user.tenant_id, instance_id)
    steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(TaskStep.instance_id == instance.id)
                .order_by(TaskStep.step_index)
            )
        ).all()
    )
    data = TaskInstanceOut.model_validate(instance).model_dump(mode="json")
    data["steps"] = [TaskStepOut.model_validate(step).model_dump(mode="json") for step in steps]
    return success(data)


@router.get("/instances/{instance_id}/replay", summary="轨迹逐帧回放")
async def replay_instance(
    instance_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await _get_instance(db, current_user.tenant_id, instance_id)
    steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(TaskStep.instance_id == instance.id)
                .order_by(TaskStep.step_index, TaskStep.id)
            )
        ).all()
    )
    interventions = list(
        (
            await db.scalars(
                select(InterventionDelta)
                .where(InterventionDelta.instance_id == instance.id)
                .order_by(InterventionDelta.id)
            )
        ).all()
    )
    attributions = list(
        (
            await db.scalars(
                select(FailureAttribution)
                .where(FailureAttribution.instance_id == instance.id)
                .order_by(FailureAttribution.id)
            )
        ).all()
    )
    frames = [
        {
            "step_id": step.id,
            "step_index": step.step_index,
            "name": step.name,
            "step_type": step.step_type,
            "status": step.status,
            "tool_code": step.tool_code,
            "input": step.input,
            "output": step.output,
            "error": step.error,
            "tokens": step.tokens,
            "cost": step.cost,
            "latency_ms": step.latency_ms,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "finished_at": step.finished_at.isoformat() if step.finished_at else None,
        }
        for step in steps
    ]
    return success(
        {
            "instance": {
                "id": instance.id,
                "title": instance.title,
                "status": instance.status,
                "employee_id": instance.employee_id,
                "trace_id": instance.trace_id,
                "task_type": instance.task_type,
                "attempt": instance.attempt,
                "error": instance.error,
                "created_at": instance.created_at.isoformat(),
                "started_at": instance.started_at.isoformat()
                if instance.started_at
                else None,
                "finished_at": instance.finished_at.isoformat()
                if instance.finished_at
                else None,
            },
            "frames": frames,
            "interventions": [
                {
                    "id": item.id,
                    "step_id": item.step_id,
                    "status": item.status,
                    "diff": item.diff,
                    "comment": item.comment,
                    "created_at": item.created_at.isoformat(),
                }
                for item in interventions
            ],
            "attributions": [
                {
                    "id": item.id,
                    "category": item.category,
                    "signals": item.signals,
                    "suggestion": item.suggestion,
                    "created_at": item.created_at.isoformat(),
                }
                for item in attributions
            ],
        }
    )


@router.post("/instances/{instance_id}/resume", summary="人工确认后恢复任务")
async def resume_instance(
    instance_id: int,
    payload: TaskResumeRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await _get_instance(db, current_user.tenant_id, instance_id)
    if instance.status != "waiting_human":
        raise BadRequestError("任务不在等待人工状态")

    step = await db.scalar(
        select(TaskStep)
        .where(
            TaskStep.instance_id == instance.id,
            TaskStep.status == "waiting",
        )
        .order_by(TaskStep.step_index.desc())
    )
    if step is None:
        raise BadRequestError("未找到等待中的步骤")

    step_output = dict(step.output or {})
    # 契约红线导致的等待：批准后需要重新执行该工具步骤，而不是跳过
    is_contract_gate = bool(step_output.get("contract_gate"))
    # 人工确认步骤本身没有输出，接管 diff 应对比它之前最近一次成功的草稿
    delta_original = step_output
    delta_step_id = step.id
    if not delta_original and step.step_type == "human":
        draft = await db.scalar(
            select(TaskStep)
            .where(
                TaskStep.instance_id == instance.id,
                TaskStep.step_index < step.step_index,
                TaskStep.status == "succeeded",
            )
            .order_by(TaskStep.step_index.desc())
        )
        if draft is not None:
            delta_original = dict(draft.output or {})
            delta_step_id = draft.id
    if is_contract_gate:
        # 门禁步骤不产生业务结果：批准后重新执行，拒绝后作废
        step.status = "cancelled"
    else:
        step.status = "succeeded" if payload.approved else "failed"
    step.output = {
        **step_output,
        "approved": payload.approved,
        "comment": payload.comment,
    }
    step.finished_at = utcnow()

    if payload.approved:
        if is_contract_gate:
            instance.next_step_index = step.step_index
            # 记录人工放行，避免恢复执行时再次被同一规则拦截
            plan = list(instance.plan or [])
            if 0 <= step.step_index < len(plan):
                plan[step.step_index] = {
                    **plan[step.step_index],
                    "approved_gate": True,
                }
                instance.plan = plan
        else:
            instance.next_step_index = step.step_index + 1
        instance.status = "pending"
        # 人工恢复不算一次重试，抵消 Worker 领取时的 attempt + 1
        instance.attempt = max(0, instance.attempt - 1)
        instance.next_run_at = None
        instance.error = None
        instance.locked_by = None
        instance.locked_at = None
    else:
        instance.status = "cancelled"
        instance.error = payload.comment or "人工拒绝"
        instance.finished_at = utcnow()

    intervention_id: int | None = None
    attribution_id: int | None = None
    if payload.final_output is not None:
        delta = InterventionDelta(
            tenant_id=current_user.tenant_id,
            employee_id=instance.employee_id,
            instance_id=instance.id,
            step_id=delta_step_id,
            trace_id=instance.trace_id,
            actor_id=current_user.id,
            source_type="human_takeover_diff",
            original_output=delta_original,
            final_output=payload.final_output,
            diff=compute_diff(delta_original, payload.final_output),
            comment=payload.comment,
            created_by=current_user.id,
        )
        db.add(delta)
        await db.flush()
        intervention_id = delta.id
        attribution = await attribute_intervention(db, delta, user_id=current_user.id)
        delta.status = "attributed"
        attribution_id = attribution.id

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=instance.employee_id,
        action="task.resume" if payload.approved else "task.reject",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={
            "approved": payload.approved,
            "comment": payload.comment,
            "intervention_id": intervention_id,
            "attribution_id": attribution_id,
        },
        ip_address=client_ip(request),
        trace_id=instance.trace_id,
    )
    await db.commit()
    return success(TaskInstanceOut.model_validate(instance).model_dump(mode="json"))


@router.post("/instances/{instance_id}/retry", summary="手动重试失败任务")
async def retry_instance(
    instance_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await _get_instance(db, current_user.tenant_id, instance_id)
    if instance.status != "failed":
        raise BadRequestError("只有失败的任务可以重试")

    instance.status = "pending"
    instance.attempt = 0
    instance.next_run_at = None
    instance.next_step_index = max(0, instance.current_step_index)
    instance.error = None
    instance.finished_at = None
    instance.locked_by = None
    instance.locked_at = None
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=instance.employee_id,
        action="task.retry",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={"next_step_index": instance.next_step_index},
        ip_address=client_ip(request),
        trace_id=instance.trace_id,
    )
    await db.commit()
    return success(TaskInstanceOut.model_validate(instance).model_dump(mode="json"))


@router.post("/instances/{instance_id}/cancel", summary="取消任务")
async def cancel_instance(
    instance_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await _get_instance(db, current_user.tenant_id, instance_id)
    if instance.status not in {"pending", "running", "waiting_human"}:
        raise BadRequestError("当前状态不可取消")
    instance.status = "cancelled"
    await db.flush()
    await record_abandon(db, instance, user_id=current_user.id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=instance.employee_id,
        action="task.cancel",
        resource_type="task_instance",
        resource_id=instance.id,
        ip_address=client_ip(request),
        trace_id=instance.trace_id,
    )
    return success(TaskInstanceOut.model_validate(instance).model_dump(mode="json"))
