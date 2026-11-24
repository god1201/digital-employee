"""监控指标计算：任务概览、队列、Worker 心跳。"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.utils import as_utc
from app.domains.operations.models import WorkerHeartbeat
from app.domains.workflows.tasks.models import TaskInstance, TaskStep
from app.domains.workforce.employees.models import DigitalEmployee

STATUSES = ("pending", "running", "waiting_human", "succeeded", "failed", "cancelled")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


async def _queue_stats(db: AsyncSession, tenant_id: int) -> tuple[dict[str, int], float]:
    rows = (
        await db.execute(
            select(TaskInstance.status, func.count())
            .where(TaskInstance.tenant_id == tenant_id)
            .group_by(TaskInstance.status)
        )
    ).all()
    counts = {row[0]: int(row[1]) for row in rows}

    pending_times = list(
        (
            await db.scalars(
                select(TaskInstance.created_at).where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.status == "pending",
                )
            )
        ).all()
    )
    oldest_age = 0.0
    if pending_times:
        oldest = min(as_utc(value) for value in pending_times if value is not None)
        oldest_age = max(0.0, (utcnow() - oldest).total_seconds())
    return counts, oldest_age


async def compute_queue(db: AsyncSession, tenant_id: int) -> dict:
    counts, oldest_age = await _queue_stats(db, tenant_id)
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "waiting_human": counts.get("waiting_human", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
        "oldest_pending_age_seconds": round(oldest_age, 1),
    }


async def list_workers(db: AsyncSession) -> dict:
    rows = list(
        (
            await db.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()))
        ).all()
    )
    now = utcnow()
    cutoff = now - timedelta(seconds=settings.worker_heartbeat_timeout)
    active = 0
    stale = 0
    items = []

    for row in rows:
        last_seen = as_utc(row.last_seen_at)
        is_active = row.status == "running" and last_seen is not None and last_seen >= cutoff
        if is_active:
            active += 1
        elif row.status == "running":
            stale += 1
        items.append(
            {
                "worker_id": row.worker_id,
                "hostname": row.hostname,
                "pid": row.pid,
                "status": row.status,
                "active": is_active,
                "current_tasks": row.current_tasks,
                "started_at": as_utc(row.started_at).isoformat() if row.started_at else None,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
            }
        )

    return {
        "total": len(rows),
        "active": active,
        "stale": stale,
        "workers": items,
    }


async def update_heartbeat(
    worker_id: str,
    *,
    hostname: str,
    pid: int,
    status: str,
    current_tasks: int,
    started_at,
) -> None:
    now = utcnow()
    async with SessionLocal() as session:
        row = await session.scalar(
            select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
        )
        if row is None:
            row = WorkerHeartbeat(
                worker_id=worker_id,
                hostname=hostname,
                pid=pid,
                status=status,
                current_tasks=current_tasks,
                started_at=started_at,
                last_seen_at=now,
            )
            session.add(row)
        else:
            row.status = status
            row.current_tasks = current_tasks
            row.last_seen_at = now
        await session.commit()


async def compute_overview(db: AsyncSession, tenant_id: int, days: int = 7) -> dict:
    days = max(1, min(days, 90))
    now = utcnow()
    cutoff = now - timedelta(days=days)

    instances = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                )
                .order_by(TaskInstance.id.desc())
                .limit(10_000)
            )
        ).all()
    )

    totals = {status: 0 for status in STATUSES}
    for instance in instances:
        totals[instance.status] = totals.get(instance.status, 0) + 1

    succeeded = totals["succeeded"]
    failed = totals["failed"]
    finished = succeeded + failed
    success_rate = succeeded / finished if finished else 0.0
    failure_rate = failed / finished if finished else 0.0

    retried = sum(1 for instance in instances if (instance.attempt or 0) > 1)
    retry_rate = retried / len(instances) if instances else 0.0

    durations: list[float] = []
    for instance in instances:
        if instance.started_at and instance.finished_at:
            started = as_utc(instance.started_at)
            finished_at = as_utc(instance.finished_at)
            if started and finished_at:
                duration = (finished_at - started).total_seconds() * 1000
                if duration >= 0:
                    durations.append(duration)
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    human_count = (
        await db.scalar(
            select(func.count(func.distinct(TaskStep.instance_id)))
            .select_from(TaskStep)
            .join(TaskInstance, TaskInstance.id == TaskStep.instance_id)
            .where(
                TaskInstance.tenant_id == tenant_id,
                TaskInstance.created_at >= cutoff,
                TaskStep.step_type == "human",
            )
        )
        or 0
    )
    human_rate = human_count / len(instances) if instances else 0.0

    token_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(TaskStep.tokens), 0),
                func.coalesce(func.sum(TaskStep.cost), 0.0),
            )
            .select_from(TaskStep)
            .join(TaskInstance, TaskInstance.id == TaskStep.instance_id)
            .where(
                TaskInstance.tenant_id == tenant_id,
                TaskInstance.created_at >= cutoff,
            )
        )
    ).one()
    total_tokens = int(token_row[0] or 0)
    total_cost = float(token_row[1] or 0.0)

    employee_ids = {instance.employee_id for instance in instances if instance.employee_id}
    employee_names: dict[int, str] = {}
    if employee_ids:
        rows = (
            await db.execute(
                select(DigitalEmployee.id, DigitalEmployee.name).where(
                    DigitalEmployee.id.in_(employee_ids),
                    DigitalEmployee.tenant_id == tenant_id,
                )
            )
        ).all()
        employee_names = {row[0]: row[1] for row in rows}

    employee_stats: dict[int | None, dict] = {}
    for instance in instances:
        key = instance.employee_id
        item = employee_stats.setdefault(
            key,
            {
                "employee_id": key,
                "employee_name": employee_names.get(key, "未知员工") if key else "未绑定",
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "_attempts": 0,
            },
        )
        item["total"] += 1
        item["_attempts"] += instance.attempt or 0
        if instance.status == "succeeded":
            item["succeeded"] += 1
        elif instance.status == "failed":
            item["failed"] += 1

    for item in employee_stats.values():
        finished_count = item["succeeded"] + item["failed"]
        item["success_rate"] = (
            round(item["succeeded"] / finished_count, 4) if finished_count else 0.0
        )
        item["avg_attempt"] = round(item["_attempts"] / item["total"], 2) if item["total"] else 0.0
        del item["_attempts"]

    type_stats: dict[str, dict] = {}
    for instance in instances:
        key = instance.task_type or "unknown"
        item = type_stats.setdefault(
            key, {"task_type": key, "total": 0, "succeeded": 0, "failed": 0}
        )
        item["total"] += 1
        if instance.status == "succeeded":
            item["succeeded"] += 1
        elif instance.status == "failed":
            item["failed"] += 1

    today = now.date()
    series: dict[str, dict] = {}
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        series[key] = {"date": key, "total": 0, "succeeded": 0, "failed": 0}
    for instance in instances:
        created = as_utc(instance.created_at)
        if created is None:
            continue
        key = created.date().isoformat()
        if key not in series:
            continue
        series[key]["total"] += 1
        if instance.status == "succeeded":
            series[key]["succeeded"] += 1
        elif instance.status == "failed":
            series[key]["failed"] += 1

    queue_counts, oldest_age = await _queue_stats(db, tenant_id)
    workers = await list_workers(db)

    recent_failures = [
        {
            "id": instance.id,
            "title": instance.title,
            "employee_id": instance.employee_id,
            "error": instance.error,
            "finished_at": as_utc(instance.finished_at).isoformat()
            if instance.finished_at
            else None,
        }
        for instance in instances
        if instance.status == "failed"
    ][:5]

    return {
        "range_days": days,
        "generated_at": now.isoformat(),
        "totals": totals,
        "rates": {
            "success_rate": round(success_rate, 4),
            "failure_rate": round(failure_rate, 4),
            "human_intervention_rate": round(human_rate, 4),
            "retry_rate": round(retry_rate, 4),
        },
        "performance": {
            "avg_duration_ms": round(avg_duration, 1),
            "p95_duration_ms": round(_percentile(durations, 95), 1),
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
        },
        "queue": {
            "pending": queue_counts.get("pending", 0),
            "running": queue_counts.get("running", 0),
            "waiting_human": queue_counts.get("waiting_human", 0),
            "oldest_pending_age_seconds": round(oldest_age, 1),
        },
        "workers": {
            "total": workers["total"],
            "active": workers["active"],
            "stale": workers["stale"],
        },
        "by_employee": sorted(
            employee_stats.values(), key=lambda item: item["total"], reverse=True
        ),
        "by_task_type": sorted(type_stats.values(), key=lambda item: item["total"], reverse=True),
        "time_series": list(series.values()),
        "recent_failures": recent_failures,
    }
