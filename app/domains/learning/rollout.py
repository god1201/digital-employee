"""学习工件发布：影子 / 金丝雀 / 全量，以及团队级共享。"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.learning.models import (
    InterventionDelta,
    LearningArtifact,
)
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.teams.models import TeamMember

APPLICABLE_STATUSES = {"active", "canary"}


def canary_bucket(trace_id: str | None, artifact_id: int) -> int:
    seed = f"{trace_id or ''}:{artifact_id}".encode()
    return int(hashlib.sha256(seed).hexdigest()[:8], 16) % 100


def artifact_visible(
    artifact: LearningArtifact,
    *,
    trace_id: str | None,
    include_canary: bool = True,
) -> bool:
    if artifact.status == "active":
        return True
    if artifact.status == "canary":
        if not include_canary or trace_id is None:
            return include_canary
        traffic = float((artifact.rollout or {}).get("traffic") or 0.0)
        return canary_bucket(trace_id, artifact.id) < int(traffic * 100)
    return False


def _content(artifact: LearningArtifact) -> str:
    proposal = artifact.proposal or {}
    content = proposal.get("content") or proposal.get("rule") or proposal.get("name")
    if content:
        return str(content)
    return json.dumps(proposal, ensure_ascii=False)


async def _team_artifact_ids(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> set[int]:
    team_ids = select(TeamMember.team_id).where(
        TeamMember.tenant_id == tenant_id,
        TeamMember.employee_id == employee_id,
    )
    member_ids = select(TeamMember.employee_id).where(
        TeamMember.tenant_id == tenant_id,
        TeamMember.team_id.in_(team_ids),
        TeamMember.employee_id.is_not(None),
    )
    rows = await db.execute(
        select(LearningArtifact.id).where(
            LearningArtifact.tenant_id == tenant_id,
            LearningArtifact.scope == "team",
            LearningArtifact.status == "active",
            LearningArtifact.employee_id.in_(member_ids),
        )
    )
    return {row[0] for row in rows}


async def applicable_artifacts(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    *,
    trace_id: str | None = None,
    include_canary: bool = True,
) -> list[LearningArtifact]:
    personal = list(
        (
            await db.scalars(
                select(LearningArtifact).where(
                    LearningArtifact.tenant_id == tenant_id,
                    LearningArtifact.employee_id == employee_id,
                    LearningArtifact.status.in_(APPLICABLE_STATUSES),
                )
            )
        ).all()
    )
    shared = list(
        (
            await db.scalars(
                select(LearningArtifact).where(
                    LearningArtifact.tenant_id == tenant_id,
                    LearningArtifact.scope == "organization",
                    LearningArtifact.status == "active",
                )
            )
        ).all()
    )
    team_ids = await _team_artifact_ids(db, tenant_id, employee_id)
    if team_ids:
        shared.extend(
            list(
                (
                    await db.scalars(
                        select(LearningArtifact).where(
                            LearningArtifact.tenant_id == tenant_id,
                            LearningArtifact.id.in_(team_ids),
                        )
                    )
                ).all()
            )
        )

    seen: set[int] = set()
    result: list[LearningArtifact] = []
    for artifact in [*personal, *shared]:
        if artifact.id in seen:
            continue
        seen.add(artifact.id)
        if artifact_visible(
            artifact, trace_id=trace_id, include_canary=include_canary
        ):
            result.append(artifact)
    result.sort(key=lambda item: (item.target_layer, item.id))
    return result


def build_artifacts_context(artifacts: list[LearningArtifact]) -> str:
    if not artifacts:
        return ""
    lines = ["已生效的岗位经验（必须遵守）："]
    for artifact in artifacts:
        lines.append(f"- [{artifact.target_layer}] {_content(artifact)}")
    return "\n".join(lines)


async def load_artifacts_context(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int | None,
    *,
    trace_id: str | None = None,
    include_canary: bool = True,
) -> str:
    if not employee_id:
        return ""
    artifacts = await applicable_artifacts(
        db,
        tenant_id,
        employee_id,
        trace_id=trace_id,
        include_canary=include_canary,
    )
    return build_artifacts_context(artifacts)


def _rollout_since(artifact: LearningArtifact) -> datetime | None:
    rollout = artifact.rollout or {}
    raw = rollout.get("started_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    return artifact.approved_at or artifact.created_at


async def rollout_metrics(db: AsyncSession, artifact: LearningArtifact) -> dict:
    since = _rollout_since(artifact)
    if artifact.employee_id is None or since is None:
        return {"samples": 0, "reason": "缺少员工或起始时间"}

    conditions = [
        TaskInstance.tenant_id == artifact.tenant_id,
        TaskInstance.employee_id == artifact.employee_id,
        TaskInstance.created_at >= since,
    ]
    total = int(
        await db.scalar(
            select(func.count(TaskInstance.id)).where(*conditions)
        )
        or 0
    )
    status_rows = await db.execute(
        select(TaskInstance.status, func.count(TaskInstance.id))
        .where(*conditions)
        .group_by(TaskInstance.status)
    )
    counts = {row[0]: row[1] for row in status_rows}
    succeeded = counts.get("succeeded", 0)

    takeover_subquery = (
        select(InterventionDelta.instance_id)
        .where(
            InterventionDelta.tenant_id == artifact.tenant_id,
            InterventionDelta.employee_id == artifact.employee_id,
            InterventionDelta.instance_id.is_not(None),
            InterventionDelta.created_at >= since,
        )
        .scalar_subquery()
    )
    takeover = int(
        await db.scalar(
            select(func.count(func.distinct(TaskInstance.id))).where(
                *conditions, TaskInstance.id.in_(takeover_subquery)
            )
        )
        or 0
    )
    one_pass = int(
        await db.scalar(
            select(func.count(TaskInstance.id)).where(
                *conditions,
                TaskInstance.status == "succeeded",
                TaskInstance.id.not_in(takeover_subquery),
            )
        )
        or 0
    )
    return {
        "samples": total,
        "succeeded": succeeded,
        "failed": counts.get("failed", 0),
        "success_rate": round(succeeded / total, 4) if total else 0.0,
        "takeover_rate": round(takeover / total, 4) if total else 0.0,
        "one_pass_rate": round(one_pass / total, 4) if total else 0.0,
        "since": since.isoformat(),
    }


def share_copy(
    artifact: LearningArtifact,
    *,
    scope: str,
    note: str | None,
    user_id: int | None,
) -> LearningArtifact:
    return LearningArtifact(
        tenant_id=artifact.tenant_id,
        employee_id=artifact.employee_id,
        source={
            "type": "shared_from",
            "from_artifact_id": artifact.id,
            **(artifact.source or {}),
        },
        attribution=artifact.attribution,
        target_layer=artifact.target_layer,
        proposal=artifact.proposal,
        evidence=artifact.evidence,
        eval_result={},
        risk=artifact.risk,
        scope=scope,
        status="pending_approval",
        rollout={
            "shared_from_artifact_id": artifact.id,
            "share_note": note,
            "shared_by": user_id,
        },
        version=artifact.version,
        expires_at=artifact.expires_at,
        created_by=user_id,
    )
