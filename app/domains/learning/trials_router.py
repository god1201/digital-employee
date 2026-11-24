from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.models import (
    EmployeeTrial,
    FailureAttribution,
    InterventionDelta,
    LearningArtifact,
)
from app.domains.learning.schemas import TrialCreate, TrialOut
from app.domains.learning.trials import build_profile, build_trend, build_trial
from app.domains.workforce.employees.service import get_employee

router = APIRouter(tags=["试运行与认证"])


@router.post("/digital-employees/{employee_id}/trials", summary="发起影子试运行/上岗认证")
async def start_trial(
    employee_id: int,
    payload: TrialCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    trial = await build_trial(
        db,
        employee,
        mode=payload.mode,
        sample_size=payload.sample_size,
        threshold=payload.threshold,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="employee.trial",
        resource_type="employee_trial",
        resource_id=trial.id,
        detail={
            "mode": trial.mode,
            "status": trial.status,
            "score": (trial.metrics or {}).get("score"),
            "decision": trial.decision,
        },
        ip_address=client_ip(request),
    )
    return success(TrialOut.model_validate(trial).model_dump(mode="json"))


@router.get("/digital-employees/{employee_id}/trials", summary="试运行记录")
async def list_trials(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    await get_employee(db, current_user.tenant_id, employee_id)
    items = list(
        (
            await db.scalars(
                select(EmployeeTrial)
                .where(
                    EmployeeTrial.tenant_id == current_user.tenant_id,
                    EmployeeTrial.employee_id == employee_id,
                )
                .order_by(EmployeeTrial.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return success(
        [TrialOut.model_validate(item).model_dump(mode="json") for item in items]
    )


@router.get("/trials", summary="全部试运行记录")
async def list_all_trials(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    mode: str | None = None,
    status: str | None = None,
):
    conditions = [EmployeeTrial.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(EmployeeTrial.employee_id == employee_id)
    if mode:
        conditions.append(EmployeeTrial.mode == mode)
    if status:
        conditions.append(EmployeeTrial.status == status)

    stmt = select(EmployeeTrial).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(EmployeeTrial.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TrialOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.get("/trials/{trial_id}", summary="试运行详情")
async def get_trial(
    trial_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    trial = await db.scalar(
        select(EmployeeTrial).where(
            EmployeeTrial.id == trial_id,
            EmployeeTrial.tenant_id == current_user.tenant_id,
        )
    )
    if trial is None:
        raise NotFoundError("试运行记录不存在")
    return success(TrialOut.model_validate(trial).model_dump(mode="json"))


@router.get("/timeline", summary="调教台时间线（接管/工件/归因/试运行）")
async def learning_timeline(
    db: DbSession,
    current_user: CurrentUser,
    employee_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    items: list[tuple[object, dict]] = []

    intervention_conditions = [InterventionDelta.tenant_id == current_user.tenant_id]
    artifact_conditions = [LearningArtifact.tenant_id == current_user.tenant_id]
    attribution_conditions = [FailureAttribution.tenant_id == current_user.tenant_id]
    trial_conditions = [EmployeeTrial.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        intervention_conditions.append(InterventionDelta.employee_id == employee_id)
        artifact_conditions.append(LearningArtifact.employee_id == employee_id)
        attribution_conditions.append(FailureAttribution.employee_id == employee_id)
        trial_conditions.append(EmployeeTrial.employee_id == employee_id)

    interventions = list(
        (
            await db.scalars(
                select(InterventionDelta)
                .where(*intervention_conditions)
                .order_by(InterventionDelta.id.desc())
                .limit(limit)
            )
        ).all()
    )
    for item in interventions:
        items.append(
            (
                item.created_at,
                {
                    "type": "intervention",
                    "id": item.id,
                    "employee_id": item.employee_id,
                    "title": f"接管增量 #{item.id}",
                    "status": item.status,
                    "category": item.source_type,
                    "summary": f"{len(item.diff or [])} 处变更",
                    "created_at": item.created_at.isoformat(),
                },
            )
        )

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
    for item in artifacts:
        items.append(
            (
                item.created_at,
                {
                    "type": "artifact",
                    "id": item.id,
                    "employee_id": item.employee_id,
                    "title": f"学习工件 #{item.id}",
                    "status": item.status,
                    "category": item.attribution,
                    "summary": f"v{item.version} · {item.target_layer}",
                    "created_at": item.created_at.isoformat(),
                },
            )
        )

    attributions = list(
        (
            await db.scalars(
                select(FailureAttribution)
                .where(*attribution_conditions)
                .order_by(FailureAttribution.id.desc())
                .limit(limit)
            )
        ).all()
    )
    for item in attributions:
        items.append(
            (
                item.created_at,
                {
                    "type": "attribution",
                    "id": item.id,
                    "employee_id": item.employee_id,
                    "title": f"失败归因 #{item.id}",
                    "status": item.status,
                    "category": item.category,
                    "summary": item.suggestion,
                    "created_at": item.created_at.isoformat(),
                },
            )
        )

    trials = list(
        (
            await db.scalars(
                select(EmployeeTrial)
                .where(*trial_conditions)
                .order_by(EmployeeTrial.id.desc())
                .limit(limit)
            )
        ).all()
    )
    for item in trials:
        items.append(
            (
                item.created_at,
                {
                    "type": "trial",
                    "id": item.id,
                    "employee_id": item.employee_id,
                    "title": f"试运行 #{item.id}",
                    "status": item.status,
                    "category": item.mode,
                    "summary": f"{(item.metrics or {}).get('score', 0)} / {item.decision or '—'}",
                    "created_at": item.created_at.isoformat(),
                },
            )
        )

    items.sort(key=lambda pair: pair[0], reverse=True)
    return success([item for _created_at, item in items[:limit]])


@router.get("/digital-employees/{employee_id}/profile", summary="员工数字履历")
async def employee_profile(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(await build_profile(db, employee))


@router.get(
    "/digital-employees/{employee_id}/profile/trend",
    summary="员工学习曲线（按天聚合）",
)
async def employee_profile_trend(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(30, ge=1, le=90),
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    return success(await build_trend(db, employee, days=days))
