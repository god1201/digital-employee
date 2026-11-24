"""学习闭环服务：接管增量、偏好记忆、学习工件。"""

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.domains.learning.models import (
    InterventionDelta,
    LearningArtifact,
    PreferenceMemory,
)
from app.domains.learning.schemas import (
    ArtifactCreate,
    InterventionCreate,
    PreferenceUpsert,
)

DIFF_LIMIT = 200


def compute_diff(
    original: Any, final: Any, *, path: str = "", limit: int = DIFF_LIMIT
) -> list[dict]:
    """计算两个 JSON 值的结构化差异，供归因与示范教学使用。"""
    diffs: list[dict] = []

    def walk(before: Any, after: Any, current: str) -> None:
        if len(diffs) >= limit:
            return
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                child = f"{current}.{key}" if current else str(key)
                if key not in before:
                    diffs.append({"path": child, "op": "add", "before": None, "after": after[key]})
                elif key not in after:
                    diffs.append(
                        {"path": child, "op": "remove", "before": before[key], "after": None}
                    )
                else:
                    walk(before[key], after[key], child)
            return
        if isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                child = f"{current}[{index}]"
                if index >= len(before):
                    diffs.append(
                        {"path": child, "op": "add", "before": None, "after": after[index]}
                    )
                elif index >= len(after):
                    diffs.append(
                        {"path": child, "op": "remove", "before": before[index], "after": None}
                    )
                else:
                    walk(before[index], after[index], child)
            return
        if before != after:
            diffs.append(
                {"path": current or "$", "op": "change", "before": before, "after": after}
            )

    walk(original, final, path)
    return diffs


def diff_summary(diff: list[dict]) -> dict:
    counts = {"add": 0, "remove": 0, "change": 0}
    for item in diff:
        op = item.get("op")
        if op in counts:
            counts[op] += 1
    return {**counts, "total": len(diff)}


def build_intervention(
    payload: InterventionCreate,
    *,
    tenant_id: int,
    actor_id: int | None,
    instance_id: int | None = None,
    step_id: int | None = None,
    source_type: str | None = None,
) -> InterventionDelta:
    return InterventionDelta(
        tenant_id=tenant_id,
        employee_id=payload.employee_id,
        instance_id=payload.instance_id or instance_id,
        step_id=payload.step_id or step_id,
        trace_id=payload.trace_id,
        actor_id=actor_id,
        source_type=source_type or payload.source_type,
        original_output=payload.original_output,
        final_output=payload.final_output,
        diff=compute_diff(payload.original_output, payload.final_output),
        comment=payload.comment,
        created_by=actor_id,
    )


async def get_preference(
    db: AsyncSession, tenant_id: int, employee_id: int, key: str
) -> PreferenceMemory | None:
    return await db.scalar(
        select(PreferenceMemory).where(
            PreferenceMemory.tenant_id == tenant_id,
            PreferenceMemory.employee_id == employee_id,
            PreferenceMemory.key == key,
        )
    )


async def upsert_preference(
    db: AsyncSession,
    tenant_id: int,
    payload: PreferenceUpsert,
    *,
    user_id: int | None = None,
) -> tuple[PreferenceMemory, bool]:
    preference = await get_preference(db, tenant_id, payload.employee_id, payload.key)
    created = preference is None
    if preference is None:
        preference = PreferenceMemory(
            tenant_id=tenant_id,
            created_by=user_id,
            **payload.model_dump(),
        )
        db.add(preference)
    else:
        preference.value = payload.value
        preference.scope = payload.scope
        preference.source = payload.source
        preference.confidence = payload.confidence
        preference.expires_at = payload.expires_at
        preference.status = "active"
    await db.flush()
    return preference, created


async def active_preferences(
    db: AsyncSession, tenant_id: int, employee_id: int | None
) -> list[PreferenceMemory]:
    if not employee_id:
        return []
    now = utcnow()
    return list(
        (
            await db.scalars(
                select(PreferenceMemory)
                .where(
                    PreferenceMemory.tenant_id == tenant_id,
                    PreferenceMemory.employee_id == employee_id,
                    PreferenceMemory.status == "active",
                    or_(
                        PreferenceMemory.expires_at.is_(None),
                        PreferenceMemory.expires_at > now,
                    ),
                )
                .order_by(PreferenceMemory.id)
            )
        ).all()
    )


def build_preference_context(preferences: list[PreferenceMemory]) -> str:
    if not preferences:
        return ""
    lines = [f"- {item.key}：{item.value}" for item in preferences]
    return "员工偏好记忆（必须遵守）：\n" + "\n".join(lines)


def create_artifact(
    payload: ArtifactCreate,
    *,
    tenant_id: int,
    user_id: int | None,
) -> LearningArtifact:
    return LearningArtifact(
        tenant_id=tenant_id,
        created_by=user_id,
        **payload.model_dump(),
    )


async def get_artifact(
    db: AsyncSession, tenant_id: int, artifact_id: int
) -> LearningArtifact | None:
    return await db.scalar(
        select(LearningArtifact).where(
            LearningArtifact.id == artifact_id,
            LearningArtifact.tenant_id == tenant_id,
        )
    )
