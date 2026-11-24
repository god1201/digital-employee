"""分层记忆：语义冲突消解、记忆总览与情景压缩。"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.domains.learning.models import (
    InterventionDelta,
    LearningArtifact,
    PreferenceMemory,
)
from app.domains.workflows.tasks.models import TaskInstance

SEMANTIC = "semantic_memory"
PROCEDURAL = "procedural_memory"
PERSONA = "persona_layer"


def memory_key(artifact: LearningArtifact) -> str | None:
    proposal = artifact.proposal or {}
    for key in ("key", "subject", "topic", "name", "fact"):
        value = proposal.get(key)
        if value:
            return str(value)
    return None


async def supersede_semantic_memories(
    db: AsyncSession, artifact: LearningArtifact
) -> list[int]:
    """同一 key 的新语义事实生效时，旧事实标记 superseded，保留历史。"""
    if artifact.target_layer != SEMANTIC or artifact.employee_id is None:
        return []
    key = memory_key(artifact)
    if not key:
        return []
    candidates = list(
        (
            await db.scalars(
                select(LearningArtifact).where(
                    LearningArtifact.tenant_id == artifact.tenant_id,
                    LearningArtifact.employee_id == artifact.employee_id,
                    LearningArtifact.target_layer == SEMANTIC,
                    LearningArtifact.status.in_(["active", "canary"]),
                    LearningArtifact.id != artifact.id,
                )
            )
        ).all()
    )
    superseded = []
    for old in candidates:
        if memory_key(old) != key:
            continue
        old.status = "superseded"
        old.rollout = {
            **(old.rollout or {}),
            "superseded_by": artifact.id,
            "superseded_at": utcnow().isoformat(),
        }
        superseded.append(old.id)
    if superseded:
        await db.flush()
    return superseded


async def memory_overview(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    *,
    layer: str | None = None,
    limit: int = 20,
) -> dict:
    artifact_conditions = [
        LearningArtifact.tenant_id == tenant_id,
        LearningArtifact.employee_id == employee_id,
    ]
    if layer:
        artifact_conditions.append(LearningArtifact.target_layer == layer)
    artifacts = list(
        (
            await db.scalars(
                select(LearningArtifact)
                .where(*artifact_conditions)
                .order_by(LearningArtifact.id.desc())
                .limit(limit)
            )
        ).all()
    )
    preference_count = int(
        await db.scalar(
            select(func.count(PreferenceMemory.id)).where(
                PreferenceMemory.tenant_id == tenant_id,
                PreferenceMemory.employee_id == employee_id,
                PreferenceMemory.status == "active",
            )
        )
        or 0
    )
    recent_tasks = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.employee_id == employee_id,
                )
                .order_by(TaskInstance.id.desc())
                .limit(limit)
            )
        ).all()
    )
    recent_interventions = list(
        (
            await db.scalars(
                select(InterventionDelta)
                .where(
                    InterventionDelta.tenant_id == tenant_id,
                    InterventionDelta.employee_id == employee_id,
                )
                .order_by(InterventionDelta.id.desc())
                .limit(limit)
            )
        ).all()
    )
    return {
        "employee_id": employee_id,
        "layers": {
            "working": {"recent_tasks": len(recent_tasks)},
            "episodic": {
                "recent_tasks": [
                    {"id": item.id, "title": item.title, "status": item.status}
                    for item in recent_tasks
                ],
                "recent_interventions": [
                    {"id": item.id, "diff_count": len(item.diff or [])}
                    for item in recent_interventions
                ],
            },
            "semantic": {
                "artifacts": [
                    {"id": item.id, "status": item.status, "key": memory_key(item)}
                    for item in artifacts
                    if item.target_layer == SEMANTIC
                ]
            },
            "procedural": {
                "artifacts": [
                    {"id": item.id, "status": item.status, "name": memory_key(item)}
                    for item in artifacts
                    if item.target_layer == PROCEDURAL
                ]
            },
            "persona": {
                "artifacts": [
                    {"id": item.id, "status": item.status}
                    for item in artifacts
                    if item.target_layer == PERSONA
                ]
            },
            "preference": {"active_count": preference_count},
        },
    }


async def compress_episodes(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    *,
    before_days: int = 30,
    limit: int = 100,
    user_id: int | None = None,
) -> LearningArtifact:
    cutoff = utcnow() - timedelta(days=max(1, before_days))
    tasks = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.employee_id == employee_id,
                    TaskInstance.created_at < cutoff,
                )
                .order_by(TaskInstance.id.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).all()
    )
    succeeded = sum(1 for item in tasks if item.status == "succeeded")
    titles = "；".join(item.title for item in tasks[:10])
    content = (
        f"过去 {before_days} 天共有 {len(tasks)} 个任务，成功 {succeeded} 个。"
        f"近期任务：{titles or '无'}。"
    )
    artifact = LearningArtifact(
        tenant_id=tenant_id,
        employee_id=employee_id,
        source={"type": "memory_compression", "before_days": before_days},
        attribution="情景记忆压缩",
        target_layer=PROCEDURAL,
        proposal={
            "action": "compress_episodes",
            "key": "episodic_summary",
            "content": content,
        },
        evidence=[f"压缩 {len(tasks)} 条历史任务"],
        eval_result={},
        risk="low",
        scope="personal",
        status="pending_approval",
        rollout={"compressed_tasks": len(tasks)},
        created_by=user_id,
    )
    db.add(artifact)
    await db.flush()
    return artifact
