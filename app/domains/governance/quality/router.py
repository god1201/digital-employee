from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.governance.quality.models import InspectionRecord, InspectionRule
from app.domains.governance.quality.schemas import (
    InspectionCheckRequest,
    InspectionRecordOut,
    InspectionReviewRequest,
    InspectionRuleCreate,
    InspectionRuleOut,
    InspectionRuleUpdate,
)
from app.domains.governance.quality.service import evaluate_inspection

router = APIRouter(prefix="/qa", tags=["质检"])


async def _get_rule(db: DbSession, tenant_id: int, rule_id: int) -> InspectionRule:
    rule = await db.scalar(
        select(InspectionRule).where(
            InspectionRule.id == rule_id,
            InspectionRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise NotFoundError("质检规则不存在")
    return rule


async def _get_record(db: DbSession, tenant_id: int, record_id: int) -> InspectionRecord:
    record = await db.scalar(
        select(InspectionRecord).where(
            InspectionRecord.id == record_id,
            InspectionRecord.tenant_id == tenant_id,
        )
    )
    if record is None:
        raise NotFoundError("质检记录不存在")
    return record


@router.get("/rules", summary="质检规则列表")
async def list_rules(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    enabled: bool | None = None,
):
    conditions = [InspectionRule.tenant_id == current_user.tenant_id]
    if enabled is not None:
        conditions.append(InspectionRule.enabled.is_(enabled))

    stmt = select(InspectionRule).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(InspectionRule.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [InspectionRuleOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/rules", summary="创建质检规则")
async def create_rule(
    payload: InspectionRuleCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    exists = await db.scalar(
        select(InspectionRule.id).where(
            InspectionRule.tenant_id == current_user.tenant_id,
            InspectionRule.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("质检规则编码已存在")

    rule = InspectionRule(
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
        action="inspection_rule.create",
        resource_type="inspection_rule",
        resource_id=rule.id,
        detail={"code": rule.code, "type": rule.rule_type},
        ip_address=client_ip(request),
    )
    return success(InspectionRuleOut.model_validate(rule).model_dump(mode="json"))


@router.patch("/rules/{rule_id}", summary="更新质检规则")
async def update_rule(
    rule_id: int,
    payload: InspectionRuleUpdate,
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
        action="inspection_rule.update",
        resource_type="inspection_rule",
        resource_id=rule.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(InspectionRuleOut.model_validate(rule).model_dump(mode="json"))


@router.delete("/rules/{rule_id}", summary="删除质检规则")
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
        action="inspection_rule.delete",
        resource_type="inspection_rule",
        resource_id=rule_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/checks", summary="执行质检")
async def create_check(
    payload: InspectionCheckRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    conditions = [
        InspectionRule.tenant_id == current_user.tenant_id,
        InspectionRule.enabled.is_(True),
    ]
    if payload.category:
        conditions.append(InspectionRule.category == payload.category)

    rules = list((await db.scalars(select(InspectionRule).where(*conditions))).all())
    result = evaluate_inspection(rules, payload.content)
    record = InspectionRecord(
        tenant_id=current_user.tenant_id,
        title=payload.title,
        content=payload.content,
        category=payload.category or "content",
        score=result["score"],
        grade=result["grade"],
        decision=result["decision"],
        rule_results=result["rule_results"],
        created_by=current_user.id,
    )
    db.add(record)
    await db.flush()
    return success(InspectionRecordOut.model_validate(record).model_dump(mode="json"))


@router.get("/checks", summary="质检记录列表")
async def list_checks(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    decision: str | None = None,
    status: str | None = None,
):
    conditions = [InspectionRecord.tenant_id == current_user.tenant_id]
    if decision:
        conditions.append(InspectionRecord.decision == decision)
    if status:
        conditions.append(InspectionRecord.status == status)

    stmt = select(InspectionRecord).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(InspectionRecord.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [InspectionRecordOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.get("/checks/{record_id}", summary="质检详情")
async def get_check(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    record = await _get_record(db, current_user.tenant_id, record_id)
    return success(InspectionRecordOut.model_validate(record).model_dump(mode="json"))


@router.post("/checks/{record_id}/review", summary="人工复核质检结果")
async def review_check(
    record_id: int,
    payload: InspectionReviewRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    record = await _get_record(db, current_user.tenant_id, record_id)
    record.decision = payload.decision
    record.status = "reviewed"
    record.review_comment = payload.comment
    record.reviewed_by = current_user.id
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="inspection.review",
        resource_type="inspection_record",
        resource_id=record.id,
        detail={"decision": payload.decision, "comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success(InspectionRecordOut.model_validate(record).model_dump(mode="json"))
