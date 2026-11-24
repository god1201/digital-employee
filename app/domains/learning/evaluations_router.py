from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.learning.evaluation import run_suite
from app.domains.learning.models import (
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
)
from app.domains.learning.schemas import (
    EvaluationCaseCreate,
    EvaluationCaseOut,
    EvaluationCaseUpdate,
    EvaluationRunOut,
    EvaluationRunRequest,
    EvaluationSuiteCreate,
    EvaluationSuiteOut,
    EvaluationSuiteUpdate,
)
from app.domains.workforce.employees.service import get_employee
from app.domains.workforce.prompting import build_employee_prompt

router = APIRouter(tags=["综合评估"])


async def _get_suite(
    db: DbSession, tenant_id: int, suite_id: int
) -> EvaluationSuite:
    suite = await db.scalar(
        select(EvaluationSuite).where(
            EvaluationSuite.id == suite_id, EvaluationSuite.tenant_id == tenant_id
        )
    )
    if suite is None:
        raise NotFoundError("评估套件不存在")
    return suite


async def _get_case(
    db: DbSession, tenant_id: int, case_id: int
) -> tuple[EvaluationCase, EvaluationSuite]:
    case = await db.get(EvaluationCase, case_id)
    if case is None:
        raise NotFoundError("评估用例不存在")
    suite = await _get_suite(db, tenant_id, case.suite_id)
    return case, suite


@router.get("/evaluation-suites", summary="评估套件列表")
async def list_suites(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    employee_id: int | None = None,
    enabled: bool | None = None,
):
    conditions = [EvaluationSuite.tenant_id == current_user.tenant_id]
    if employee_id is not None:
        conditions.append(EvaluationSuite.employee_id == employee_id)
    if enabled is not None:
        conditions.append(EvaluationSuite.enabled.is_(enabled))

    stmt = select(EvaluationSuite).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(EvaluationSuite.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [EvaluationSuiteOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/evaluation-suites", summary="创建评估套件")
async def create_suite(
    payload: EvaluationSuiteCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.employee_id is not None:
        await get_employee(db, current_user.tenant_id, payload.employee_id)
    exists = await db.scalar(
        select(EvaluationSuite.id).where(
            EvaluationSuite.tenant_id == current_user.tenant_id,
            EvaluationSuite.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("评估套件编码已存在")

    suite = EvaluationSuite(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(suite)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=suite.employee_id,
        action="evaluation_suite.create",
        resource_type="evaluation_suite",
        resource_id=suite.id,
        detail={"code": suite.code, "threshold": suite.threshold},
        ip_address=client_ip(request),
    )
    return success(EvaluationSuiteOut.model_validate(suite).model_dump(mode="json"))


@router.get("/evaluation-suites/{suite_id}", summary="评估套件详情")
async def get_suite(
    suite_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    cases = list(
        (
            await db.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.suite_id == suite.id)
                .order_by(EvaluationCase.id)
            )
        ).all()
    )
    data = EvaluationSuiteOut.model_validate(suite).model_dump(mode="json")
    data["cases"] = [
        EvaluationCaseOut.model_validate(item).model_dump(mode="json") for item in cases
    ]
    return success(data)


@router.patch("/evaluation-suites/{suite_id}", summary="更新评估套件")
async def update_suite(
    suite_id: int,
    payload: EvaluationSuiteUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(suite, field, value)
    await db.flush()
    return success(EvaluationSuiteOut.model_validate(suite).model_dump(mode="json"))


@router.delete("/evaluation-suites/{suite_id}", summary="停用评估套件")
async def disable_suite(
    suite_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    suite.enabled = False
    await db.flush()
    return success(None, "评估套件已停用")


@router.get("/evaluation-suites/{suite_id}/cases", summary="评估用例列表")
async def list_cases(
    suite_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    items = list(
        (
            await db.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.suite_id == suite.id)
                .order_by(EvaluationCase.id)
            )
        ).all()
    )
    return success(
        [EvaluationCaseOut.model_validate(item).model_dump(mode="json") for item in items]
    )


@router.post("/evaluation-suites/{suite_id}/cases", summary="新增评估用例")
async def create_case(
    suite_id: int,
    payload: EvaluationCaseCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    case = EvaluationCase(suite_id=suite.id, **payload.model_dump())
    db.add(case)
    await db.flush()
    return success(EvaluationCaseOut.model_validate(case).model_dump(mode="json"))


@router.patch("/evaluation-cases/{case_id}", summary="更新评估用例")
async def update_case(
    case_id: int,
    payload: EvaluationCaseUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    case, _suite = await _get_case(db, current_user.tenant_id, case_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(case, field, value)
    await db.flush()
    return success(EvaluationCaseOut.model_validate(case).model_dump(mode="json"))


@router.delete("/evaluation-cases/{case_id}", summary="停用评估用例")
async def disable_case(
    case_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    case, _suite = await _get_case(db, current_user.tenant_id, case_id)
    case.enabled = False
    await db.flush()
    return success(None, "评估用例已停用")


@router.post("/evaluation-suites/{suite_id}/run", summary="执行综合评估")
async def run_evaluation(
    suite_id: int,
    payload: EvaluationRunRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    suite = await _get_suite(db, current_user.tenant_id, suite_id)
    employee = None
    system_prompt = ""
    if suite.employee_id is not None:
        employee = await get_employee(db, current_user.tenant_id, suite.employee_id)
        system_prompt = await build_employee_prompt(
            db, suite.tenant_id, employee
        )

    run = await run_suite(
        db,
        suite,
        employee=employee,
        system_prompt=system_prompt,
        trigger="manual",
        outputs=payload.outputs,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=suite.employee_id,
        action="evaluation.run",
        resource_type="evaluation_run",
        resource_id=run.id,
        detail={"suite_id": suite.id, "score": run.score, "passed": run.passed},
        ip_address=client_ip(request),
    )
    return success(EvaluationRunOut.model_validate(run).model_dump(mode="json"))


@router.get("/evaluation-runs", summary="评估执行记录")
async def list_runs(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    suite_id: int | None = None,
    employee_id: int | None = None,
    status: str | None = None,
):
    conditions = [EvaluationRun.tenant_id == current_user.tenant_id]
    if suite_id is not None:
        conditions.append(EvaluationRun.suite_id == suite_id)
    if employee_id is not None:
        conditions.append(EvaluationRun.employee_id == employee_id)
    if status:
        conditions.append(EvaluationRun.status == status)

    stmt = select(EvaluationRun).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(EvaluationRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [EvaluationRunOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.get("/evaluation-runs/{run_id}", summary="评估执行详情")
async def get_run(
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    run = await db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id,
            EvaluationRun.tenant_id == current_user.tenant_id,
        )
    )
    if run is None:
        raise NotFoundError("评估记录不存在")
    return success(EvaluationRunOut.model_validate(run).model_dump(mode="json"))
