from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import NotFoundError
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.tools.models import Tool
from app.domains.workforce.contracts.schemas import (
    ContractCheckRequest,
    ContractDecisionOut,
    JobContractOut,
    JobContractUpsert,
)
from app.domains.workforce.contracts.service import (
    evaluate_tool_call,
    get_active_contract,
    get_contract,
    upsert_contract,
)
from app.domains.workforce.employees.service import get_employee

router = APIRouter(prefix="/digital-employees", tags=["岗位契约"])


@router.get("/{employee_id}/contract", summary="获取岗位契约")
async def read_contract(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    contract = await get_contract(db, current_user.tenant_id, employee_id)
    if contract is None:
        raise NotFoundError("该员工尚未配置岗位契约")
    return success(JobContractOut.model_validate(contract).model_dump(mode="json"))


@router.put(
    "/{employee_id}/contract",
    summary="保存岗位契约（仅管理员可改）",
    dependencies=[Depends(get_current_admin)],
)
async def save_contract(
    employee_id: int,
    payload: JobContractUpsert,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    contract = await upsert_contract(
        db,
        current_user.tenant_id,
        employee_id,
        payload,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="contract.update",
        resource_type="job_contract",
        resource_id=contract.id,
        detail={
            "version": contract.version,
            "autonomy_level": contract.autonomy_level,
            "fields": sorted(payload.model_fields_set),
        },
        ip_address=client_ip(request),
    )
    return success(JobContractOut.model_validate(contract).model_dump(mode="json"))


@router.post("/{employee_id}/contract/check", summary="预检一次工具调用是否触碰契约")
async def check_contract(
    employee_id: int,
    payload: ContractCheckRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    contract = await get_active_contract(db, current_user.tenant_id, employee_id)
    tool = await db.scalar(
        select(Tool).where(
            Tool.tenant_id == current_user.tenant_id,
            Tool.code == payload.tool_code,
        )
    )
    decision = evaluate_tool_call(
        contract,
        tool=tool,
        arguments=payload.arguments,
        step_name=payload.step_name,
        step_description=payload.step_description,
    )
    return success(ContractDecisionOut(**decision.as_dict()).model_dump(mode="json"))
