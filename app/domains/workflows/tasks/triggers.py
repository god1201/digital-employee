"""任务触发器：定时/每日/事件驱动，支撑主动汇报和周期任务。"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.workflows.tasks.models import (
    TaskDefinition,
    TaskInstance,
    TaskTrigger,
)
from app.domains.workflows.tasks.schemas import TaskTriggerCreate, TaskTriggerUpdate
from app.worker.enqueue import enqueue_task

logger = logging.getLogger(__name__)


def compute_next_run(
    trigger_type: str,
    *,
    interval_seconds: int | None = None,
    daily_at: str | None = None,
    now: datetime | None = None,
) -> datetime | None:
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if trigger_type == "interval":
        seconds = max(60, int(interval_seconds or 3600))
        return current + timedelta(seconds=seconds)
    if trigger_type == "daily":
        if not daily_at or ":" not in daily_at:
            return None
        hour, minute = (int(part) for part in daily_at.split(":", 1))
        candidate = current.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate
    return None


async def _get_definition(
    db: AsyncSession, tenant_id: int, definition_id: int | None
) -> TaskDefinition | None:
    if definition_id is None:
        return None
    definition = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == definition_id,
            TaskDefinition.tenant_id == tenant_id,
        )
    )
    if definition is None:
        raise NotFoundError("任务定义不存在")
    return definition


async def create_trigger(
    db: AsyncSession,
    tenant_id: int,
    payload: TaskTriggerCreate,
    *,
    user_id: int | None = None,
) -> TaskTrigger:
    definition = await _get_definition(db, tenant_id, payload.definition_id)
    if (
        definition is not None
        and definition.employee_id is not None
        and definition.employee_id != payload.employee_id
    ):
        raise BadRequestError("任务定义绑定的员工与触发器不一致")

    trigger = TaskTrigger(
        tenant_id=tenant_id,
        employee_id=payload.employee_id,
        definition_id=payload.definition_id,
        name=payload.name,
        trigger_type=payload.trigger_type,
        interval_seconds=payload.interval_seconds,
        daily_at=payload.daily_at,
        event_name=payload.event_name,
        input=payload.input,
        enabled=payload.enabled,
        next_run_at=compute_next_run(
            payload.trigger_type,
            interval_seconds=payload.interval_seconds,
            daily_at=payload.daily_at,
        )
        if payload.enabled
        else None,
        created_by=user_id,
    )
    db.add(trigger)
    await db.flush()
    return trigger


async def update_trigger(
    db: AsyncSession,
    trigger: TaskTrigger,
    payload: TaskTriggerUpdate,
) -> TaskTrigger:
    changes = payload.model_dump(exclude_unset=True)
    if "definition_id" in changes:
        await _get_definition(db, trigger.tenant_id, changes["definition_id"])
    for field, value in changes.items():
        setattr(trigger, field, value)
    if trigger.trigger_type == "interval" and not trigger.interval_seconds:
        raise BadRequestError("interval 触发器缺少 interval_seconds")
    if trigger.trigger_type == "daily" and not trigger.daily_at:
        raise BadRequestError("daily 触发器缺少 daily_at")
    if trigger.trigger_type == "event" and not trigger.event_name:
        raise BadRequestError("event 触发器缺少 event_name")
    if trigger.enabled:
        trigger.next_run_at = compute_next_run(
            trigger.trigger_type,
            interval_seconds=trigger.interval_seconds,
            daily_at=trigger.daily_at,
        )
    else:
        trigger.next_run_at = None
    await db.flush()
    return trigger


async def create_instance_for_trigger(
    db: AsyncSession,
    trigger: TaskTrigger,
    *,
    input_override: dict | None = None,
) -> TaskInstance:
    definition = await _get_definition(db, trigger.tenant_id, trigger.definition_id)
    if definition is not None and not definition.enabled:
        raise BadRequestError("任务定义已停用")
    instance = TaskInstance(
        tenant_id=trigger.tenant_id,
        definition_id=trigger.definition_id,
        employee_id=trigger.employee_id,
        title=f"触发：{trigger.name}"[:255],
        task_type=definition.task_type if definition is not None else "free",
        status="pending",
        input={**(trigger.input or {}), **(input_override or {})},
        output={},
        trace_id=uuid.uuid4().hex,
        created_by=trigger.created_by,
    )
    db.add(instance)
    await db.flush()
    return instance


async def run_due_triggers(
    db: AsyncSession, *, now: datetime | None = None
) -> list[int]:
    current = now or utcnow()
    triggers = list(
        (
            await db.scalars(
                select(TaskTrigger)
                .where(
                    TaskTrigger.enabled.is_(True),
                    TaskTrigger.trigger_type.in_(["interval", "daily"]),
                    TaskTrigger.next_run_at.is_not(None),
                    TaskTrigger.next_run_at <= current,
                )
                .order_by(TaskTrigger.next_run_at)
                .limit(50)
            )
        ).all()
    )
    created: list[int] = []
    for trigger in triggers:
        try:
            instance = await create_instance_for_trigger(db, trigger)
        except BadRequestError as exc:
            logger.warning("触发器跳过: %s (%s)", trigger.id, exc.message)
            trigger.next_run_at = compute_next_run(
                trigger.trigger_type,
                interval_seconds=trigger.interval_seconds,
                daily_at=trigger.daily_at,
                now=current,
            )
            continue
        trigger.last_run_at = current
        trigger.next_run_at = compute_next_run(
            trigger.trigger_type,
            interval_seconds=trigger.interval_seconds,
            daily_at=trigger.daily_at,
            now=current,
        )
        created.append(instance.id)
    if created:
        await db.flush()
    return created


async def run_trigger_scheduler(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            async with SessionLocal() as session:
                created = await run_due_triggers(session)
                await session.commit()
            if settings.use_celery:
                # 必须等实例提交后再投递，避免 Celery Worker 读不到任务行
                for instance_id in created:
                    enqueue_task(instance_id)
        except Exception:  # noqa: BLE001
            logger.exception("触发器调度异常")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=max(5, settings.trigger_poll_interval)
            )
        except TimeoutError:
            continue


async def fire_trigger_manually(
    db: AsyncSession, trigger: TaskTrigger
) -> TaskInstance:
    instance = await create_instance_for_trigger(db, trigger)
    trigger.last_run_at = utcnow()
    await db.flush()
    return instance


async def fire_event_triggers(
    db: AsyncSession,
    tenant_id: int,
    event_name: str,
    payload: dict,
) -> list[TaskInstance]:
    triggers = list(
        (
            await db.scalars(
                select(TaskTrigger).where(
                    TaskTrigger.tenant_id == tenant_id,
                    TaskTrigger.enabled.is_(True),
                    TaskTrigger.trigger_type == "event",
                    TaskTrigger.event_name == event_name,
                )
            )
        ).all()
    )
    created = []
    now = utcnow()
    for trigger in triggers:
        instance = await create_instance_for_trigger(
            db, trigger, input_override=payload
        )
        trigger.last_run_at = now
        created.append(instance)
    await db.flush()
    return created
