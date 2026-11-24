from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance.audit.models import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    tenant_id: int,
    action: str,
    user_id: int | None = None,
    employee_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
    trace_id: str | None = None,
) -> AuditLog:
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        employee_id=employee_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail or {},
        ip_address=ip_address,
        trace_id=trace_id,
    )
    db.add(log)
    await db.flush()
    return log
