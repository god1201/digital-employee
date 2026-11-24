from fastapi import APIRouter, Depends, Request

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import NotFoundError
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.employees.service import get_employee
from app.domains.workforce.persona.schemas import PersonaOut, PersonaUpsert
from app.domains.workforce.persona.service import (
    build_persona_context,
    get_persona,
    upsert_persona,
)

router = APIRouter(prefix="/digital-employees", tags=["人格风格"])


@router.get("/{employee_id}/persona", summary="获取人格风格")
async def read_persona(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    persona = await get_persona(db, current_user.tenant_id, employee_id)
    if persona is None:
        raise NotFoundError("该员工尚未配置人格风格")
    return success(PersonaOut.model_validate(persona).model_dump(mode="json"))


@router.put(
    "/{employee_id}/persona",
    summary="保存人格风格（仅管理员）",
    dependencies=[Depends(get_current_admin)],
)
async def save_persona(
    employee_id: int,
    payload: PersonaUpsert,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    persona = await upsert_persona(
        db, current_user.tenant_id, employee_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="persona.update",
        resource_type="persona_profile",
        resource_id=persona.id,
        detail={"version": persona.version, "tone": persona.tone},
        ip_address=client_ip(request),
    )
    return success(PersonaOut.model_validate(persona).model_dump(mode="json"))


@router.get("/{employee_id}/persona/context", summary="查看人格层上下文")
async def persona_context(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    persona = await get_persona(db, current_user.tenant_id, employee_id)
    return success(
        {
            "employee_id": employee_id,
            "configured": persona is not None,
            "context": build_persona_context(persona),
        }
    )
