from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, get_current_admin
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.marketplace.models import EmployeeSkill, SkillPackage
from app.domains.skills.marketplace.schemas import (
    EmployeeSkillOut,
    SkillCopyRequest,
    SkillInstallRequest,
    SkillInstallResult,
    SkillPackageCreate,
    SkillPackageOut,
    SkillPackageVersionCreate,
    SkillRecommendationOut,
    SkillToggleRequest,
    SkillUpgradeResult,
)
from app.domains.skills.marketplace.service import (
    build_skills_context,
    copy_skill,
    create_package,
    create_version,
    deprecate_package,
    install_skill,
    installed_rows,
    latest_package,
    list_latest_packages,
    list_versions,
    merge_permissions,
    recommend_skills,
    resolve_install_plan,
    serialize_skill,
    upgrade_skill,
)
from app.domains.workforce.employees.service import get_employee

router = APIRouter(tags=["技能市场"])


async def _get_package(db: DbSession, tenant_id: int, package_id: int) -> SkillPackage:
    package = await db.get(SkillPackage, package_id)
    if package is None or (package.tenant_id not in (None, tenant_id)):
        raise NotFoundError("技能包不存在")
    return package


@router.get("/skill-packages", summary="技能市场列表（每个编码返回最新版本）")
async def list_packages(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = None,
    keyword: str | None = None,
    include_drafts: bool = False,
):
    published_only = not (include_drafts and current_user.is_superuser)
    packages = await list_latest_packages(
        db,
        current_user.tenant_id,
        category=category,
        keyword=keyword,
        published_only=published_only,
    )
    total = len(packages)
    start = (page - 1) * page_size
    items = packages[start : start + page_size]
    return paged(
        [SkillPackageOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.get("/skill-packages/{code}", summary="技能包详情与版本列表")
async def get_package(
    code: str,
    db: DbSession,
    current_user: CurrentUser,
    version: int | None = Query(None, ge=1),
):
    package = await latest_package(
        db,
        current_user.tenant_id,
        code,
        version=version,
        published_only=not current_user.is_superuser,
    )
    if package is None:
        raise NotFoundError("技能包不存在或未发布")
    versions = await list_versions(db, current_user.tenant_id, code)
    data = SkillPackageOut.model_validate(package).model_dump(mode="json")
    data["versions"] = [
        {
            "id": item.id,
            "version": item.version,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
        }
        for item in versions
    ]
    return success(data)


@router.get("/skill-packages/{code}/versions", summary="技能包全部版本")
async def get_package_versions(
    code: str,
    db: DbSession,
    current_user: CurrentUser,
):
    versions = await list_versions(db, current_user.tenant_id, code)
    return success(
        [SkillPackageOut.model_validate(item).model_dump(mode="json") for item in versions]
    )


@router.post(
    "/skill-packages",
    summary="创建技能包（v1 草稿）",
    dependencies=[Depends(get_current_admin)],
)
async def create_package_endpoint(
    payload: SkillPackageCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    package = await create_package(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="skill_package.create",
        resource_type="skill_package",
        resource_id=package.id,
        detail={"code": package.code, "version": package.version},
        ip_address=client_ip(request),
    )
    return success(SkillPackageOut.model_validate(package).model_dump(mode="json"))


@router.post(
    "/skill-packages/{code}/versions",
    summary="创建技能包新版本",
    dependencies=[Depends(get_current_admin)],
)
async def create_version_endpoint(
    code: str,
    payload: SkillPackageVersionCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    package = await create_version(
        db, current_user.tenant_id, code, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="skill_package.version",
        resource_type="skill_package",
        resource_id=package.id,
        detail={"code": package.code, "version": package.version},
        ip_address=client_ip(request),
    )
    return success(SkillPackageOut.model_validate(package).model_dump(mode="json"))


@router.post(
    "/skill-packages/{package_id}/publish",
    summary="发布技能包版本",
    dependencies=[Depends(get_current_admin)],
)
async def publish_package(
    package_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    package = await _get_package(db, current_user.tenant_id, package_id)
    if package.tenant_id != current_user.tenant_id:
        raise ForbiddenError("不能修改平台内置技能包")
    # 发布前确认依赖可解析
    await resolve_install_plan(db, current_user.tenant_id, package.code, version=package.version)
    package.status = "published"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="skill_package.publish",
        resource_type="skill_package",
        resource_id=package.id,
        detail={"code": package.code, "version": package.version},
        ip_address=client_ip(request),
    )
    return success(SkillPackageOut.model_validate(package).model_dump(mode="json"))


@router.delete(
    "/skill-packages/{package_id}",
    summary="下架技能包版本",
    dependencies=[Depends(get_current_admin)],
)
async def deprecate_package_endpoint(
    package_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    package = await _get_package(db, current_user.tenant_id, package_id)
    if package.tenant_id != current_user.tenant_id:
        raise ForbiddenError("不能修改平台内置技能包")
    deprecate_package(package)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="skill_package.deprecate",
        resource_type="skill_package",
        resource_id=package.id,
        detail={"code": package.code, "version": package.version},
        ip_address=client_ip(request),
    )
    return success(None, "技能包版本已下架")


@router.get("/digital-employees/{employee_id}/skills", summary="员工已装配技能")
async def list_employee_skills(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    rows = await installed_rows(db, current_user.tenant_id, employee_id)
    return success([serialize_skill(skill, package) for skill, package in rows])


@router.get("/digital-employees/{employee_id}/skills/context", summary="员工技能装配上下文")
async def employee_skills_context(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    rows = await installed_rows(db, current_user.tenant_id, employee_id)
    active = [package for skill, package in rows if skill.status == "active"]
    return success(
        {
            "employee_id": employee_id,
            "count": len(active),
            "context": await build_skills_context(
                db, current_user.tenant_id, employee_id
            ),
            "permissions": merge_permissions(active),
        }
    )


@router.get("/digital-employees/{employee_id}/skills/recommend", summary="技能组合推荐")
async def recommend(
    employee_id: int,
    db: DbSession,
    current_user: CurrentUser,
    need: str = Query(..., min_length=1, max_length=200),
    use_llm: bool = Query(False),
):
    await get_employee(db, current_user.tenant_id, employee_id)
    items = await recommend_skills(
        db, current_user.tenant_id, employee_id, need, use_llm=use_llm
    )
    return success(
        [SkillRecommendationOut(**item).model_dump(mode="json") for item in items]
    )


@router.post("/digital-employees/{employee_id}/skills", summary="安装技能（自动解析依赖）")
async def install(
    employee_id: int,
    payload: SkillInstallRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    result = await install_skill(
        db, current_user.tenant_id, employee_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="skill.install",
        resource_type="employee_skill",
        detail={
            "code": payload.code,
            "installed": [item["skill_code"] for item in result["installed"]],
            "warnings": result["warnings"],
        },
        ip_address=client_ip(request),
    )
    return success(
        SkillInstallResult(
            installed=[EmployeeSkillOut(**item) for item in result["installed"]],
            warnings=result["warnings"],
            permissions=result["permissions"],
        ).model_dump(mode="json")
    )


@router.post("/digital-employees/{employee_id}/skills/copy", summary="从其他员工复制技能")
async def copy(
    employee_id: int,
    payload: SkillCopyRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    await get_employee(db, current_user.tenant_id, payload.source_employee_id)
    result = await copy_skill(
        db,
        current_user.tenant_id,
        employee_id,
        payload.source_employee_id,
        payload.skill_code,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="skill.copy",
        resource_type="employee_skill",
        detail={
            "code": payload.skill_code,
            "source_employee_id": payload.source_employee_id,
        },
        ip_address=client_ip(request),
    )
    return success(
        SkillInstallResult(
            installed=[EmployeeSkillOut(**item) for item in result["installed"]],
            warnings=result["warnings"],
            permissions=result["permissions"],
        ).model_dump(mode="json")
    )


@router.delete(
    "/digital-employees/{employee_id}/skills/{skill_code}",
    summary="停用已装配技能",
)
async def disable_skill(
    employee_id: int,
    skill_code: str,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    skill = await db.scalar(
        select(EmployeeSkill).where(
            EmployeeSkill.tenant_id == current_user.tenant_id,
            EmployeeSkill.employee_id == employee_id,
            EmployeeSkill.skill_code == skill_code,
        )
    )
    if skill is None:
        raise NotFoundError("员工未装配该技能")
    skill.status = "disabled"
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="skill.disable",
        resource_type="employee_skill",
        resource_id=skill.id,
        detail={"code": skill_code},
        ip_address=client_ip(request),
    )
    return success(None, "技能已停用")


@router.post(
    "/digital-employees/{employee_id}/skills/{skill_code}/toggle",
    summary="启用/停用已装配技能",
)
async def toggle_skill(
    employee_id: int,
    skill_code: str,
    payload: SkillToggleRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    await get_employee(db, current_user.tenant_id, employee_id)
    skill = await db.scalar(
        select(EmployeeSkill).where(
            EmployeeSkill.tenant_id == current_user.tenant_id,
            EmployeeSkill.employee_id == employee_id,
            EmployeeSkill.skill_code == skill_code,
        )
    )
    if skill is None:
        raise NotFoundError("员工未装配该技能")
    skill.status = "active" if payload.enabled else "disabled"
    await db.flush()
    return success(None, "技能状态已更新")


@router.post(
    "/digital-employees/{employee_id}/skills/{skill_code}/upgrade",
    summary="升级技能（有评估套件时自动回归）",
)
async def upgrade(
    employee_id: int,
    skill_code: str,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    employee = await get_employee(db, current_user.tenant_id, employee_id)
    result = await upgrade_skill(
        db, current_user.tenant_id, employee, skill_code, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="skill.upgrade",
        resource_type="employee_skill",
        detail={
            "code": skill_code,
            "version": result["skill"]["version"],
            "runs": result["runs"],
        },
        ip_address=client_ip(request),
    )
    return success(
        SkillUpgradeResult(
            skill=EmployeeSkillOut(**result["skill"]),
            runs=result["runs"],
            warnings=result["warnings"],
        ).model_dump(mode="json")
    )
