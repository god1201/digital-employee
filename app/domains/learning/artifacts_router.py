from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.core.base import utcnow
from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.evaluation import run_suite, suites_for_employee
from app.domains.learning.memory import supersede_semantic_memories
from app.domains.learning.models import LearningArtifact
from app.domains.learning.rollout import rollout_metrics, share_copy
from app.domains.learning.schemas import (
    ArtifactCreate,
    ArtifactDecision,
    ArtifactOut,
    ArtifactRolloutRequest,
    ArtifactShareRequest,
    ArtifactVersionCreate,
)
from app.domains.learning.service import create_artifact
from app.domains.workforce.employees.service import get_employee
from app.domains.workforce.prompting import build_employee_prompt

router = APIRouter(prefix="/learning-artifacts", tags=["学习工件"])

DECIDABLE_STATUSES = {"draft", "pending_approval"}


async def _get_artifact(
    db: DbSession, tenant_id: int, artifact_id: int
) -> LearningArtifact:
    artifact = await db.scalar(
        select(LearningArtifact).where(
            LearningArtifact.id == artifact_id,
            LearningArtifact.tenant_id == tenant_id,
        )
    )
    if artifact is None:
        raise NotFoundError("学习工件不存在")
    return artifact


@router.get("", summary="学习工件列表（含审批队列）")
async def list_artifacts(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    status: str | None = None,
    scope: str | None = None,
    target_layer: str | None = None,
    risk: str | None = None,
):
    conditions = [LearningArtifact.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(LearningArtifact.employee_id == employee_id)
    if status:
        conditions.append(LearningArtifact.status == status)
    if scope:
        conditions.append(LearningArtifact.scope == scope)
    if target_layer:
        conditions.append(LearningArtifact.target_layer == target_layer)
    if risk:
        conditions.append(LearningArtifact.risk == risk)

    stmt = select(LearningArtifact).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(LearningArtifact.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [ArtifactOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建学习工件（默认进入审批队列）")
async def create_artifact_endpoint(
    payload: ArtifactCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    artifact = create_artifact(payload, tenant_id=current_user.tenant_id, user_id=current_user.id)
    db.add(artifact)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.create",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"target_layer": artifact.target_layer, "risk": artifact.risk},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.get("/{artifact_id}", summary="学习工件详情")
async def get_artifact_detail(
    artifact_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/approve",
    summary="审批通过学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def approve_artifact(
    artifact_id: int,
    payload: ArtifactDecision,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status not in DECIDABLE_STATUSES:
        raise BadRequestError(f"当前状态不可审批: {artifact.status}")
    artifact.status = "approved"
    artifact.approved_by = current_user.id
    artifact.approved_at = utcnow()
    if payload.note:
        artifact.rollout = {**(artifact.rollout or {}), "approval_note": payload.note}
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.approve",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"note": payload.note},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/reject",
    summary="驳回学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def reject_artifact(
    artifact_id: int,
    payload: ArtifactDecision,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status not in DECIDABLE_STATUSES:
        raise BadRequestError(f"当前状态不可驳回: {artifact.status}")
    artifact.status = "rejected"
    if payload.note:
        artifact.rollout = {**(artifact.rollout or {}), "reject_reason": payload.note}
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.reject",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"reason": payload.note},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/activate",
    summary="生效学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def activate_artifact(
    artifact_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status != "approved":
        raise BadRequestError("只有已审批通过学习工件可以生效")

    if artifact.employee_id is not None:
        suites = await suites_for_employee(
            db, current_user.tenant_id, artifact.employee_id
        )
        if suites:
            employee = await get_employee(db, current_user.tenant_id, artifact.employee_id)
            system_prompt = await build_employee_prompt(
                db, current_user.tenant_id, employee
            )

            runs = []
            for suite in suites:
                runs.append(
                    await run_suite(
                        db,
                        suite,
                        employee=employee,
                        system_prompt=system_prompt,
                        artifact_id=artifact.id,
                        trigger="artifact_activation",
                        user_id=current_user.id,
                    )
                )
            eval_summary = {
                str(run.suite_id): {
                    "run_id": run.id,
                    "score": run.score,
                    "threshold": run.threshold,
                    "baseline_score": run.baseline_score,
                    "delta": run.delta,
                    "passed": run.passed,
                    "status": run.status,
                }
                for run in runs
            }
            artifact.eval_result = {**(artifact.eval_result or {}), "activation": eval_summary}

            failed = [run for run in runs if not run.passed]
            if failed:
                failed_codes = {
                    str(suite.id): suite.code for suite in suites
                }
                summary = "；".join(
                    f"{failed_codes.get(str(run.suite_id), run.suite_id)} "
                    f"得分 {run.score:.2f} < 阈值 {run.threshold:.2f}"
                    for run in failed
                )
                artifact.rollout = {
                    **(artifact.rollout or {}),
                    "activation_blocked": True,
                    "blocked_reason": summary,
                }
                await record_audit(
                    db,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    employee_id=artifact.employee_id,
                    action="artifact.activation_blocked",
                    resource_type="learning_artifact",
                    resource_id=artifact.id,
                    detail={"reason": summary},
                    ip_address=client_ip(request),
                )
                # 评估记录必须先落库，否则异常回滚会丢失证据
                await db.commit()
                raise BadRequestError(f"综合评估未通过，已阻止生效：{summary}")

    await supersede_semantic_memories(db, artifact)
    artifact.status = "active"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.activate",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/rollback",
    summary="回滚学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def rollback_artifact(
    artifact_id: int,
    payload: ArtifactDecision,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status not in {"active", "approved"}:
        raise BadRequestError("只有已生效或已审批的学习工件可以回滚")
    artifact.status = "rolled_back"
    artifact.rollback_of = artifact.id
    artifact.rollout = {
        **(artifact.rollout or {}),
        "rolled_back_by": current_user.id,
        "rolled_back_at": utcnow().isoformat(),
        "rollback_note": payload.note,
    }
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.rollback",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"note": payload.note},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/rollout",
    summary="影子 / 金丝雀 / 全量发布",
    dependencies=[Depends(get_current_admin)],
)
async def rollout_artifact(
    artifact_id: int,
    payload: ArtifactRolloutRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status not in {"approved", "shadow", "canary", "active"}:
        raise BadRequestError("只有已审批或发布中的工件可以调整发布策略")

    traffic = 1.0 if payload.mode == "full" else 0.0
    if payload.mode == "canary":
        traffic = payload.traffic
    status = {"shadow": "shadow", "canary": "canary", "full": "active"}[payload.mode]
    now = utcnow()
    if status == "active":
        await supersede_semantic_memories(db, artifact)
    artifact.status = status
    artifact.rollout = {
        **(artifact.rollout or {}),
        "mode": payload.mode,
        "traffic": traffic,
        "started_at": now.isoformat(),
        "note": payload.note,
        "observations": await rollout_metrics(db, artifact),
    }
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.rollout",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"mode": payload.mode, "traffic": traffic},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.get("/{artifact_id}/rollout", summary="发布状态与观测指标")
async def get_rollout(
    artifact_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    return success(
        {
            "artifact_id": artifact.id,
            "status": artifact.status,
            "rollout": artifact.rollout or {},
            "metrics": await rollout_metrics(db, artifact),
        }
    )


@router.post(
    "/{artifact_id}/promote",
    summary="推进发布阶段（影子→金丝雀→全量）",
    dependencies=[Depends(get_current_admin)],
)
async def promote_artifact(
    artifact_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    stages = {"approved": ("shadow", 0.0), "shadow": ("canary", 0.1), "canary": ("active", 1.0)}
    if artifact.status not in stages:
        raise BadRequestError(f"当前状态不可推进: {artifact.status}")
    status, traffic = stages[artifact.status]
    now = utcnow()
    if status == "active":
        await supersede_semantic_memories(db, artifact)
    artifact.status = status
    artifact.rollout = {
        **(artifact.rollout or {}),
        "mode": "full" if status == "active" else status,
        "traffic": traffic,
        "started_at": now.isoformat(),
        "observations": await rollout_metrics(db, artifact),
    }
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.promote",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"status": status, "traffic": traffic},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))


@router.post(
    "/{artifact_id}/share",
    summary="共享到团队或组织（需再次审批）",
    dependencies=[Depends(get_current_admin)],
)
async def share_artifact(
    artifact_id: int,
    payload: ArtifactShareRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status not in {"approved", "active"}:
        raise BadRequestError("只有已审批或已生效的工件可以共享")

    shared = share_copy(
        artifact,
        scope=payload.scope,
        note=payload.note,
        user_id=current_user.id,
    )
    db.add(shared)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.share",
        resource_type="learning_artifact",
        resource_id=shared.id,
        detail={
            "from_artifact_id": artifact.id,
            "scope": payload.scope,
            "note": payload.note,
        },
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(shared).model_dump(mode="json"))


@router.get("/{artifact_id}/lineage", summary="学习工件版本谱系")
async def artifact_lineage(
    artifact_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    chain: dict[int, LearningArtifact] = {}
    current: LearningArtifact | None = artifact
    while current is not None and current.id not in chain:
        chain[current.id] = current
        parent_id = current.supersedes_id or current.rollback_of
        if not parent_id:
            break
        current = await db.scalar(
            select(LearningArtifact).where(
                LearningArtifact.id == parent_id,
                LearningArtifact.tenant_id == current_user.tenant_id,
            )
        )
    children = list(
        (
            await db.scalars(
                select(LearningArtifact).where(
                    LearningArtifact.tenant_id == current_user.tenant_id,
                    LearningArtifact.supersedes_id == artifact.id,
                )
            )
        ).all()
    )
    for child in children:
        chain[child.id] = child
    items = sorted(chain.values(), key=lambda item: (item.version, item.id))
    return success(
        [
            {
                "id": item.id,
                "version": item.version,
                "status": item.status,
                "attribution": item.attribution,
                "target_layer": item.target_layer,
                "supersedes_id": item.supersedes_id,
                "rollback_of": item.rollback_of,
                "created_at": item.created_at.isoformat(),
                "proposal": item.proposal,
            }
            for item in items
        ]
    )


@router.post("/{artifact_id}/new-version", summary="基于当前工件创建新版本")
async def create_new_version(
    artifact_id: int,
    payload: ArtifactVersionCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    if artifact.status in {"archived"}:
        raise BadRequestError("已归档的学习工件不能创建新版本")
    new_artifact = LearningArtifact(
        tenant_id=artifact.tenant_id,
        employee_id=artifact.employee_id,
        source={
            "type": "new_version",
            "from_artifact_id": artifact.id,
            **(artifact.source or {}),
        },
        attribution=payload.attribution or artifact.attribution,
        target_layer=payload.target_layer or artifact.target_layer,
        proposal=payload.proposal if payload.proposal is not None else artifact.proposal,
        evidence=payload.evidence if payload.evidence is not None else artifact.evidence,
        eval_result={},
        risk=payload.risk or artifact.risk,
        scope=payload.scope or artifact.scope,
        status="pending_approval",
        rollout=payload.rollout if payload.rollout is not None else artifact.rollout,
        version=artifact.version + 1,
        supersedes_id=artifact.id,
        expires_at=artifact.expires_at,
        created_by=current_user.id,
    )
    db.add(new_artifact)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=new_artifact.employee_id,
        action="artifact.new_version",
        resource_type="learning_artifact",
        resource_id=new_artifact.id,
        detail={"from_artifact_id": artifact.id, "version": new_artifact.version},
        ip_address=client_ip(request),
    )
    return success(
        ArtifactOut.model_validate(new_artifact).model_dump(mode="json")
    )


@router.post(
    "/{artifact_id}/archive",
    summary="归档学习工件",
    dependencies=[Depends(get_current_admin)],
)
async def archive_artifact(
    artifact_id: int,
    db: DbSession,
    current_user: CurrentUser,
    request: Request,
):
    artifact = await _get_artifact(db, current_user.tenant_id, artifact_id)
    artifact.status = "archived"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.archive",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))
