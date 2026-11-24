"""成长周报：任务、接管、错误归因、学习工件与下周建议。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.domains.learning.models import (
    EmployeeTrial,
    FailureAttribution,
    ImplicitSignal,
    InterventionDelta,
    LearningArtifact,
    LearningQuestion,
    OutcomeEvent,
    WeeklyReview,
)
from app.domains.workflows.tasks.models import TaskInstance

CATEGORY_LABELS = {
    "knowledge_missing": "知识缺失",
    "retrieval_miss": "检索未召回",
    "tool_misuse": "工具用错",
    "planning_error": "规划错误",
    "style_mismatch": "风格不符",
    "permission_violation": "越权/合规",
    "intent_misunderstanding": "理解偏差",
    "unknown": "未知",
}

RECOMMENDATIONS = {
    "knowledge_missing": "补充知识库文档并重建索引，优先处理 Top1 缺口",
    "retrieval_miss": "调整分块、同义词与 Rerank，不要先改 Prompt",
    "tool_misuse": "修正工具 Schema、参数校验与示例，并复跑失败任务",
    "planning_error": "补 SOP 节点或 Few-shot 轨迹，明确步骤顺序",
    "style_mismatch": "更新人格层风格卡，保持技能层只输出结构化结果",
    "permission_violation": "收紧契约与工具权限，并检查越权告警",
    "intent_misunderstanding": "补充意图样例与澄清话术，先问再做",
    "unknown": "人工复核未知失败，补充归因规则",
}


def _period(week_start: datetime | None) -> tuple[datetime, datetime]:
    if week_start is None:
        now = utcnow()
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start = week_start
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
    return start, start + timedelta(days=7)


async def build_weekly_review(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int | None,
    *,
    week_start: datetime | None = None,
    user_id: int | None = None,
) -> WeeklyReview:
    start, end = _period(week_start)

    task_conditions = [
        TaskInstance.tenant_id == tenant_id,
        TaskInstance.created_at >= start,
        TaskInstance.created_at < end,
    ]
    if employee_id is not None:
        task_conditions.append(TaskInstance.employee_id == employee_id)

    task_rows = await db.execute(
        select(TaskInstance.status, func.count(TaskInstance.id))
        .where(*task_conditions)
        .group_by(TaskInstance.status)
    )
    task_counts = {row[0]: row[1] for row in task_rows}
    total_tasks = sum(task_counts.values())
    succeeded = task_counts.get("succeeded", 0)

    intervention_conditions = [
        InterventionDelta.tenant_id == tenant_id,
        InterventionDelta.created_at >= start,
        InterventionDelta.created_at < end,
    ]
    attribution_conditions = [
        FailureAttribution.tenant_id == tenant_id,
        FailureAttribution.created_at >= start,
        FailureAttribution.created_at < end,
    ]
    artifact_conditions = [
        LearningArtifact.tenant_id == tenant_id,
        LearningArtifact.created_at >= start,
        LearningArtifact.created_at < end,
    ]
    question_conditions = [
        LearningQuestion.tenant_id == tenant_id,
        LearningQuestion.created_at >= start,
        LearningQuestion.created_at < end,
    ]
    trial_conditions = [
        EmployeeTrial.tenant_id == tenant_id,
        EmployeeTrial.created_at >= start,
        EmployeeTrial.created_at < end,
    ]
    outcome_conditions = [
        OutcomeEvent.tenant_id == tenant_id,
        OutcomeEvent.occurred_at >= start,
        OutcomeEvent.occurred_at < end,
    ]
    implicit_conditions = [
        ImplicitSignal.tenant_id == tenant_id,
        ImplicitSignal.created_at >= start,
        ImplicitSignal.created_at < end,
    ]
    if employee_id is not None:
        intervention_conditions.append(InterventionDelta.employee_id == employee_id)
        attribution_conditions.append(FailureAttribution.employee_id == employee_id)
        artifact_conditions.append(LearningArtifact.employee_id == employee_id)
        question_conditions.append(LearningQuestion.employee_id == employee_id)
        trial_conditions.append(EmployeeTrial.employee_id == employee_id)
        outcome_conditions.append(OutcomeEvent.employee_id == employee_id)
        implicit_conditions.append(ImplicitSignal.employee_id == employee_id)

    interventions = int(
        await db.scalar(
            select(func.count(InterventionDelta.id)).where(*intervention_conditions)
        )
        or 0
    )
    attribution_rows = await db.execute(
        select(FailureAttribution.category, func.count(FailureAttribution.id))
        .where(*attribution_conditions)
        .group_by(FailureAttribution.category)
    )
    attribution_counts = {row[0]: row[1] for row in attribution_rows}

    artifact_rows = await db.execute(
        select(LearningArtifact.status, func.count(LearningArtifact.id))
        .where(*artifact_conditions)
        .group_by(LearningArtifact.status)
    )
    artifact_counts = {row[0]: row[1] for row in artifact_rows}

    questions = int(
        await db.scalar(
            select(func.count(LearningQuestion.id)).where(*question_conditions)
        )
        or 0
    )
    answered_questions = int(
        await db.scalar(
            select(func.count(LearningQuestion.id)).where(
                *question_conditions, LearningQuestion.status == "answered"
            )
        )
        or 0
    )
    trials = int(
        await db.scalar(select(func.count(EmployeeTrial.id)).where(*trial_conditions)) or 0
    )
    outcome_rows = await db.execute(
        select(
            OutcomeEvent.outcome_type,
            OutcomeEvent.success,
            func.count(OutcomeEvent.id),
        )
        .where(*outcome_conditions)
        .group_by(OutcomeEvent.outcome_type, OutcomeEvent.success)
    )
    outcome_counts: dict[str, dict[str, int]] = {}
    for outcome_type, success, count in outcome_rows:
        bucket = outcome_counts.setdefault(str(outcome_type), {"total": 0, "success": 0})
        bucket["total"] += int(count)
        if success:
            bucket["success"] += int(count)

    implicit_rows = await db.execute(
        select(ImplicitSignal.signal_type, func.count(ImplicitSignal.id))
        .where(*implicit_conditions)
        .group_by(ImplicitSignal.signal_type)
    )
    implicit_counts = {row[0]: row[1] for row in implicit_rows}

    takeover_rate = round(interventions / total_tasks, 4) if total_tasks else 0.0
    one_pass_rate = (
        round(max(0, succeeded - interventions) / total_tasks, 4)
        if total_tasks
        else 0.0
    )
    success_rate = round(succeeded / total_tasks, 4) if total_tasks else 0.0

    top_errors = sorted(
        attribution_counts.items(), key=lambda item: item[1], reverse=True
    )[:3]
    top_error_payload = [
        {
            "category": category,
            "label": CATEGORY_LABELS.get(category, category),
            "count": count,
            "suggestion": RECOMMENDATIONS.get(category, ""),
        }
        for category, count in top_errors
    ]
    recommendations = []
    for category, _count in top_errors:
        suggestion = RECOMMENDATIONS.get(category)
        if suggestion and suggestion not in recommendations:
            recommendations.append(suggestion)
    if not recommendations:
        recommendations.append("本周没有明显失败归因，保持评估回归与巡检节奏")

    metrics = {
        "task_counts": task_counts,
        "total_tasks": total_tasks,
        "success_rate": success_rate,
        "one_pass_rate": one_pass_rate,
        "takeover_rate": takeover_rate,
        "interventions": interventions,
        "attribution_counts": attribution_counts,
        "artifact_counts": artifact_counts,
        "questions": questions,
        "answered_questions": answered_questions,
        "trials": trials,
        "outcome_counts": outcome_counts,
        "implicit_signals": implicit_counts,
        "recurrence": {
            category: count
            for category, count in attribution_counts.items()
            if count >= 2
        },
    }
    summary = (
        f"本周处理 {total_tasks} 个任务，成功率 {success_rate:.0%}，"
        f"一次通过率 {one_pass_rate:.0%}，接管率 {takeover_rate:.0%}；"
        f"产生 {sum(artifact_counts.values())} 个学习工件，"
        f"主动提问 {questions} 次（已回答 {answered_questions} 次）。"
    )
    if top_error_payload:
        summary += "Top 错误：" + "、".join(
            f"{item['label']}({item['count']})" for item in top_error_payload
        ) + "。"

    review = WeeklyReview(
        tenant_id=tenant_id,
        employee_id=employee_id,
        period_start=start,
        period_end=end,
        metrics=metrics,
        top_errors=top_error_payload,
        learned={"artifacts": artifact_counts},
        recommendations=recommendations,
        summary=summary,
        status="generated",
        created_by=user_id,
    )
    db.add(review)
    await db.flush()
    return review
