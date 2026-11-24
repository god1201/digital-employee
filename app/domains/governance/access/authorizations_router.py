from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.crypto import encrypt_secret
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.access.models import Authorization
from app.domains.governance.access.schemas import (
    AuthorizationCreate,
    AuthorizationOut,
    AuthorizationUpdate,
)
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.employees.service import ensure_employee_exists

router = APIRouter(prefix="/authorizations", tags=["授权与准入"])


async def _get_authorization(db: DbSession, tenant_id: int, authorization_id: int) -> Authorization:
    record = await db.scalar(
        select(Authorization).where(
            Authorization.id == authorization_id,
            Authorization.tenant_id == tenant_id,
        )
    )
    if record is None:
        raise NotFoundError("授权记录不存在")
    return record


@router.get("", summary="授权记录列表")
async def list_authorizations(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    system_code: str | None = None,
    status: str | None = None,
):
    conditions = [Authorization.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(Authorization.employee_id == employee_id)
    if system_code:
        conditions.append(Authorization.system_code == system_code)
    if status:
        conditions.append(Authorization.status == status)

    stmt = select(Authorization).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(Authorization.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [AuthorizationOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="登记授权（凭证加密存储）")
async def create_authorization(
    payload: AuthorizationCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await ensure_employee_exists(db, current_user.tenant_id, payload.employee_id)

    data = payload.model_dump(exclude={"credential"})
    record = Authorization(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        credential_encrypted=encrypt_secret(payload.credential) if payload.credential else None,
        **data,
    )
    db.add(record)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=record.employee_id,
        action="authorization.create",
        resource_type="authorization",
        resource_id=record.id,
        detail={"system_code": record.system_code, "access_type": record.access_type},
        ip_address=client_ip(request),
    )
    return success(AuthorizationOut.model_validate(record).model_dump(mode="json"))


@router.patch("/{authorization_id}", summary="更新授权")
async def update_authorization(
    authorization_id: int,
    payload: AuthorizationUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    record = await _get_authorization(db, current_user.tenant_id, authorization_id)
    changes = payload.model_dump(exclude_unset=True)
    credential_provided = "credential" in changes
    credential = changes.pop("credential", None)

    if "employee_id" in changes:
        await ensure_employee_exists(db, current_user.tenant_id, changes["employee_id"])
    for field, value in changes.items():
        setattr(record, field, value)
    if credential_provided:
        record.credential_encrypted = encrypt_secret(credential) if credential else None

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=record.employee_id,
        action="authorization.update",
        resource_type="authorization",
        resource_id=record.id,
        detail={"fields": sorted(changes.keys()), "credential_updated": credential_provided},
        ip_address=client_ip(request),
    )
    return success(AuthorizationOut.model_validate(record).model_dump(mode="json"))


@router.delete("/{authorization_id}", summary="删除授权")
async def delete_authorization(
    authorization_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    record = await _get_authorization(db, current_user.tenant_id, authorization_id)
    await db.delete(record)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="authorization.delete",
        resource_type="authorization",
        resource_id=authorization_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")
