from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import NotFoundError
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.fewshot import build_few_shot_context
from app.domains.learning.models import FewShotExample
from app.domains.learning.onboarding import (
    apply_contract_draft,
    extract_contract,
    import_knowledge_document,
    result_payload,
)
from app.domains.learning.schemas import (
    FewShotBulkCreate,
    FewShotCreate,
    FewShotOut,
    FewShotUpdate,
    OnboardingImportRequest,
)
from app.domains.workforce.contracts.service import get_contract
from app.domains.workforce.employees.service import get_employee

router = APIRouter(tags=["入职引导"])


async def _get_example(
    db: DbSession, tenant_id: int, example_id: int
) -> FewShotExample:
    example = await db.scalar(
        select(FewShotExample).where(
            FewShotExample.id == example_id,
            FewShotExample.tenant_id == tenant_id,
        )
    )
    if example is None:
        raise NotFoundError("示范案例不存在")
    return example


@router.post(
    "/digital-employees/{employee_id}/onboarding/import",
    summary="导入 JD/SOP，生成岗位契约草稿与知识文档",
    dependencies=[Depends(get_current_admin)],
)
async def onboarding_import(
    employee_id: int,
    payload: OnboardingImportRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    extracted = await extract_contract(payload.text, payload.source_type)
    contract_id = None
    document_id = None
    if payload.apply_contract:
        contract = await apply_contract_draft(
            db,
            current_user.tenant_id,
            employee.id,
            extracted,
            user_id=current_user.id,
        )
        contract_id = contract.id
    if payload.knowledge_base_id is not None:
        title = payload.title or f"入职资料 · {employee.name}"
        document = await import_knowledge_document(
            db,
            current_user.tenant_id,
            payload.knowledge_base_id,
            title,
            payload.text,
            user_id=current_user.id,
        )
        document_id = document.id
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee.id,
        action="onboarding.import",
        resource_type="digital_employee",
        resource_id=employee.id,
        detail={
            "source_type": payload.source_type,
            "contract_id": contract_id,
            "knowledge_document_id": document_id,
            "extracted_source": extracted.get("source"),
        },
        ip_address=client_ip(request),
    )
    return success(
        result_payload(
            extracted,
            contract_id=contract_id,
            knowledge_document_id=document_id,
        ).model_dump(mode="json")
    )


@router.get(
    "/digital-employees/{employee_id}/few-shot-examples",
    summary="示范案例列表",
)
async def list_examples(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    items = list(
        (
            await db.scalars(
                select(FewShotExample)
                .where(
                    FewShotExample.tenant_id == current_user.tenant_id,
                    FewShotExample.employee_id == employee_id,
                )
                .order_by(FewShotExample.id.desc())
            )
        ).all()
    )
    return success(
        [FewShotOut.model_validate(item).model_dump(mode="json") for item in items]
    )


@router.post(
    "/digital-employees/{employee_id}/few-shot-examples",
    summary="新增示范案例",
    dependencies=[Depends(get_current_admin)],
)
async def create_example(
    employee_id: int,
    payload: FewShotCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    example = FewShotExample(
        tenant_id=current_user.tenant_id,
        employee_id=employee_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(example)
    await db.flush()
    return success(FewShotOut.model_validate(example).model_dump(mode="json"))


@router.post(
    "/digital-employees/{employee_id}/onboarding/examples",
    summary="批量导入入职案例（20–50 条）",
    dependencies=[Depends(get_current_admin)],
)
async def bulk_examples(
    employee_id: int,
    payload: FewShotBulkCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    created = []
    for item in payload.examples:
        example = FewShotExample(
            tenant_id=current_user.tenant_id,
            employee_id=employee.id,
            created_by=current_user.id,
            **item.model_dump(),
        )
        db.add(example)
        created.append(example)
    await db.flush()
    return success(
        {
            "created": len(created),
            "examples": [
                FewShotOut.model_validate(item).model_dump(mode="json")
                for item in created
            ],
        }
    )


@router.patch(
    "/few-shot-examples/{example_id}",
    summary="更新示范案例",
    dependencies=[Depends(get_current_admin)],
)
async def update_example(
    example_id: int,
    payload: FewShotUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    example = await _get_example(db, current_user.tenant_id, example_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(example, field, value)
    await db.flush()
    return success(FewShotOut.model_validate(example).model_dump(mode="json"))


@router.delete(
    "/few-shot-examples/{example_id}",
    summary="停用示范案例",
    dependencies=[Depends(get_current_admin)],
)
async def disable_example(
    example_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    example = await _get_example(db, current_user.tenant_id, example_id)
    example.enabled = False
    await db.flush()
    return success(None, "示范案例已停用")


@router.get(
    "/digital-employees/{employee_id}/onboarding/status",
    summary="入职引导状态",
)
async def onboarding_status(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    contract = await get_contract(db, current_user.tenant_id, employee.id)
    example_count = int(
        await db.scalar(
            select(func.count(FewShotExample.id)).where(
                FewShotExample.tenant_id == current_user.tenant_id,
                FewShotExample.employee_id == employee.id,
                FewShotExample.enabled.is_(True),
            )
        )
        or 0
    )
    examples = list(
        (
            await db.scalars(
                select(FewShotExample)
                .where(
                    FewShotExample.tenant_id == current_user.tenant_id,
                    FewShotExample.employee_id == employee.id,
                    FewShotExample.enabled.is_(True),
                )
                .limit(3)
            )
        ).all()
    )
    return success(
        {
            "employee_id": employee.id,
            "contract": {
                "configured": contract is not None,
                "status": contract.status if contract else None,
                "role": contract.role if contract else None,
            },
            "few_shot_count": example_count,
            "few_shot_context": build_few_shot_context(examples),
            "certification": (employee.config or {}).get("certification"),
        }
    )
