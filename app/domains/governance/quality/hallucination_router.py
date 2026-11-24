from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.governance.quality.hallucination import run_check
from app.domains.governance.quality.models import HallucinationCheck
from app.domains.governance.quality.schemas import (
    HallucinationCheckOut,
    HallucinationCheckRequest,
)
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/hallucination", tags=["幻觉检测"])


@router.post("/check", summary="检测答案是否有来源支撑")
async def check_hallucination(
    payload: HallucinationCheckRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    if payload.instance_id is not None:
        exists = await db.scalar(
            select(TaskInstance.id).where(
                TaskInstance.id == payload.instance_id,
                TaskInstance.tenant_id == current_user.tenant_id,
            )
        )
        if exists is None:
            raise NotFoundError("任务实例不存在")
    record = await run_check(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=record.employee_id,
        action="hallucination.check",
        resource_type="hallucination_check",
        resource_id=record.id,
        detail={"score": record.score, "grounded": record.grounded},
        ip_address=client_ip(request),
    )
    return success(HallucinationCheckOut.model_validate(record).model_dump(mode="json"))


@router.get("/checks", summary="幻觉检测记录")
async def list_checks(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    grounded: bool | None = None,
):
    conditions = [HallucinationCheck.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(HallucinationCheck.employee_id == employee_id)
    if grounded is not None:
        conditions.append(HallucinationCheck.grounded.is_(grounded))
    stmt = select(HallucinationCheck).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(HallucinationCheck.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [
            HallucinationCheckOut.model_validate(item).model_dump(mode="json")
            for item in items
        ],
        total,
        page,
        page_size,
    )
