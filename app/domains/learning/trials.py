"""影子试运行与上岗资格认证。"""

from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.domains.knowledge.models import KnowledgeChunk
from app.domains.learning.models import (
    EmployeeTrial,
    FailureAttribution,
    FewShotExample,
    ImplicitSignal,
    InterventionDelta,
    LearningArtifact,
    OutcomeEvent,
)
from app.domains.skills.marketplace.service import installed_rows as installed_skill_rows
from app.domains.workflows.tasks.models import TaskInstance


async def build_trial(
    db: AsyncSession,
    employee,
    *,
    mode: str,
    sample_size: int,
    threshold: float,
    user_id: int | None = None,
) -> EmployeeTrial:
    instances = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(
                    TaskInstance.tenant_id == employee.tenant_id,
                    TaskInstance.employee_id == employee.id,
                )
                .order_by(TaskInstance.id.desc())
                .limit(sample_size)
            )
        ).all()
    )
    instance_ids = [item.id for item in instances]

    intervention_counts: dict[int, int] = {}
    if instance_ids:
        rows = await db.execute(
            select(InterventionDelta.instance_id, func.count(InterventionDelta.id))
            .where(InterventionDelta.instance_id.in_(instance_ids))
            .group_by(InterventionDelta.instance_id)
        )
        intervention_counts = {row[0]: row[1] for row in rows if row[0] is not None}

    attribution_map: dict[int, list[str]] = {}
    if instance_ids:
        rows = await db.execute(
            select(FailureAttribution.instance_id, FailureAttribution.category).where(
                FailureAttribution.instance_id.in_(instance_ids)
            )
        )
        for instance_id, category in rows:
            if instance_id is not None:
                attribution_map.setdefault(instance_id, []).append(category)

    total = len(instances)
    succeeded = sum(1 for item in instances if item.status == "succeeded")
    failed = sum(1 for item in instances if item.status == "failed")
    cancelled = sum(1 for item in instances if item.status == "cancelled")
    pending = total - succeeded - failed - cancelled
    takeover_instances = sum(
        1 for item in instances if intervention_counts.get(item.id, 0) > 0
    )
    one_pass = sum(
        1
        for item in instances
        if item.status == "succeeded" and intervention_counts.get(item.id, 0) == 0
    )
    avg_attempts = (
        round(sum(item.attempt or 0 for item in instances) / total, 2) if total else 0.0
    )

    success_rate = round(succeeded / total, 4) if total else 0.0
    takeover_rate = round(takeover_instances / total, 4) if total else 0.0
    one_pass_rate = round(one_pass / total, 4) if total else 0.0
    score = one_pass_rate

    sample_sufficient = total >= sample_size
    if total == 0:
        status, decision = "failed", "no_samples"
    elif mode == "certification" and not sample_sufficient:
        status, decision = "failed", "insufficient_samples"
    elif mode == "shadow" and not sample_sufficient:
        status, decision = "running", None
    elif score >= threshold:
        status = "passed"
        decision = "go_live" if mode == "certification" else "passed"
    else:
        status = "failed"
        decision = "downgrade" if mode == "certification" else "rejected"

    finished_at = utcnow()
    metrics = {
        "samples": total,
        "sample_size": sample_size,
        "sample_sufficient": sample_sufficient,
        "succeeded": succeeded,
        "failed": failed,
        "cancelled": cancelled,
        "pending": pending,
        "success_rate": success_rate,
        "takeover_rate": takeover_rate,
        "one_pass_rate": one_pass_rate,
        "avg_attempts": avg_attempts,
        "score": score,
    }
    details = [
        {
            "instance_id": item.id,
            "title": item.title,
            "status": item.status,
            "attempt": item.attempt,
            "takeover": intervention_counts.get(item.id, 0),
            "attributions": attribution_map.get(item.id, []),
        }
        for item in instances
    ]

    trial = EmployeeTrial(
        tenant_id=employee.tenant_id,
        employee_id=employee.id,
        mode=mode,
        status=status,
        sample_size=sample_size,
        threshold=threshold,
        metrics=metrics,
        details=details,
        decision=decision,
        started_at=finished_at,
        finished_at=finished_at,
        created_by=user_id,
    )
    db.add(trial)
    await db.flush()

    if mode == "certification":
        config = dict(employee.config or {})
        config["certification"] = {
            "level": "certified" if status == "passed" else "failed",
            "score": score,
            "threshold": threshold,
            "samples": total,
            "trial_id": trial.id,
            "decided_at": finished_at.isoformat(),
            "decision": decision,
        }
        employee.config = config

    await db.flush()
    return trial


async def build_profile(db: AsyncSession, employee) -> dict:
    status_rows = await db.execute(
        select(TaskInstance.status, func.count(TaskInstance.id))
        .where(
            TaskInstance.tenant_id == employee.tenant_id,
            TaskInstance.employee_id == employee.id,
        )
        .group_by(TaskInstance.status)
    )
    task_counts = {row[0]: row[1] for row in status_rows}
    total_tasks = sum(task_counts.values())

    takeover_rows = await db.execute(
        select(func.count(func.distinct(InterventionDelta.instance_id))).where(
            InterventionDelta.tenant_id == employee.tenant_id,
            InterventionDelta.employee_id == employee.id,
        )
    )
    takeover_instances = int(takeover_rows.scalar() or 0)

    takeover_subquery = (
        select(InterventionDelta.instance_id)
        .where(
            InterventionDelta.tenant_id == employee.tenant_id,
            InterventionDelta.employee_id == employee.id,
            InterventionDelta.instance_id.is_not(None),
        )
        .scalar_subquery()
    )
    one_pass = int(
        await db.scalar(
            select(func.count(TaskInstance.id)).where(
                TaskInstance.tenant_id == employee.tenant_id,
                TaskInstance.employee_id == employee.id,
                TaskInstance.status == "succeeded",
                TaskInstance.id.not_in(takeover_subquery),
            )
        )
        or 0
    )

    artifact_rows = await db.execute(
        select(LearningArtifact.status, func.count(LearningArtifact.id))
        .where(
            LearningArtifact.tenant_id == employee.tenant_id,
            LearningArtifact.employee_id == employee.id,
        )
        .group_by(LearningArtifact.status)
    )
    artifact_counts = {row[0]: row[1] for row in artifact_rows}

    attribution_rows = await db.execute(
        select(FailureAttribution.category, func.count(FailureAttribution.id))
        .where(
            FailureAttribution.tenant_id == employee.tenant_id,
            FailureAttribution.employee_id == employee.id,
        )
        .group_by(FailureAttribution.category)
    )
    attribution_counts = {row[0]: row[1] for row in attribution_rows}

    outcome_rows = await db.execute(
        select(
            OutcomeEvent.outcome_type,
            OutcomeEvent.success,
            func.count(OutcomeEvent.id),
        )
        .where(
            OutcomeEvent.tenant_id == employee.tenant_id,
            OutcomeEvent.employee_id == employee.id,
        )
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
        .where(
            ImplicitSignal.tenant_id == employee.tenant_id,
            ImplicitSignal.employee_id == employee.id,
        )
        .group_by(ImplicitSignal.signal_type)
    )
    implicit_counts = {row[0]: row[1] for row in implicit_rows}

    skill_rows = await installed_skill_rows(db, employee.tenant_id, employee.id)
    knowledge_base_ids: set[int] = set()
    for skill, package in skill_rows:
        if skill.status != "active":
            continue
        knowledge_base_ids.update(
            int(item) for item in (package.knowledge_base_ids or [])
        )
    chunk_count = 0
    if knowledge_base_ids:
        chunk_count = int(
            await db.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.tenant_id == employee.tenant_id,
                    KnowledgeChunk.base_id.in_(knowledge_base_ids),
                )
            )
            or 0
        )

    few_shot_count = int(
        await db.scalar(
            select(func.count(FewShotExample.id)).where(
                FewShotExample.tenant_id == employee.tenant_id,
                FewShotExample.employee_id == employee.id,
                FewShotExample.enabled.is_(True),
            )
        )
        or 0
    )

    trials = list(
        (
            await db.scalars(
                select(EmployeeTrial)
                .where(
                    EmployeeTrial.tenant_id == employee.tenant_id,
                    EmployeeTrial.employee_id == employee.id,
                )
                .order_by(EmployeeTrial.id.desc())
                .limit(5)
            )
        ).all()
    )

    succeeded = int(task_counts.get("succeeded", 0))
    success_rate = round(succeeded / total_tasks, 4) if total_tasks else 0.0
    takeover_rate = (
        round(takeover_instances / total_tasks, 4) if total_tasks else 0.0
    )
    one_pass_rate = round(one_pass / total_tasks, 4) if total_tasks else 0.0
    active_artifacts = int(artifact_counts.get("active", 0))
    outcome_total = sum(item["total"] for item in outcome_counts.values())
    outcome_success = sum(item["success"] for item in outcome_counts.values())
    outcome_rate = (
        round(outcome_success / outcome_total, 4) if outcome_total else 0.0
    )
    capability_radar = [
        {"key": "delivery", "label": "交付成功率", "value": success_rate},
        {"key": "one_pass", "label": "一次通过率", "value": one_pass_rate},
        {
            "key": "autonomy",
            "label": "自主完成率",
            "value": round(max(0.0, 1 - takeover_rate), 4),
        },
        {
            "key": "knowledge",
            "label": "知识覆盖",
            "value": round(min(1.0, chunk_count / 100), 4),
        },
        {
            "key": "learning",
            "label": "学习闭环",
            "value": round(min(1.0, active_artifacts / 10), 4),
        },
        {"key": "outcome", "label": "业务结果", "value": outcome_rate},
    ]

    return {
        "employee_id": employee.id,
        "task_counts": task_counts,
        "total_tasks": total_tasks,
        "success_rate": success_rate,
        "takeover_rate": takeover_rate,
        "one_pass_rate": one_pass_rate,
        "capability_radar": capability_radar,
        "artifact_counts": artifact_counts,
        "attribution_counts": attribution_counts,
        "recurrence": {
            category: count
            for category, count in attribution_counts.items()
            if count >= 2
        },
        "outcome_counts": outcome_counts,
        "implicit_signals": implicit_counts,
        "knowledge_coverage": {
            "knowledge_bases": len(knowledge_base_ids),
            "chunks": chunk_count,
        },
        "few_shot_count": few_shot_count,
        "prompt_budget": (employee.config or {}).get("prompt_token_budget", 0),
        "certification": (employee.config or {}).get("certification"),
        "trials": [
            {
                "id": item.id,
                "mode": item.mode,
                "status": item.status,
                "score": (item.metrics or {}).get("score", 0),
                "threshold": item.threshold,
                "decision": item.decision,
                "created_at": item.created_at.isoformat(),
            }
            for item in trials
        ],
    }


async def build_trend(
    db: AsyncSession,
    employee,
    *,
    days: int = 30,
) -> dict:
    """按天聚合任务、接管与学习工件，用于数字履历学习曲线。"""
    window = max(1, min(90, days))
    current = utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    end = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    start = end - timedelta(days=window)
    tenant_id = employee.tenant_id
    employee_id = employee.id

    task_rows = await db.execute(
        select(
            func.date(TaskInstance.created_at),
            TaskInstance.status,
            func.count(TaskInstance.id),
        )
        .where(
            TaskInstance.tenant_id == tenant_id,
            TaskInstance.employee_id == employee_id,
            TaskInstance.created_at >= start,
            TaskInstance.created_at < end,
        )
        .group_by(func.date(TaskInstance.created_at), TaskInstance.status)
    )
    takeover_rows = await db.execute(
        select(
            func.date(InterventionDelta.created_at),
            func.count(InterventionDelta.id),
        )
        .where(
            InterventionDelta.tenant_id == tenant_id,
            InterventionDelta.employee_id == employee_id,
            InterventionDelta.created_at >= start,
            InterventionDelta.created_at < end,
        )
        .group_by(func.date(InterventionDelta.created_at))
    )
    artifact_rows = await db.execute(
        select(
            func.date(LearningArtifact.created_at),
            func.count(LearningArtifact.id),
        )
        .where(
            LearningArtifact.tenant_id == tenant_id,
            LearningArtifact.employee_id == employee_id,
            LearningArtifact.created_at >= start,
            LearningArtifact.created_at < end,
        )
        .group_by(func.date(LearningArtifact.created_at))
    )

    buckets: dict[str, dict[str, int]] = {}
    for day, status, count in task_rows:
        bucket = buckets.setdefault(
            str(day),
            {"total": 0, "succeeded": 0, "failed": 0, "takeovers": 0, "artifacts": 0},
        )
        bucket["total"] += int(count)
        if status == "succeeded":
            bucket["succeeded"] += int(count)
        elif status == "failed":
            bucket["failed"] += int(count)
    for day, count in takeover_rows:
        bucket = buckets.setdefault(
            str(day),
            {"total": 0, "succeeded": 0, "failed": 0, "takeovers": 0, "artifacts": 0},
        )
        bucket["takeovers"] += int(count)
    for day, count in artifact_rows:
        bucket = buckets.setdefault(
            str(day),
            {"total": 0, "succeeded": 0, "failed": 0, "takeovers": 0, "artifacts": 0},
        )
        bucket["artifacts"] += int(count)

    series = []
    cursor = start
    while cursor < end:
        key = cursor.date().isoformat()
        bucket = buckets.get(
            key, {"total": 0, "succeeded": 0, "failed": 0, "takeovers": 0, "artifacts": 0}
        )
        total = bucket["total"]
        series.append(
            {
                "date": key,
                "total": total,
                "succeeded": bucket["succeeded"],
                "failed": bucket["failed"],
                "takeovers": bucket["takeovers"],
                "artifacts": bucket["artifacts"],
                "success_rate": (
                    round(bucket["succeeded"] / total, 4) if total else 0.0
                ),
                "takeover_rate": (
                    round(bucket["takeovers"] / total, 4) if total else 0.0
                ),
            }
        )
        cursor += timedelta(days=1)

    return {
        "employee_id": employee_id,
        "days": window,
        "start": start.date().isoformat(),
        "end": (end - timedelta(days=1)).date().isoformat(),
        "series": series,
    }
