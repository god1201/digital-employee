from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.collaboration.models import CollaborationRun
from app.domains.workforce.collaboration.schemas import (
    CollaborationCreate,
    CollaborationOut,
)
from app.domains.workforce.collaboration.service import (
    create_collaboration,
    get_collaboration,
    sync_collaboration,
)
from app.worker.enqueue import enqueue_task

router = APIRouter(prefix="/collaborations", tags=["多员工协作"])


@router.get("", summary="协作会话列表")
async def list_collaborations(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
):
    conditions = [CollaborationRun.tenant_id == current_user.tenant_id]
    if status:
        conditions.append(CollaborationRun.status == status)
    stmt = select(CollaborationRun).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(CollaborationRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    for item in items:
        await sync_collaboration(db, item)
    return paged(
        [CollaborationOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="发起多员工协作")
async def start_collaboration(
    payload: CollaborationCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    run = await create_collaboration(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=run.owner_employee_id,
        action="collaboration.create",
        resource_type="collaboration_run",
        resource_id=run.id,
        detail={
            "parent_instance_id": run.parent_instance_id,
            "participants": [item["employee_id"] for item in run.participants],
        },
        ip_address=client_ip(request),
    )
    # 先提交，Celery 模式下才能立即投递
    await db.commit()
    if settings.use_celery and run.parent_instance_id:
        enqueue_task(run.parent_instance_id, 0)
    return success(CollaborationOut.model_validate(run).model_dump(mode="json"))


@router.get("/{collaboration_id}", summary="协作会话详情")
async def get_collaboration_detail(
    collaboration_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    run = await get_collaboration(db, current_user.tenant_id, collaboration_id)
    return success(CollaborationOut.model_validate(run).model_dump(mode="json"))
