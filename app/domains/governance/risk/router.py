from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.governance.risk.models import RiskCheck, RiskRule
from app.domains.governance.risk.schemas import (
    RiskCheckOut,
    RiskCheckRequest,
    RiskRuleCreate,
    RiskRuleOut,
    RiskRuleUpdate,
)
from app.domains.governance.risk.service import evaluate_risk

router = APIRouter(prefix="/risk", tags=["风控"])


async def _get_rule(db: DbSession, tenant_id: int, rule_id: int) -> RiskRule:
    rule = await db.scalar(
        select(RiskRule).where(
            RiskRule.id == rule_id,
            RiskRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise NotFoundError("风控规则不存在")
    return rule


@router.get("/rules", summary="风控规则列表")
async def list_rules(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = None,
    enabled: bool | None = None,
):
    conditions = [RiskRule.tenant_id == current_user.tenant_id]
    if category:
        conditions.append(RiskRule.category == category)
    if enabled is not None:
        conditions.append(RiskRule.enabled.is_(enabled))

    stmt = select(RiskRule).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(RiskRule.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [RiskRuleOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/rules", summary="创建风控规则")
async def create_rule(
    payload: RiskRuleCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    rule = RiskRule(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(rule)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="risk_rule.create",
        resource_type="risk_rule",
        resource_id=rule.id,
        detail={"category": rule.category, "action": rule.action},
        ip_address=client_ip(request),
    )
    return success(RiskRuleOut.model_validate(rule).model_dump(mode="json"))


@router.patch("/rules/{rule_id}", summary="更新风控规则")
async def update_rule(
    rule_id: int,
    payload: RiskRuleUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    rule = await _get_rule(db, current_user.tenant_id, rule_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="risk_rule.update",
        resource_type="risk_rule",
        resource_id=rule.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(RiskRuleOut.model_validate(rule).model_dump(mode="json"))


@router.delete("/rules/{rule_id}", summary="删除风控规则")
async def delete_rule(
    rule_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    rule = await _get_rule(db, current_user.tenant_id, rule_id)
    await db.delete(rule)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="risk_rule.delete",
        resource_type="risk_rule",
        resource_id=rule_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/check", summary="内容风控检查")
async def check(
    payload: RiskCheckRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await evaluate_risk(
        db,
        current_user.tenant_id,
        payload.content,
        payload.category,
    )
    record = RiskCheck(
        tenant_id=current_user.tenant_id,
        content=payload.content,
        category=payload.category,
        decision=result["decision"],
        score=result["score"],
        matched_rules=result["matched_rules"],
        created_by=current_user.id,
    )
    db.add(record)
    await db.flush()
    return success(RiskCheckOut.model_validate(record).model_dump(mode="json"))


@router.get("/checks", summary="风控检查记录")
async def list_checks(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    decision: str | None = None,
):
    conditions = [RiskCheck.tenant_id == current_user.tenant_id]
    if decision:
        conditions.append(RiskCheck.decision == decision)
    stmt = select(RiskCheck).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(RiskCheck.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [RiskCheckOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )
