from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.models import LearningArtifact, OutcomeEvent
from app.domains.learning.schemas import OutcomeCreate, OutcomeOut
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/outcome-events", tags=["业务结果回执"])


async def _validate_links(
    db: DbSession, tenant_id: int, payload: OutcomeCreate
) -> None:
    if payload.employee_id is not None:
        await get_employee(db, tenant_id, payload.employee_id)
    if payload.instance_id is not None:
        exists = await db.scalar(
            select(TaskInstance.id).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == tenant_id,
            )
        )
        if exists is None:
            raise NotFoundError("任务实例不存在")
    if payload.artifact_id is not None:
        exists = await db.scalar(
            select(LearningArtifact.id).where(
                LearningArtifact.id == payload.artifact_id,
                LearningArtifact.tenant_id == tenant_id,
            )
        )
        if exists is None:
            raise NotFoundError("学习工件不存在")


@router.get("", summary="业务结果回执列表")
async def list_outcomes(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    outcome_type: str | None = None,
    success: bool | None = None,
):
    conditions = [OutcomeEvent.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(OutcomeEvent.employee_id == employee_id)
    if outcome_type:
        conditions.append(OutcomeEvent.outcome_type == outcome_type)
    if success is not None:
        conditions.append(OutcomeEvent.success.is_(success))
    stmt = select(OutcomeEvent).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(OutcomeEvent.occurred_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [OutcomeOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="记录业务结果回执")
async def create_outcome(
    payload: OutcomeCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await _validate_links(db, current_user.tenant_id, payload)
    event = OutcomeEvent(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(exclude={"occurred_at"}),
    )
    if payload.occurred_at is not None:
        event.occurred_at = payload.occurred_at
    db.add(event)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=event.employee_id,
        action="outcome.create",
        resource_type="outcome_event",
        resource_id=event.id,
        detail={
            "outcome_type": event.outcome_type,
            "success": event.success,
            "value": event.value,
        },
        ip_address=client_ip(request),
    )
    return success(OutcomeOut.model_validate(event).model_dump(mode="json"))


@router.get("/stats", summary="业务结果统计")
async def outcome_stats(
    db: DbSession,
    current_user: CurrentUser,
    employee_id: int | None = None,
):
    conditions = [OutcomeEvent.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(OutcomeEvent.employee_id == employee_id)
    rows = await db.execute(
        select(
            OutcomeEvent.outcome_type,
            OutcomeEvent.success,
            func.count(OutcomeEvent.id),
        )
        .where(*conditions)
        .group_by(OutcomeEvent.outcome_type, OutcomeEvent.success)
    )
    counts: dict[str, dict[str, int]] = {}
    for outcome_type, is_success, count in rows:
        bucket = counts.setdefault(str(outcome_type), {"total": 0, "success": 0})
        bucket["total"] += int(count)
        if is_success:
            bucket["success"] += int(count)
    data = {}
    for outcome_type, bucket in counts.items():
        total = bucket["total"]
        data[outcome_type] = {
            "total": total,
            "success": bucket["success"],
            "success_rate": round(bucket["success"] / total, 4) if total else 0.0,
        }
    return success({"employee_id": employee_id, "outcomes": data})
