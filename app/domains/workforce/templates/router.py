from fastapi import APIRouter, Depends, Request

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.employees.service import get_employee
from app.domains.workforce.templates.schemas import (
    ApplyTemplateRequest,
    ApplyTemplateResult,
    JobTemplateOut,
)
from app.domains.workforce.templates.service import (
    apply_template,
    get_template,
    list_templates,
)

router = APIRouter(tags=["岗位模板"])


@router.get("/job-templates", summary="岗位模板列表")
async def list_job_templates(
    db: DbSession,
    current_user: CurrentUser,
):
    items = await list_templates(db, current_user.tenant_id)
    return success(
        [JobTemplateOut.model_validate(item).model_dump(mode="json") for item in items]
    )


@router.get("/job-templates/{code}", summary="岗位模板详情")
async def get_job_template(
    code: str,
    db: DbSession,
    current_user: CurrentUser,
):
    template = await get_template(db, current_user.tenant_id, code)
    return success(JobTemplateOut.model_validate(template).model_dump(mode="json"))


@router.post(
    "/digital-employees/{employee_id}/apply-job-template",
    summary="按岗位模板装配员工",
    dependencies=[Depends(get_current_admin)],
)
async def apply_job_template(
    employee_id: int,
    payload: ApplyTemplateRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    result = await apply_template(
        db, current_user.tenant_id, employee, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="job_template.apply",
        resource_type="job_template",
        detail={
            "template": payload.template_code,
            "skills": result["skills"],
            "persona": result["persona"],
            "contract": result["contract"],
            "knowledge_bases": result.get("knowledge_bases", {}),
        },
        ip_address=client_ip(request),
    )
    return success(
        ApplyTemplateResult(
            template=JobTemplateOut.model_validate(result["template"]),
            skills=result["skills"],
            persona=result["persona"],
            contract=result["contract"],
            knowledge_bases=result.get("knowledge_bases", {}),
            notes=result["notes"],
        ).model_dump(mode="json")
    )
