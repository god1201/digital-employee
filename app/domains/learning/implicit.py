"""隐式学习信号：重复追问、换说法、放弃、复制片段。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.learning.models import ImplicitSignal
from app.domains.learning.schemas import ImplicitSignalCreate
from app.domains.workflows.tasks.models import TaskInstance


async def record_signal(
    db: AsyncSession,
    tenant_id: int,
    payload: ImplicitSignalCreate,
    *,
    user_id: int | None = None,
) -> ImplicitSignal:
    signal = ImplicitSignal(
        tenant_id=tenant_id,
        created_by=user_id,
        **payload.model_dump(),
    )
    db.add(signal)
    await db.flush()
    return signal


async def record_abandon(
    db: AsyncSession,
    instance: TaskInstance,
    *,
    user_id: int | None = None,
) -> ImplicitSignal:
    signal = ImplicitSignal(
        tenant_id=instance.tenant_id,
        employee_id=instance.employee_id,
        instance_id=instance.id,
        trace_id=instance.trace_id,
        signal_type="abandon",
        content=instance.title[:2000],
        weight=1.0,
        payload={"status": instance.status},
        created_by=user_id,
    )
    db.add(signal)
    await db.flush()
    return signal


async def implicit_summary(
    db: AsyncSession, tenant_id: int, employee_id: int | None = None
) -> dict:
    conditions = [ImplicitSignal.tenant_id == tenant_id]
    if employee_id is not None:
        conditions.append(ImplicitSignal.employee_id == employee_id)
    rows = await db.execute(
        select(
            ImplicitSignal.signal_type,
            func.count(ImplicitSignal.id),
            func.sum(ImplicitSignal.weight),
        )
        .where(*conditions)
        .group_by(ImplicitSignal.signal_type)
    )
    by_type = {
        str(signal_type): {
            "count": int(count or 0),
            "weight": round(float(weight or 0), 2),
        }
        for signal_type, count, weight in rows
    }
    recent = list(
        (
            await db.scalars(
                select(ImplicitSignal)
                .where(*conditions)
                .order_by(ImplicitSignal.id.desc())
                .limit(10)
            )
        ).all()
    )
    return {
        "employee_id": employee_id,
        "by_type": by_type,
        "total": sum(item["count"] for item in by_type.values()),
        "recent": [
            {
                "id": item.id,
                "type": item.signal_type,
                "content": item.content[:200],
                "weight": item.weight,
                "created_at": item.created_at.isoformat(),
            }
            for item in recent
        ],
    }
