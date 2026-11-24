from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentAdmin, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.operations.alerting import evaluate_rule
from app.domains.operations.models import AlertEvent, AlertRule
from app.domains.operations.schemas import (
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
)

router = APIRouter(tags=["告警"])


async def _get_rule(db: DbSession, tenant_id: int, rule_id: int) -> AlertRule:
    rule = await db.scalar(
        select(AlertRule).where(
            AlertRule.id == rule_id,
            AlertRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise NotFoundError("告警规则不存在")
    return rule


async def _get_event(db: DbSession, tenant_id: int, event_id: int) -> AlertEvent:
    event = await db.scalar(
        select(AlertEvent).where(
            AlertEvent.id == event_id,
            AlertEvent.tenant_id == tenant_id,
        )
    )
    if event is None:
        raise NotFoundError("告警事件不存在")
    return event


@router.get("/alert-rules", summary="告警规则列表（管理员）")
async def list_rules(
    db: DbSession,
    current_admin: CurrentAdmin,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    enabled: bool | None = None,
):
    conditions = [AlertRule.tenant_id == current_admin.tenant_id]
    if enabled is not None:
        conditions.append(AlertRule.enabled.is_(enabled))

    stmt = select(AlertRule).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AlertRule.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [AlertRuleOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/alert-rules", summary="创建告警规则（管理员）")
async def create_rule(
    payload: AlertRuleCreate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    rule = AlertRule(
        tenant_id=current_admin.tenant_id,
        created_by=current_admin.id,
        **payload.model_dump(),
    )
    db.add(rule)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="alert_rule.create",
        resource_type="alert_rule",
        resource_id=rule.id,
        detail={
            "metric": rule.metric,
            "operator": rule.operator,
            "threshold": rule.threshold,
        },
        ip_address=client_ip(request),
    )
    return success(AlertRuleOut.model_validate(rule).model_dump(mode="json"))


@router.patch("/alert-rules/{rule_id}", summary="更新告警规则（管理员）")
async def update_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    rule = await _get_rule(db, current_admin.tenant_id, rule_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="alert_rule.update",
        resource_type="alert_rule",
        resource_id=rule.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(AlertRuleOut.model_validate(rule).model_dump(mode="json"))


@router.delete("/alert-rules/{rule_id}", summary="删除告警规则（管理员）")
async def delete_rule(
    rule_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    rule = await _get_rule(db, current_admin.tenant_id, rule_id)
    await db.delete(rule)
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="alert_rule.delete",
        resource_type="alert_rule",
        resource_id=rule_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/alert-rules/{rule_id}/evaluate", summary="立即评估告警规则（管理员）")
async def evaluate(
    rule_id: int,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    rule = await _get_rule(db, current_admin.tenant_id, rule_id)
    return success(await evaluate_rule(db, rule))


@router.get("/alert-events", summary="告警事件列表（管理员）")
async def list_events(
    db: DbSession,
    current_admin: CurrentAdmin,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    rule_id: int | None = None,
):
    conditions = [AlertEvent.tenant_id == current_admin.tenant_id]
    if status:
        conditions.append(AlertEvent.status == status)
    if rule_id is not None:
        conditions.append(AlertEvent.rule_id == rule_id)

    stmt = select(AlertEvent).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AlertEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [AlertEventOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/alert-events/{event_id}/ack", summary="确认告警事件（管理员）")
async def ack_event(
    event_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    event = await _get_event(db, current_admin.tenant_id, event_id)
    event.status = "acked"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="alert_event.ack",
        resource_type="alert_event",
        resource_id=event.id,
        ip_address=client_ip(request),
    )
    return success(AlertEventOut.model_validate(event).model_dump(mode="json"))
