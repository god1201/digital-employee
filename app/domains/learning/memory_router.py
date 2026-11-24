from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.memory import compress_episodes, memory_overview
from app.domains.learning.schemas import ArtifactOut, MemoryCompressRequest
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/digital-employees", tags=["分层记忆"])


@router.get("/{employee_id}/memories", summary="分层记忆总览")
async def read_memories(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    layer: str | None = None,
    limit: int = Query(20, ge=1, le=200),
):
    await get_employee(db, current_user.tenant_id, employee_id)
    return success(
        await memory_overview(
            db,
            current_user.tenant_id,
            employee_id,
            layer=layer,
            limit=limit,
        )
    )


@router.post(
    "/{employee_id}/memories/compress",
    summary="压缩情景记忆为学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def compress_memory(
    employee_id: int,
    payload: MemoryCompressRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    artifact = await compress_episodes(
        db,
        current_user.tenant_id,
        employee_id,
        before_days=payload.before_days,
        limit=payload.limit,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="memory.compress",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"before_days": payload.before_days, "limit": payload.limit},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))
