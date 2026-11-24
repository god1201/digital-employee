from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.core.response import paged, success
from app.domains.learning.implicit import implicit_summary, record_signal
from app.domains.learning.models import ImplicitSignal
from app.domains.learning.schemas import ImplicitSignalCreate, ImplicitSignalOut
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/implicit-signals", tags=["隐式学习信号"])


@router.get("", summary="隐式信号列表")
async def list_signals(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    signal_type: str | None = None,
):
    conditions = [ImplicitSignal.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(ImplicitSignal.employee_id == employee_id)
    if signal_type:
        conditions.append(ImplicitSignal.signal_type == signal_type)
    stmt = select(ImplicitSignal).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ImplicitSignal.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [ImplicitSignalOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="记录隐式信号")
async def create_signal(
    payload: ImplicitSignalCreate,
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
    signal = await record_signal(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    return success(ImplicitSignalOut.model_validate(signal).model_dump(mode="json"))


@router.get("/stats", summary="隐式信号统计")
async def signal_stats(
    db: DbSession,
    current_user: CurrentUser,
    employee_id: int | None = None,
):
    if employee_id is not None:
        await get_employee(db, current_user.tenant_id, employee_id)
    return success(
        await implicit_summary(db, current_user.tenant_id, employee_id)
    )
