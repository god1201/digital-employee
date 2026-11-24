from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.models import PreferenceMemory
from app.domains.learning.schemas import (
    PreferenceOut,
    PreferenceUpdate,
    PreferenceUpsert,
)
from app.domains.learning.service import (
    active_preferences,
    build_preference_context,
    upsert_preference,
)
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/preferences", tags=["偏好记忆"])


async def _get_preference(
    db: DbSession, tenant_id: int, preference_id: int
) -> PreferenceMemory:
    preference = await db.scalar(
        select(PreferenceMemory).where(
            PreferenceMemory.id == preference_id,
            PreferenceMemory.tenant_id == tenant_id,
        )
    )
    if preference is None:
        raise NotFoundError("偏好记忆不存在")
    return preference


@router.get("", summary="偏好记忆列表")
async def list_preferences(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    employee_id: int | None = None,
    scope: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
):
    conditions = [PreferenceMemory.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(PreferenceMemory.employee_id == employee_id)
    if scope:
        conditions.append(PreferenceMemory.scope == scope)
    if status:
        conditions.append(PreferenceMemory.status == status)
    if keyword:
        conditions.append(
            or_(
                PreferenceMemory.key.ilike(f"%{keyword}%"),
                PreferenceMemory.value.ilike(f"%{keyword}%"),
            )
        )

    stmt = select(PreferenceMemory).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(PreferenceMemory.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [PreferenceOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="写入偏好记忆（实时生效）")
async def save_preference(
    payload: PreferenceUpsert,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, payload.employee_id)
    preference, created = await upsert_preference(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="preference.create" if created else "preference.update",
        resource_type="preference_memory",
        resource_id=preference.id,
        detail={"key": preference.key, "scope": preference.scope},
        ip_address=client_ip(request),
    )
    return success(PreferenceOut.model_validate(preference).model_dump(mode="json"))


@router.patch("/{preference_id}", summary="更新偏好记忆")
async def update_preference(
    preference_id: int,
    payload: PreferenceUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    preference = await _get_preference(db, current_user.tenant_id, preference_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(preference, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=preference.employee_id,
        action="preference.update",
        resource_type="preference_memory",
        resource_id=preference.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(PreferenceOut.model_validate(preference).model_dump(mode="json"))


@router.delete("/{preference_id}", summary="遗忘偏好记忆")
async def archive_preference(
    preference_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    preference = await _get_preference(db, current_user.tenant_id, preference_id)
    preference.status = "archived"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=preference.employee_id,
        action="preference.archive",
        resource_type="preference_memory",
        resource_id=preference.id,
        detail={"key": preference.key},
        ip_address=client_ip(request),
    )
    return success(None, "偏好记忆已遗忘")


@router.get("/context/{employee_id}", summary="查看将注入提示词的偏好上下文")
async def preference_context(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    preferences = await active_preferences(db, current_user.tenant_id, employee_id)
    return success(
        {
            "employee_id": employee_id,
            "count": len(preferences),
            "context": build_preference_context(preferences),
        }
    )
