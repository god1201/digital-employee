"""主动学习：受每日预算约束的结构化提问与回答入库。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.exceptions import BadRequestError
from app.domains.learning.models import LearningArtifact, LearningQuestion
from app.domains.learning.schemas import (
    LearningQuestionAnswer,
    LearningQuestionCreate,
)

DEFAULT_DAILY_BUDGET = 3


def daily_budget(employee) -> int:
    config = employee.config or {}
    try:
        value = int(config.get("active_learning_budget", DEFAULT_DAILY_BUDGET))
    except (TypeError, ValueError):
        value = DEFAULT_DAILY_BUDGET
    return max(0, value)


async def used_today(db: AsyncSession, tenant_id: int, employee_id: int) -> int:
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.count(LearningQuestion.id)).where(
                LearningQuestion.tenant_id == tenant_id,
                LearningQuestion.employee_id == employee_id,
                LearningQuestion.created_at >= today,
            )
        )
        or 0
    )


async def budget_info(db: AsyncSession, employee) -> dict:
    limit = daily_budget(employee)
    used = await used_today(db, employee.tenant_id, employee.id)
    return {
        "employee_id": employee.id,
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
    }


async def create_question(
    db: AsyncSession,
    tenant_id: int,
    employee,
    payload: LearningQuestionCreate,
    *,
    user_id: int | None = None,
) -> tuple[LearningQuestion, dict]:
    info = await budget_info(db, employee)
    if info["remaining"] <= 0:
        raise BadRequestError(
            f"今日主动提问预算已用完（{info['limit']} 次），明天再问或调高预算"
        )
    if not payload.options:
        raise BadRequestError("主动提问必须提供选项，便于结构化入库")

    question = LearningQuestion(
        tenant_id=tenant_id,
        employee_id=employee.id,
        instance_id=payload.instance_id,
        question=payload.question,
        options=payload.options,
        default_option=payload.default_option,
        expires_at=payload.expires_at,
        created_by=user_id,
    )
    db.add(question)
    await db.flush()
    info = await budget_info(db, employee)
    return question, info


async def answer_question(
    db: AsyncSession,
    question: LearningQuestion,
    payload: LearningQuestionAnswer,
    *,
    user_id: int | None = None,
) -> LearningArtifact:
    if question.status != "open":
        raise BadRequestError(f"提问当前状态不可回答: {question.status}")

    question.status = "answered"
    question.answer = payload.answer
    question.answer_note = payload.note
    question.answered_by = user_id
    question.answered_at = utcnow()

    artifact = LearningArtifact(
        tenant_id=question.tenant_id,
        employee_id=question.employee_id,
        source={
            "type": "active_learning",
            "question_id": question.id,
            "instance_id": question.instance_id,
        },
        attribution="主动学习回答",
        target_layer="semantic_memory",
        proposal={
            "action": "record_answer",
            "question": question.question,
            "options": question.options,
            "default_option": question.default_option,
            "answer": payload.answer,
            "note": payload.note,
        },
        evidence=[
            f"主动提问：{question.question}",
            f"人工回答：{payload.answer}",
            *([payload.note] if payload.note else []),
        ],
        eval_result={},
        risk="low",
        scope="personal",
        status="pending_approval",
        rollout={"question_id": question.id},
        created_by=user_id,
    )
    db.add(artifact)
    await db.flush()
    question.artifact_id = artifact.id
    await db.flush()
    return artifact
