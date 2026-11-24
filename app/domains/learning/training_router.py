from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.core.deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    callback_token_matches,
    get_current_admin,
)
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.models import PreferencePair, TrainingJob
from app.domains.learning.schemas import (
    PreferenceCollectRequest,
    PreferenceCollectResult,
    PreferenceExportRequest,
    PreferenceExportResult,
    PreferencePairOut,
    TrainingJobCreate,
    TrainingJobOut,
    TrainingJobStatusUpdate,
)
from app.domains.learning.training import (
    apply_job_status,
    collect_preference_pairs,
    create_training_job,
    dispatch_training_job,
    export_pairs,
)
from app.domains.workforce.employees.service import get_employee

router = APIRouter(tags=["DPO 训练数据"])


@router.get("/preference-pairs", summary="偏好对列表")
async def list_pairs(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    source_type: str | None = None,
    status: str | None = None,
):
    conditions = [PreferencePair.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(PreferencePair.employee_id == employee_id)
    if source_type:
        conditions.append(PreferencePair.source_type == source_type)
    if status:
        conditions.append(PreferencePair.status == status)
    stmt = select(PreferencePair).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(PreferencePair.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [PreferencePairOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/preference-pairs/collect", summary="从接管/评估/反馈采集偏好对")
async def collect(
    payload: PreferenceCollectRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    result = await collect_preference_pairs(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="preference.collect",
        resource_type="preference_pair",
        detail={"created": result["created"], "skipped": result["skipped"]},
        ip_address=client_ip(request),
    )
    return success(
        PreferenceCollectResult(
            created=result["created"],
            skipped=result["skipped"],
            pairs=[
                PreferencePairOut.model_validate(item) for item in result["pairs"]
            ],
        ).model_dump(mode="json")
    )


@router.post("/preference-pairs/export", summary="导出 DPO JSONL")
async def export(
    payload: PreferenceExportRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await export_pairs(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="preference.export",
        resource_type="preference_pair",
        detail={"path": result["path"], "count": result["count"]},
        ip_address=client_ip(request),
    )
    return success(PreferenceExportResult(**result).model_dump(mode="json"))


@router.patch("/preference-pairs/{pair_id}/archive", summary="归档偏好对")
async def archive_pair(
    pair_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    pair = await db.scalar(
        select(PreferencePair).where(
            PreferencePair.id == pair_id,
            PreferencePair.tenant_id == current_user.tenant_id,
        )
    )
    if pair is None:
        raise NotFoundError("偏好对不存在")
    pair.status = "archived"
    await db.flush()
    return success(None, "偏好对已归档")


@router.get("/training-jobs", summary="训练任务列表")
async def list_jobs(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    status: str | None = None,
):
    conditions = [TrainingJob.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(TrainingJob.employee_id == employee_id)
    if status:
        conditions.append(TrainingJob.status == status)
    stmt = select(TrainingJob).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(TrainingJob.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TrainingJobOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post(
    "/training-jobs",
    summary="创建训练任务（数据集台账）",
    dependencies=[Depends(get_current_admin)],
)
async def create_job(
    payload: TrainingJobCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    job = await create_training_job(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=job.employee_id,
        action="training_job.create",
        resource_type="training_job",
        resource_id=job.id,
        detail={"method": job.method, "dataset": job.dataset_path},
        ip_address=client_ip(request),
    )
    return success(TrainingJobOut.model_validate(job).model_dump(mode="json"))


@router.get("/training-jobs/{job_id}", summary="训练任务详情")
async def get_job(
    job_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await db.scalar(
        select(TrainingJob).where(
            TrainingJob.id == job_id,
            TrainingJob.tenant_id == current_user.tenant_id,
        )
    )
    if job is None:
        raise NotFoundError("训练任务不存在")
    return success(TrainingJobOut.model_validate(job).model_dump(mode="json"))


@router.post(
    "/training-jobs/{job_id}/dispatch",
    summary="派发训练任务到外部 trainer",
    dependencies=[Depends(get_current_admin)],
)
async def dispatch_job(
    job_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await db.scalar(
        select(TrainingJob).where(
            TrainingJob.id == job_id,
            TrainingJob.tenant_id == current_user.tenant_id,
        )
    )
    if job is None:
        raise NotFoundError("训练任务不存在")
    job = await dispatch_training_job(db, job)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=job.employee_id,
        action="training_job.dispatch",
        resource_type="training_job",
        resource_id=job.id,
        detail={"metrics": job.metrics},
        ip_address=client_ip(request),
    )
    return success(TrainingJobOut.model_validate(job).model_dump(mode="json"))


@router.post("/training-jobs/{job_id}/status", summary="外部 trainer 回调状态")
async def update_job_status(
    job_id: int,
    payload: TrainingJobStatusUpdate,
    request: Request,
    db: DbSession,
    actor: OptionalUser,
):
    job = await db.get(TrainingJob, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    provided = request.headers.get("X-Training-Token")
    expected_hash = (job.config or {}).get("callback_token_hash")
    authorized = (
        actor is not None and actor.tenant_id == job.tenant_id
    ) or callback_token_matches(provided, expected_hash)
    if not authorized:
        raise UnauthorizedError("训练回调需要有效 JWT 或任务回调令牌")
    tenant_id = job.tenant_id
    apply_job_status(job, payload)
    await db.flush()
    await record_audit(
        db,
        tenant_id=tenant_id,
        user_id=actor.id if actor is not None else None,
        employee_id=job.employee_id,
        action="training_job.status",
        resource_type="training_job",
        resource_id=job.id,
        detail={
            "status": payload.status,
            "metrics": payload.metrics,
            "actor": "training_provider" if actor is None else "user",
        },
        ip_address=client_ip(request),
    )
    return success(TrainingJobOut.model_validate(job).model_dump(mode="json"))
