from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.access.models import AccessRule
from app.domains.governance.access.schemas import (
    AccessCheckRequest,
    AccessCheckResult,
    AccessRuleCreate,
    AccessRuleOut,
    AccessRuleUpdate,
)
from app.domains.governance.access.service import evaluate_access
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.employees.service import ensure_employee_exists

router = APIRouter(prefix="/access-rules", tags=["授权与准入"])


async def _get_rule(db: DbSession, tenant_id: int, rule_id: int) -> AccessRule:
    rule = await db.scalar(
        select(AccessRule).where(AccessRule.id == rule_id, AccessRule.tenant_id == tenant_id)
    )
    if rule is None:
        raise NotFoundError("访问规则不存在")
    return rule


@router.get("", summary="访问规则列表")
async def list_rules(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    system_code: str | None = None,
    enabled: bool | None = None,
):
    conditions = [AccessRule.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(AccessRule.employee_id == employee_id)
    if system_code:
        conditions.append(AccessRule.system_code == system_code)
    if enabled is not None:
        conditions.append(AccessRule.enabled.is_(enabled))

    stmt = select(AccessRule).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AccessRule.priority.desc(), AccessRule.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [AccessRuleOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建访问规则")
async def create_rule(
    payload: AccessRuleCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await ensure_employee_exists(db, current_user.tenant_id, payload.employee_id)
    rule = AccessRule(
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
        employee_id=rule.employee_id,
        action="access_rule.create",
        resource_type="access_rule",
        resource_id=rule.id,
        detail={"path": rule.path_pattern, "effect": rule.effect, "priority": rule.priority},
        ip_address=client_ip(request),
    )
    return success(AccessRuleOut.model_validate(rule).model_dump(mode="json"))


@router.patch("/{rule_id}", summary="更新访问规则")
async def update_rule(
    rule_id: int,
    payload: AccessRuleUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    rule = await _get_rule(db, current_user.tenant_id, rule_id)
    changes = payload.model_dump(exclude_unset=True)
    if "employee_id" in changes:
        await ensure_employee_exists(db, current_user.tenant_id, changes["employee_id"])
    for field, value in changes.items():
        setattr(rule, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="access_rule.update",
        resource_type="access_rule",
        resource_id=rule.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(AccessRuleOut.model_validate(rule).model_dump(mode="json"))


@router.delete("/{rule_id}", summary="删除访问规则")
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
        action="access_rule.delete",
        resource_type="access_rule",
        resource_id=rule_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/check", summary="模拟访问检查（默认拒绝）")
async def check_access(
    payload: AccessCheckRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    await ensure_employee_exists(db, current_user.tenant_id, payload.employee_id)
    decision = await evaluate_access(
        db,
        current_user.tenant_id,
        employee_id=payload.employee_id,
        method=payload.method,
        path=payload.path,
        system_code=payload.system_code,
    )
    result = AccessCheckResult(
        allowed=decision.allowed,
        effect=decision.effect,
        rule_id=decision.rule_id,
        reason=decision.reason,
    )
    return success(result.model_dump())
