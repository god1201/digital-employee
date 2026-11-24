"""告警规则评估。"""

import logging
from datetime import timedelta

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.database import SessionLocal
from app.core.utils import as_utc
from app.domains.governance.audit.models import AuditLog
from app.domains.operations.models import AlertEvent, AlertRule
from app.domains.workflows.tasks.models import TaskInstance, TaskStep

logger = logging.getLogger(__name__)

SENSITIVE_PATTERNS = ("delete", "disable", "reject")


def check_condition(value: float, operator: str, threshold: float) -> bool:
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    return False


async def compute_metric(
    db: AsyncSession,
    tenant_id: int,
    metric: str,
    window_minutes: int,
) -> float:
    cutoff = utcnow() - timedelta(minutes=max(1, int(window_minutes)))

    if metric == "failure_rate":
        total = (
            await db.scalar(
                select(func.count())
                .select_from(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                    TaskInstance.status.in_(["succeeded", "failed"]),
                )
            )
            or 0
        )
        failed = (
            await db.scalar(
                select(func.count())
                .select_from(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                    TaskInstance.status == "failed",
                )
            )
            or 0
        )
        return failed / total if total else 0.0

    if metric == "queue_backlog":
        return float(
            await db.scalar(
                select(func.count())
                .select_from(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.status == "pending",
                )
            )
            or 0
        )

    if metric == "avg_duration_ms":
        rows = (
            await db.execute(
                select(TaskInstance.started_at, TaskInstance.finished_at).where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                    TaskInstance.started_at.is_not(None),
                    TaskInstance.finished_at.is_not(None),
                )
            )
        ).all()
        durations = []
        for started, finished in rows:
            started_at = as_utc(started)
            finished_at = as_utc(finished)
            if started_at and finished_at:
                value = (finished_at - started_at).total_seconds() * 1000
                if value >= 0:
                    durations.append(value)
        return sum(durations) / len(durations) if durations else 0.0

    if metric == "token_usage":
        return float(
            await db.scalar(
                select(func.coalesce(func.sum(TaskStep.tokens), 0))
                .select_from(TaskStep)
                .join(TaskInstance, TaskInstance.id == TaskStep.instance_id)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                )
            )
            or 0
        )

    if metric == "token_cost":
        return float(
            await db.scalar(
                select(func.coalesce(func.sum(TaskStep.cost), 0.0))
                .select_from(TaskStep)
                .join(TaskInstance, TaskInstance.id == TaskStep.instance_id)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                )
            )
            or 0.0
        )

    if metric == "human_intervention_rate":
        total = (
            await db.scalar(
                select(func.count())
                .select_from(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.created_at >= cutoff,
                )
            )
            or 0
        )
        human = (
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
        return human / total if total else 0.0

    if metric == "sensitive_actions":
        conditions = [AuditLog.action.like(f"%{pattern}%") for pattern in SENSITIVE_PATTERNS]
        return float(
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= cutoff,
                    or_(*conditions),
                )
            )
            or 0
        )

    return 0.0


async def _send_webhook(rule: AlertRule, event: AlertEvent) -> None:
    if not rule.webhook_url:
        return
    payload = {
        "type": "alert",
        "event_id": event.id,
        "rule": rule.name,
        "metric": event.metric,
        "operator": event.operator,
        "value": event.value,
        "threshold": event.threshold,
        "message": event.message,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(rule.webhook_url, json=payload)
        event.webhook_status = str(response.status_code)
    except Exception as exc:  # noqa: BLE001
        event.webhook_status = f"error: {exc}"[:64]
        logger.warning("告警 Webhook 发送失败: %s", exc)


async def evaluate_rule(db: AsyncSession, rule: AlertRule) -> dict:
    if not rule.enabled:
        return {
            "triggered": False,
            "value": 0.0,
            "event_id": None,
            "message": "规则已停用",
        }

    value = await compute_metric(db, rule.tenant_id, rule.metric, rule.window_minutes)
    triggered = check_condition(value, rule.operator, rule.threshold)
    event: AlertEvent | None = None
    message: str | None = None

    if triggered:
        now = utcnow()
        cooldown_cutoff = now - timedelta(minutes=max(0, rule.cooldown_minutes))
        result = await db.execute(
            update(AlertRule)
            .where(
                AlertRule.id == rule.id,
                or_(
                    AlertRule.last_triggered_at.is_(None),
                    AlertRule.last_triggered_at < cooldown_cutoff,
                ),
            )
            .values(last_triggered_at=now)
            # 数据库读出的时间可能无时区，关闭 ORM 同步比较避免 naive/aware 冲突
            .execution_options(synchronize_session=False)
        )
        if (result.rowcount or 0) == 1:
            message = f"[{rule.name}] {rule.metric}={value:.4f} {rule.operator} {rule.threshold}"
            event = AlertEvent(
                tenant_id=rule.tenant_id,
                rule_id=rule.id,
                rule_name=rule.name,
                metric=rule.metric,
                value=float(value),
                threshold=rule.threshold,
                operator=rule.operator,
                message=message,
                status="open",
            )
            db.add(event)
            await db.flush()
            await _send_webhook(rule, event)
        else:
            message = "触发但处于冷却期，未生成事件"

    await db.commit()
    return {
        "triggered": triggered,
        "value": float(value),
        "event_id": event.id if event else None,
        "message": message or ("已触发" if triggered else "未触发"),
    }


async def evaluate_all_rules() -> list[dict]:
    async with SessionLocal() as session:
        rules = list(
            (await session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True)))).all()
        )
        results = []
        for rule in rules:
            try:
                results.append(await evaluate_rule(session, rule))
            except Exception:  # noqa: BLE001
                logger.exception("告警规则评估失败: %s", rule.id)
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    logger.exception("告警评估会话回滚失败")
        return results
