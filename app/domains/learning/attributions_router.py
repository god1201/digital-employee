from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.llm import LLMError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.attribution import (
    attribute_instance_failure,
    attribute_intervention,
    attribution_artifact_payload,
    classify_failure,
    classify_failure_llm,
    reanalyze_attribution_llm,
    route_label,
)
from app.domains.learning.models import FailureAttribution, InterventionDelta
from app.domains.learning.schemas import (
    ArtifactCreate,
    ArtifactOut,
    AttributionAnalyzeRequest,
    AttributionOut,
    AttributionStatusUpdate,
)
from app.domains.learning.service import create_artifact
from app.domains.workflows.tasks.models import TaskInstance, TaskStep

router = APIRouter(prefix="/attributions", tags=["失败归因"])


async def _get_attribution(
    db: DbSession, tenant_id: int, attribution_id: int
) -> FailureAttribution:
    attribution = await db.scalar(
        select(FailureAttribution).where(
            FailureAttribution.id == attribution_id,
            FailureAttribution.tenant_id == tenant_id,
        )
    )
    if attribution is None:
        raise NotFoundError("归因记录不存在")
    return attribution


def _decorate(data: dict) -> dict:
    label, route = route_label(data.get("category", "unknown"))
    return {**data, "category_label": label, "route": route}


@router.get("", summary="失败归因列表")
async def list_attributions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    instance_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
):
    conditions = [FailureAttribution.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(FailureAttribution.employee_id == employee_id)
    if instance_id is not None:
        conditions.append(FailureAttribution.instance_id == instance_id)
    if category:
        conditions.append(FailureAttribution.category == category)
    if status:
        conditions.append(FailureAttribution.status == status)

    stmt = select(FailureAttribution).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(FailureAttribution.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    data = [
        _decorate(AttributionOut.model_validate(item).model_dump(mode="json"))
        for item in items
    ]
    return paged(data, total, page, page_size)


@router.post("/analyze", summary="归因一次失败（任务或接管增量）")
async def analyze(
    payload: AttributionAnalyzeRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.instance_id is None and payload.intervention_id is None:
        raise BadRequestError("需要提供 instance_id 或 intervention_id")

    if payload.instance_id is not None:
        instance = await db.scalar(
            select(TaskInstance).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == current_user.tenant_id,
            )
        )
        if instance is None:
            raise NotFoundError("任务实例不存在")
        if payload.persist:
            attribution = await attribute_instance_failure(
                db,
                instance,
                error=instance.error,
                user_id=current_user.id,
                use_llm=payload.use_llm,
            )
            await record_audit(
                db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                employee_id=attribution.employee_id,
                action="attribution.create",
                resource_type="failure_attribution",
                resource_id=attribution.id,
                detail={
                    "category": attribution.category,
                    "source": attribution.source,
                    "instance_id": instance.id,
                },
                ip_address=client_ip(request),
            )
            return success(
                _decorate(AttributionOut.model_validate(attribution).model_dump(mode="json"))
            )
        steps = list(
            (
                await db.scalars(
                    select(TaskStep).where(TaskStep.instance_id == instance.id)
                )
            ).all()
        )
        result = None
        if payload.use_llm:
            result = await classify_failure_llm(
                instance=instance, steps=steps, error=instance.error
            )
        return success(
            _decorate(
                result
                if result is not None
                else classify_failure(
                    instance=instance, steps=steps, error=instance.error
                )
            )
        )

    intervention = await db.scalar(
        select(InterventionDelta).where(
            InterventionDelta.id == payload.intervention_id,
            InterventionDelta.tenant_id == current_user.tenant_id,
        )
    )
    if intervention is None:
        raise NotFoundError("接管增量不存在")
    if payload.persist:
        attribution = await attribute_intervention(
            db, intervention, user_id=current_user.id, use_llm=payload.use_llm
        )
        intervention.status = "attributed"
        await record_audit(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            employee_id=attribution.employee_id,
            action="attribution.create",
            resource_type="failure_attribution",
            resource_id=attribution.id,
            detail={
                "category": attribution.category,
                "source": attribution.source,
                "intervention_id": intervention.id,
            },
            ip_address=client_ip(request),
        )
        return success(
            _decorate(AttributionOut.model_validate(attribution).model_dump(mode="json"))
        )
    result = None
    if payload.use_llm:
        result = await classify_failure_llm(intervention=intervention)
    return success(
        _decorate(
            result if result is not None else classify_failure(intervention=intervention)
        )
    )


@router.get("/{attribution_id}", summary="归因详情")
async def get_attribution(
    attribution_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    attribution = await _get_attribution(db, current_user.tenant_id, attribution_id)
    return success(
        _decorate(AttributionOut.model_validate(attribution).model_dump(mode="json"))
    )


@router.post("/{attribution_id}/reanalyze-llm", summary="用 LLM 复核归因")
async def reanalyze_with_llm(
    attribution_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    attribution = await _get_attribution(db, current_user.tenant_id, attribution_id)
    try:
        await reanalyze_attribution_llm(
            db, attribution, user_id=current_user.id
        )
    except LLMError as exc:
        raise BadRequestError(str(exc)) from exc
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=attribution.employee_id,
        action="attribution.reanalyze_llm",
        resource_type="failure_attribution",
        resource_id=attribution.id,
        detail={
            "category": attribution.category,
            "confidence": attribution.confidence,
        },
        ip_address=client_ip(request),
    )
    return success(
        _decorate(AttributionOut.model_validate(attribution).model_dump(mode="json"))
    )


@router.patch("/{attribution_id}", summary="更新归因状态")
async def update_attribution(
    attribution_id: int,
    payload: AttributionStatusUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    attribution = await _get_attribution(db, current_user.tenant_id, attribution_id)
    attribution.status = payload.status
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=attribution.employee_id,
        action="attribution.status",
        resource_type="failure_attribution",
        resource_id=attribution.id,
        detail={"status": payload.status},
        ip_address=client_ip(request),
    )
    return success(
        _decorate(AttributionOut.model_validate(attribution).model_dump(mode="json"))
    )


@router.post("/{attribution_id}/artifact", summary="把归因结果转为学习工件")
async def artifact_from_attribution(
    attribution_id: int,
    payload: ArtifactCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    attribution = await _get_attribution(db, current_user.tenant_id, attribution_id)
    if attribution.category == "permission_violation":
        raise BadRequestError("越权/合规类失败禁止进入学习，请直接收紧权限并告警")

    defaults = attribution_artifact_payload(attribution)
    provided = payload.model_fields_set
    artifact_payload = payload.model_copy(
        update={
            "employee_id": payload.employee_id or defaults["employee_id"],
            "source": {**defaults["source"], **payload.source},
            "attribution": (
                payload.attribution if "attribution" in provided else defaults["attribution"]
            ),
            "target_layer": (
                payload.target_layer if "target_layer" in provided else defaults["target_layer"]
            ),
            "proposal": payload.proposal if "proposal" in provided else defaults["proposal"],
            "evidence": payload.evidence if "evidence" in provided else defaults["evidence"],
            "risk": payload.risk if "risk" in provided else defaults["risk"],
            "scope": payload.scope if "scope" in provided else defaults["scope"],
        }
    )
    artifact = create_artifact(
        artifact_payload, tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    db.add(artifact)
    await db.flush()
    attribution.artifact_id = artifact.id
    attribution.status = "artifact_created"
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=artifact.employee_id,
        action="artifact.create_from_attribution",
        resource_type="learning_artifact",
        resource_id=artifact.id,
        detail={"attribution_id": attribution.id, "category": attribution.category},
        ip_address=client_ip(request),
    )
    return success(ArtifactOut.model_validate(artifact).model_dump(mode="json"))
