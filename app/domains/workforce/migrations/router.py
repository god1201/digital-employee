from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.migrations.models import CapabilityMigration
from app.domains.workforce.migrations.schemas import (
    CapabilityMigrationCreate,
    CapabilityMigrationOut,
)
from app.domains.workforce.migrations.service import migrate_capabilities

router = APIRouter(prefix="/capability-migrations", tags=["能力迁移"])


@router.get("", summary="能力迁移记录")
async def list_migrations(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    source_employee_id: int | None = None,
    target_employee_id: int | None = None,
):
    conditions = [CapabilityMigration.tenant_id == current_user.tenant_id]
    if source_employee_id is not None:
        conditions.append(
            CapabilityMigration.source_employee_id == source_employee_id
        )
    if target_employee_id is not None:
        conditions.append(
            CapabilityMigration.target_employee_id == target_employee_id
        )
    stmt = select(CapabilityMigration).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(CapabilityMigration.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [
            CapabilityMigrationOut.model_validate(item).model_dump(mode="json")
            for item in items
        ],
        total,
        page,
        page_size,
    )


@router.post(
    "",
    summary="跨员工迁移能力",
    dependencies=[Depends(get_current_admin)],
)
async def create_migration(
    payload: CapabilityMigrationCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    migration = await migrate_capabilities(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.target_employee_id,
        action="capability.migrate",
        resource_type="capability_migration",
        resource_id=migration.id,
        detail={
            "source_employee_id": payload.source_employee_id,
            "components": payload.components,
            "dry_run": payload.dry_run,
            "status": migration.status,
        },
        ip_address=client_ip(request),
    )
    return success(
        CapabilityMigrationOut.model_validate(migration).model_dump(mode="json")
    )


@router.get("/{migration_id}", summary="能力迁移详情")
async def get_migration(
    migration_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    migration = await db.scalar(
        select(CapabilityMigration).where(
            CapabilityMigration.id == migration_id,
            CapabilityMigration.tenant_id == current_user.tenant_id,
        )
    )
    if migration is None:
        raise NotFoundError("迁移记录不存在")
    return success(
        CapabilityMigrationOut.model_validate(migration).model_dump(mode="json")
    )
