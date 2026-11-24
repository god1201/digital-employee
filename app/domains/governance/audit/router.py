from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import CurrentAdmin, DbSession
from app.core.response import paged
from app.domains.governance.audit.models import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["审计"])


@router.get("", summary="审计日志列表（管理员）")
async def list_audit_logs(
    db: DbSession,
    current_admin: CurrentAdmin,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    action: str | None = None,
    resource_type: str | None = None,
    employee_id: int | None = None,
):
    conditions = [AuditLog.tenant_id == current_admin.tenant_id]
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if employee_id is not None:
        conditions.append(AuditLog.employee_id == employee_id)

    stmt = select(AuditLog).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    data = [
        {
            "id": item.id,
            "user_id": item.user_id,
            "employee_id": item.employee_id,
            "action": item.action,
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "detail": item.detail,
            "ip_address": item.ip_address,
            "trace_id": item.trace_id,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]
    return paged(data, total, page, page_size)
