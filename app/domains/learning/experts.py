"""专家轨迹蒸馏：把高质量成功轨迹提炼成 SOP / Few-shot 学习工件。"""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.learning.models import InterventionDelta, LearningArtifact
from app.domains.learning.schemas import ExpertTrajectoryDistillRequest
from app.domains.workflows.tasks.models import TaskInstance, TaskStep


async def candidate_trajectories(
    db: AsyncSession,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    conditions = [
        TaskInstance.tenant_id == tenant_id,
        TaskInstance.status == "succeeded",
    ]
    if employee_id is not None:
        conditions.append(TaskInstance.employee_id == employee_id)
    instances = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(*conditions)
                .order_by(TaskInstance.attempt.asc(), TaskInstance.finished_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not instances:
        return []
    ids = [item.id for item in instances]
    intervention_rows = await db.execute(
        select(InterventionDelta.instance_id, func.count(InterventionDelta.id))
        .where(InterventionDelta.instance_id.in_(ids))
        .group_by(InterventionDelta.instance_id)
    )
    intervention_counts = {row[0]: row[1] for row in intervention_rows}
    step_rows = await db.execute(
        select(TaskStep.instance_id, func.count(TaskStep.id))
        .where(TaskStep.instance_id.in_(ids))
        .group_by(TaskStep.instance_id)
    )
    step_counts = {row[0]: row[1] for row in step_rows}
    return [
        {
            "instance_id": item.id,
            "employee_id": item.employee_id,
            "title": item.title,
            "attempt": item.attempt,
            "steps": step_counts.get(item.id, 0),
            "takeover": intervention_counts.get(item.id, 0),
            "trace_id": item.trace_id,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            "quality": "high"
            if item.attempt <= 1 and intervention_counts.get(item.id, 0) == 0
            else "medium",
        }
        for item in instances
    ]


def _excerpt(value, limit: int = 300) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


async def distill_trajectory(
    db: AsyncSession,
    tenant_id: int,
    payload: ExpertTrajectoryDistillRequest,
    *,
    user_id: int | None = None,
) -> LearningArtifact:
    instance = await db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == payload.instance_id,
            TaskInstance.tenant_id == tenant_id,
        )
    )
    if instance is None:
        raise NotFoundError("任务实例不存在")
    if instance.status != "succeeded":
        raise BadRequestError("只能蒸馏成功的任务轨迹")

    steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(
                    TaskStep.instance_id == instance.id,
                    TaskStep.status == "succeeded",
                )
                .order_by(TaskStep.step_index)
            )
        ).all()
    )
    if not steps:
        raise BadRequestError("任务没有成功步骤，无法蒸馏")

    trajectory = [
        {
            "index": step.step_index,
            "name": step.name,
            "type": step.step_type,
            "tool_code": step.tool_code,
            "input": step.input,
            "output_excerpt": _excerpt(step.output),
            "latency_ms": step.latency_ms,
        }
        for step in steps
    ]
    artifact = LearningArtifact(
        tenant_id=tenant_id,
        employee_id=instance.employee_id,
        source={
            "type": "expert_trajectory",
            "instance_id": instance.id,
            "trace_id": instance.trace_id,
            "employee_id": instance.employee_id,
        },
        attribution="专家轨迹蒸馏",
        target_layer="procedural_memory",
        proposal={
            "action": "add_trajectory",
            "name": payload.name or instance.title,
            "steps": trajectory,
        },
        evidence=[
            f"专家轨迹 instance#{instance.id} trace={instance.trace_id or '—'}",
            f"{len(steps)} 个成功步骤，任务尝试 {instance.attempt} 次",
        ],
        eval_result={},
        risk="medium",
        scope=payload.scope,
        status="pending_approval",
        rollout={"distilled_from_instance_id": instance.id},
        created_by=user_id,
    )
    db.add(artifact)
    await db.flush()
    return artifact
