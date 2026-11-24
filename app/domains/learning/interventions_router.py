from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.models import InterventionDelta
from app.domains.learning.schemas import (
    ArtifactCreate,
    ArtifactOut,
    InterventionCreate,
    InterventionOut,
    InterventionStatusUpdate,
)
from app.domains.learning.service import (
    build_intervention,
    create_artifact,
    diff_summary,
)
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/interventions", tags=["接管增量"])


async def _get_delta(
    db: DbSession, tenant_id: int, intervention_id: int
) -> InterventionDelta:
    delta = await db.scalar(
        select(InterventionDelta).where(
            InterventionDelta.id == intervention_id,
            InterventionDelta.tenant_id == tenant_id,
        )
    )
    if delta is None:
        raise NotFoundError("接管增量不存在")
    return delta


@router.get("", summary="人工接管增量列表")
async def list_interventions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    instance_id: int | None = None,
    status: str | None = None,
    source_type: str | None = None,
):
    conditions = [InterventionDelta.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(InterventionDelta.employee_id == employee_id)
    if instance_id is not None:
        conditions.append(InterventionDelta.instance_id == instance_id)
    if status:
        conditions.append(InterventionDelta.status == status)
    if source_type:
        conditions.append(InterventionDelta.source_type == source_type)

    stmt = select(InterventionDelta).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(InterventionDelta.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [InterventionOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="手工记录一次接管增量（单次示范教学）")
async def create_intervention(
    payload: InterventionCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    if payload.instance_id is not None:
        instance = await db.scalar(
            select(TaskInstance.id).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == current_user.tenant_id,
            )
        )
        if instance is None:
            raise NotFoundError("任务实例不存在")

    delta = build_intervention(payload, tenant_id=current_user.tenant_id, actor_id=current_user.id)
    db.add(delta)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=delta.employee_id,
        action="intervention.create",
        resource_type="intervention_delta",
        resource_id=delta.id,
        detail={
            "source_type": delta.source_type,
            "changes": diff_summary(delta.diff)["total"],
        },
        ip_address=client_ip(request),
    )
    return success(InterventionOut.model_validate(delta).model_dump(mode="json"))


@router.get("/{intervention_id}", summary="接管增量详情")
async def get_intervention(
    intervention_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    delta = await _get_delta(db, current_user.tenant_id, intervention_id)
    data = InterventionOut.model_validate(delta).model_dump(mode="json")
    data["summary"] = diff_summary(delta.diff)
    return success(data)


@router.patch("/{intervention_id}", summary="更新接管增量状态")
async def update_intervention(
    intervention_id: int,
    payload: InterventionStatusUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    delta = await _get_delta(db, current_user.tenant_id, intervention_id)
    delta.status = payload.status
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=delta.employee_id,
        action="intervention.status",
        resource_type="intervention_delta",
        resource_id=delta.id,
        detail={"status": payload.status},
        ip_address=client_ip(request),
    )
    return success(InterventionOut.model_validate(delta).model_dump(mode="json"))


@router.post("/{intervention_id}/artifact", summary="将接管增量提炼为学习工件")
async def artifact_from_intervention(
    intervention_id: int,
    payload: ArtifactCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    delta = await _get_delta(db, current_user.tenant_id, intervention_id)
    source = {
        "type": delta.source_type,
        "trace_id": delta.trace_id,
        "instance_id": delta.instance_id,
        "step_id": delta.step_id,
        "actor_id": delta.actor_id,
        "intervention_id": delta.id,
        **payload.source,
    }
    evidence = list(payload.evidence or [])
    evidence.append(f"人工接管 diff：{diff_summary(delta.diff)['total']} 处变更")
    if delta.comment:
        evidence.append(delta.comment)
    artifact_payload = payload.model_copy(
        update={
            "employee_id": payload.employee_id or delta.employee_id,
            "source": source,
            "evidence": evidence,
        }
    )
    artifact = create_artifact(
        artifact_payload, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    db.add(artifact)
    delta.status = "artifact_created"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.create_from_intervention",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"intervention_id": delta.id, "target_layer": artifact.target_layer},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))
