from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.experts import (
    candidate_trajectories,
    distill_trajectory,
)
from app.domains.learning.models import LearningQuestion, WeeklyReview
from app.domains.learning.questions import (
    answer_question,
    budget_info,
    create_question,
)
from app.domains.learning.reviews import build_weekly_review
from app.domains.learning.rollout import (
    applicable_artifacts,
    build_artifacts_context,
)
from app.domains.learning.scheduler import (
    deliver_weekly_review,
    run_daily_learning_batch,
    run_weekly_review_batch,
    scheduler_status,
)
from app.domains.learning.schemas import (
    ArtifactOut,
    ExpertTrajectoryDistillRequest,
    LearningQuestionAnswer,
    LearningQuestionCreate,
    LearningQuestionOut,
    WeeklyReviewBatchGenerate,
    WeeklyReviewGenerate,
    WeeklyReviewOut,
)
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.service import get_employee

router = APIRouter(tags=["P2 学习增强"])


async def _get_question(
    db: DbSession, tenant_id: int, question_id: int
) -> LearningQuestion:
    question = await db.scalar(
        select(LearningQuestion).where(
            LearningQuestion.id == question_id,
            LearningQuestion.tenant_id == tenant_id,
        )
    )
    if question is None:
        raise NotFoundError("提问不存在")
    return question


@router.get("/learning-questions", summary="主动学习提问列表")
async def list_questions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    status: str | None = None,
):
    conditions = [LearningQuestion.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(LearningQuestion.employee_id == employee_id)
    if status:
        conditions.append(LearningQuestion.status == status)

    stmt = select(LearningQuestion).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(LearningQuestion.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [LearningQuestionOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/learning-questions", summary="员工主动提问（受每日预算约束）")
async def ask_question(
    payload: LearningQuestionCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, payload.employee_id)
    if payload.instance_id is not None:
        instance = await db.scalar(
            select(TaskInstance.id).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == current_user.tenant_id,
            )
        )
        if instance is None:
            raise NotFoundError("任务实例不存在")

    question, budget = await create_question(
        db, current_user.tenant_id, employee, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="learning_question.create",
        resource_type="learning_question",
        resource_id=question.id,
        detail={"remaining": budget["remaining"]},
        ip_address=client_ip(request),
    )
    return success(
        {
            "question": LearningQuestionOut.model_validate(question).model_dump(mode="json"),
            "budget": budget,
        }
    )


@router.post("/learning-questions/{question_id}/answer", summary="回答问题并生成学习工件")
async def answer(
    question_id: int,
    payload: LearningQuestionAnswer,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    question = await _get_question(db, current_user.tenant_id, question_id)
    artifact = await answer_question(db, question, payload, user_id=current_user.id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=question.employee_id,
        action="learning_question.answer",
        resource_type="learning_question",
        resource_id=question.id,
        detail={"answer": payload.answer, "artifact_id": artifact.id},
        ip_address=client_ip(request),
    )
    return success(
        {
            "question": LearningQuestionOut.model_validate(question).model_dump(mode="json"),
            "artifact": ArtifactOut.model_validate(artifact).model_dump(mode="json"),
        }
    )


@router.post("/learning-questions/{question_id}/dismiss", summary="忽略提问")
async def dismiss(
    question_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    question = await _get_question(db, current_user.tenant_id, question_id)
    question.status = "dismissed"
    await db.flush()
    return success(None, "提问已忽略")


@router.get(
    "/digital-employees/{employee_id}/learning-budget",
    summary="主动学习预算",
)
async def learning_budget(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(await budget_info(db, employee))


@router.get("/learning/scheduler/status", summary="学习节奏调度状态")
async def learning_scheduler_status(current_user: CurrentUser):
    return success({"tenant_id": current_user.tenant_id, **scheduler_status()})


@router.post(
    "/learning/jobs/daily-batch",
    summary="立即执行日结批量归因与自动提问",
)
async def run_daily_batch(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    lookback_hours: int | None = Query(None, ge=1, le=720),
):
    result = await run_daily_learning_batch(
        db,
        lookback_hours=lookback_hours,
        tenant_id=current_user.tenant_id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="learning.daily_batch",
        resource_type="learning_job",
        detail={
            "attributed": result["attribution"]["attributed"],
            "questions": result["questions"]["created"],
            "lookback_hours": result["lookback_hours"],
        },
        ip_address=client_ip(request),
    )
    return success(result)


@router.post("/weekly-reviews/generate", summary="生成成长周报")
async def generate_review(
    payload: WeeklyReviewGenerate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    review = await build_weekly_review(
        db,
        current_user.tenant_id,
        payload.employee_id,
        week_start=payload.week_start,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="weekly_review.generate",
        resource_type="weekly_review",
        resource_id=review.id,
        detail={"period_start": review.period_start.isoformat()},
        ip_address=client_ip(request),
    )
    return success(WeeklyReviewOut.model_validate(review).model_dump(mode="json"))


@router.post(
    "/weekly-reviews/generate-batch",
    summary="批量生成周报（默认上一自然周）",
)
async def generate_review_batch(
    payload: WeeklyReviewBatchGenerate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await run_weekly_review_batch(
        db,
        tenant_id=current_user.tenant_id,
        week_start=payload.week_start,
        force=payload.force,
        deliver=payload.deliver,
        previous_week=True,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="weekly_review.generate_batch",
        resource_type="weekly_review",
        detail={
            "generated": result["generated"],
            "skipped": result["skipped"],
            "period_start": result["period_start"],
        },
        ip_address=client_ip(request),
    )
    return success(result)


@router.get("/weekly-reviews", summary="成长周报列表")
async def list_reviews(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
):
    conditions = [WeeklyReview.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(WeeklyReview.employee_id == employee_id)
    stmt = select(WeeklyReview).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(WeeklyReview.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [WeeklyReviewOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.get("/weekly-reviews/{review_id}", summary="成长周报详情")
async def get_review(
    review_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    review = await db.scalar(
        select(WeeklyReview).where(
            WeeklyReview.id == review_id,
            WeeklyReview.tenant_id == current_user.tenant_id,
        )
    )
    if review is None:
        raise NotFoundError("周报不存在")
    return success(WeeklyReviewOut.model_validate(review).model_dump(mode="json"))


@router.post("/weekly-reviews/{review_id}/deliver", summary="投递周报到 webhook")
async def deliver_review(
    review_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    review = await db.scalar(
        select(WeeklyReview).where(
            WeeklyReview.id == review_id,
            WeeklyReview.tenant_id == current_user.tenant_id,
        )
    )
    if review is None:
        raise NotFoundError("周报不存在")
    delivery = await deliver_weekly_review(db, review)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=review.employee_id,
        action="weekly_review.deliver",
        resource_type="weekly_review",
        resource_id=review.id,
        detail={"delivered": delivery.get("delivered"), "url": delivery.get("url")},
        ip_address=client_ip(request),
    )
    return success(
        {
            "review": WeeklyReviewOut.model_validate(review).model_dump(mode="json"),
            "delivery": delivery,
        }
    )


@router.get(
    "/digital-employees/{employee_id}/artifacts/context",
    summary="查看将注入提示词的生效工件上下文",
)
async def employee_artifact_context(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    artifacts = await applicable_artifacts(
        db, current_user.tenant_id, employee_id
    )
    return success(
        {
            "employee_id": employee_id,
            "count": len(artifacts),
            "context": build_artifacts_context(artifacts),
            "items": [
                {
                    "id": item.id,
                    "version": item.version,
                    "status": item.status,
                    "scope": item.scope,
                    "target_layer": item.target_layer,
                    "proposal": item.proposal,
                }
                for item in artifacts
            ],
        }
    )


@router.get("/expert-trajectories/candidates", summary="专家轨迹候选")
async def expert_candidates(
    db: DbSession,
    current_user: CurrentUser,
    employee_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    items = await candidate_trajectories(
        db, current_user.tenant_id, employee_id=employee_id, limit=limit
    )
    return success(items)


@router.post("/expert-trajectories/distill", summary="蒸馏专家轨迹为学习工件")
async def distill(
    payload: ExpertTrajectoryDistillRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await distill_trajectory(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="expert_trajectory.distill",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"instance_id": payload.instance_id},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))
