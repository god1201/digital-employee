from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.core.response import success
from app.domains.operations.service import compute_overview, compute_queue, list_workers

router = APIRouter(prefix="/monitoring", tags=["监控"])


@router.get("/overview", summary="任务总览与指标")
async def overview(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(7, ge=1, le=90),
):
    return success(await compute_overview(db, current_user.tenant_id, days))


@router.get("/workers", summary="Worker 心跳与存活状态")
async def workers(db: DbSession, current_user: CurrentUser):
    return success(await list_workers(db))


@router.get("/queue", summary="任务队列积压")
async def queue(db: DbSession, current_user: CurrentUser):
    return success(await compute_queue(db, current_user.tenant_id))
