from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workflows.tasks.models import TaskTrigger
from app.domains.workflows.tasks.schemas import (
    TaskTriggerCreate,
    TaskTriggerOut,
    TaskTriggerUpdate,
)
from app.domains.workflows.tasks.triggers import (
    create_trigger,
    fire_event_triggers,
    fire_trigger_manually,
    update_trigger,
)
from app.domains.workforce.employees.service import get_employee
from app.worker.enqueue import enqueue_task

router = APIRouter(prefix="/task-triggers", tags=["任务触发器"])


async def _get_trigger(db: DbSession, tenant_id: int, trigger_id: int) -> TaskTrigger:
    trigger = await db.scalar(
        select(TaskTrigger).where(
            TaskTrigger.id == trigger_id,
            TaskTrigger.tenant_id == tenant_id,
        )
    )
    if trigger is None:
        raise NotFoundError("触发器不存在")
    return trigger


@router.get("", summary="触发器列表")
async def list_triggers(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    trigger_type: str | None = None,
    enabled: bool | None = None,
):
    conditions = [TaskTrigger.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(TaskTrigger.employee_id == employee_id)
    if trigger_type:
        conditions.append(TaskTrigger.trigger_type == trigger_type)
    if enabled is not None:
        conditions.append(TaskTrigger.enabled.is_(enabled))
    stmt = select(TaskTrigger).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(TaskTrigger.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TaskTriggerOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post(
    "",
    summary="创建触发器（定时/每日/事件）",
    dependencies=[Depends(get_current_admin)],
)
async def create_trigger_endpoint(
    payload: TaskTriggerCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, payload.employee_id)
    trigger = await create_trigger(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=trigger.employee_id,
        action="trigger.create",
        resource_type="task_trigger",
        resource_id=trigger.id,
        detail={
            "type": trigger.trigger_type,
            "interval_seconds": trigger.interval_seconds,
            "daily_at": trigger.daily_at,
            "event_name": trigger.event_name,
        },
        ip_address=client_ip(request),
    )
    return success(TaskTriggerOut.model_validate(trigger).model_dump(mode="json"))


@router.patch(
    "/{trigger_id}",
    summary="更新/启停触发器",
    dependencies=[Depends(get_current_admin)],
)
async def update_trigger_endpoint(
    trigger_id: int,
    payload: TaskTriggerUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    trigger = await _get_trigger(db, current_user.tenant_id, trigger_id)
    trigger = await update_trigger(db, trigger, payload)
    return success(TaskTriggerOut.model_validate(trigger).model_dump(mode="json"))


@router.delete(
    "/{trigger_id}",
    summary="删除触发器",
    dependencies=[Depends(get_current_admin)],
)
async def delete_trigger(
    trigger_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    trigger = await _get_trigger(db, current_user.tenant_id, trigger_id)
    await db.delete(trigger)
    await db.flush()
    return success(None, "触发器已删除")


@router.post(
    "/{trigger_id}/fire",
    summary="立即触发一次",
    dependencies=[Depends(get_current_admin)],
)
async def fire_trigger(
    trigger_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    trigger = await _get_trigger(db, current_user.tenant_id, trigger_id)
    instance = await fire_trigger_manually(db, trigger)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=trigger.employee_id,
        action="trigger.fire",
        resource_type="task_trigger",
        resource_id=trigger.id,
        detail={"instance_id": instance.id},
        ip_address=client_ip(request),
    )
    await db.commit()
    queued = enqueue_task(instance.id) if settings.use_celery else False
    return success(
        {"trigger_id": trigger.id, "instance_id": instance.id, "queued": queued}
    )


@router.post("/events/{event_name}", summary="触发事件型触发器")
async def fire_event(
    event_name: str,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    payload: dict | None = Body(default=None),
):
    instances = await fire_event_triggers(
        db, current_user.tenant_id, event_name, payload or {}
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="trigger.event",
        resource_type="task_trigger",
        detail={
            "event_name": event_name,
            "instances": [item.id for item in instances],
        },
        ip_address=client_ip(request),
    )
    await db.commit()
    queued = (
        sum(1 for item in instances if enqueue_task(item.id))
        if settings.use_celery
        else 0
    )
    return success(
        {
            "event_name": event_name,
            "created": len(instances),
            "instance_ids": [item.id for item in instances],
            "queued": queued,
        }
    )
