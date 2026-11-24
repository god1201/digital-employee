from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.core.response import success
from app.domains.workforce.employees.service import get_employee
from app.domains.workforce.routing import build_routing_context

router = APIRouter(prefix="/digital-employees", tags=["协作路由"])


@router.get("/{employee_id}/routing", summary="推荐该问谁（团队/岗位/技能）")
async def employee_routing(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    topic: str = Query("", max_length=200),
):
    await get_employee(db, current_user.tenant_id, employee_id)
    context = await build_routing_context(
        db, current_user.tenant_id, employee_id, topic=topic
    )
    return success(
        {"employee_id": employee_id, "topic": topic, "context": context}
    )
