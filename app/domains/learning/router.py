from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.domains.learning.models import FeedbackSample
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workflows.tasks.schemas import FeedbackCreate, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["反馈样本"])


@router.post("", summary="提交人工反馈（bad case 入库）")
async def create_feedback(
    payload: FeedbackCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.instance_id is not None:
        instance = await db.scalar(
            select(TaskInstance).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == current_user.tenant_id,
            )
        )
        if instance is None:
            raise NotFoundError("任务实例不存在")

    sample = FeedbackSample(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(sample)
    await db.flush()
    return success(FeedbackOut.model_validate(sample).model_dump(mode="json"))


@router.get("", summary="反馈样本列表")
async def list_feedback(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    verdict: str | None = None,
    status: str | None = None,
):
    conditions = [FeedbackSample.tenant_id == current_user.tenant_id]
    if verdict:
        conditions.append(FeedbackSample.verdict == verdict)
    if status:
        conditions.append(FeedbackSample.status == status)

    stmt = select(FeedbackSample).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(FeedbackSample.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [FeedbackOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )
