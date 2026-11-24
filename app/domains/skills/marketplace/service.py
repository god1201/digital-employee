"""技能市场服务：版本、依赖、冲突、权限并集与员工装配。"""

import json
import logging
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.llm import LLMError, chat_json, is_configured
from app.domains.governance.audit.service import record_audit
from app.domains.learning.evaluation import run_suite, suites_for_employee
from app.domains.skills.marketplace.models import EmployeeSkill, SkillPackage
from app.domains.skills.marketplace.schemas import (
    SkillInstallRequest,
    SkillPackageCreate,
    SkillPackageVersionCreate,
)
from app.domains.workforce.employees.models import DigitalEmployee

logger = logging.getLogger(__name__)

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
CATEGORY_LABELS = {
    "language": "语言类",
    "data": "数据类",
    "process": "流程类",
    "audit": "审核类",
    "learning": "学习类",
}


def visible_condition(tenant_id: int):
    return or_(SkillPackage.tenant_id.is_(None), SkillPackage.tenant_id == tenant_id)


async def latest_package(
    db: AsyncSession,
    tenant_id: int,
    code: str,
    *,
    version: int | None = None,
    published_only: bool = True,
) -> SkillPackage | None:
    stmt = select(SkillPackage).where(
        visible_condition(tenant_id), SkillPackage.code == code
    )
    if version is not None:
        stmt = stmt.where(SkillPackage.version == version)
    elif published_only:
        stmt = stmt.where(SkillPackage.status == "published")
    items = list((await db.scalars(stmt.order_by(SkillPackage.version.desc()))).all())
    if not items:
        return None
    # 同版本时优先租户自定义包
    items.sort(
        key=lambda item: (item.version, 1 if item.tenant_id == tenant_id else 0),
        reverse=True,
    )
    return items[0]


async def list_latest_packages(
    db: AsyncSession,
    tenant_id: int,
    *,
    category: str | None = None,
    keyword: str | None = None,
    published_only: bool = True,
) -> list[SkillPackage]:
    stmt = select(SkillPackage).where(visible_condition(tenant_id))
    if published_only:
        stmt = stmt.where(SkillPackage.status == "published")
    if category:
        stmt = stmt.where(SkillPackage.category == category)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                SkillPackage.name.ilike(like),
                SkillPackage.code.ilike(like),
                SkillPackage.description.ilike(like),
            )
        )
    items = list(
        (
            await db.scalars(
                stmt.order_by(SkillPackage.code, SkillPackage.version.desc())
            )
        ).all()
    )
    latest: dict[str, SkillPackage] = {}
    for item in items:
        current = latest.get(item.code)
        if current is None or item.version > current.version or (
            item.version == current.version and item.tenant_id == tenant_id
        ):
            latest[item.code] = item
    return sorted(latest.values(), key=lambda item: (item.category, item.code))


async def list_versions(db: AsyncSession, tenant_id: int, code: str) -> list[SkillPackage]:
    items = list(
        (
            await db.scalars(
                select(SkillPackage)
                .where(visible_condition(tenant_id), SkillPackage.code == code)
                .order_by(SkillPackage.version.desc())
            )
        ).all()
    )
    return items


async def resolve_install_plan(
    db: AsyncSession,
    tenant_id: int,
    code: str,
    *,
    version: int | None = None,
) -> list[SkillPackage]:
    """解析依赖并返回按依赖优先排序的安装计划。"""
    plan: list[SkillPackage] = []
    visited: dict[str, SkillPackage] = {}
    visiting: set[str] = set()

    async def visit(skill_code: str, pinned_version: int | None, trail: list[str]) -> None:
        if skill_code in visiting:
            raise ConflictError(f"技能依赖存在环: {' -> '.join([*trail, skill_code])}")
        package = await latest_package(
            db, tenant_id, skill_code, version=pinned_version
        )
        if package is None:
            raise NotFoundError(f"技能不存在或未发布: {skill_code}")
        if skill_code in visited:
            if visited[skill_code].version < package.version:
                visited[skill_code] = package
            return

        visiting.add(skill_code)
        for dep in package.dependencies or []:
            dep_code = str((dep or {}).get("code") or "")
            if not dep_code:
                continue
            min_version = int((dep or {}).get("min_version") or 1)
            dep_package = await latest_package(db, tenant_id, dep_code)
            if dep_package is None:
                raise NotFoundError(f"缺少依赖技能: {dep_code}")
            if dep_package.version < min_version:
                raise ConflictError(
                    f"{package.code} 需要 {dep_code} >= v{min_version}，"
                    f"当前最新 v{dep_package.version}"
                )
            await visit(dep_code, None, [*trail, skill_code])
        visiting.discard(skill_code)
        visited[skill_code] = package
        plan.append(package)

    await visit(code, version, [])
    return plan


def merge_permissions(packages: list[SkillPackage]) -> dict:
    """技能组合后的权限并集。"""
    tool_codes: set[str] = set()
    data_scopes: set[str] = set()
    read_only = True
    amount_threshold: float | None = None
    risk_level = "low"

    for package in packages:
        tool_codes.update(str(item) for item in (package.tool_codes or []))
        permissions = package.permissions or {}
        data_scopes.update(str(item) for item in (permissions.get("data_scopes") or []))
        read_only = read_only and bool(permissions.get("read_only", False))
        threshold = permissions.get("amount_threshold")
        if threshold is not None:
            value = float(threshold)
            amount_threshold = value if amount_threshold is None else min(amount_threshold, value)
        level = str(permissions.get("risk_level") or "low")
        if RISK_ORDER.get(level, 0) > RISK_ORDER.get(risk_level, 0):
            risk_level = level

    return {
        "read_only": read_only,
        "amount_threshold": amount_threshold,
        "risk_level": risk_level,
        "data_scopes": sorted(data_scopes),
        "tool_codes": sorted(tool_codes),
    }


def build_skills_context_from_packages(packages: list[SkillPackage]) -> str:
    if not packages:
        return "（未装配技能）"
    lines = ["已装配技能（只在岗位契约允许范围内使用）："]
    for package in packages:
        detail = package.prompt_template or package.description or ""
        lines.append(f"- {package.name}（{package.code} v{package.version}）：{detail}")
        if package.tool_codes:
            lines.append(f"  可用工具：{', '.join(str(item) for item in package.tool_codes)}")
        if package.knowledge_base_ids:
            lines.append(
                "  知识库："
                + ", ".join(str(item) for item in package.knowledge_base_ids)
            )
    return "\n".join(lines)


async def installed_rows(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> list[tuple[EmployeeSkill, SkillPackage]]:
    rows = await db.execute(
        select(EmployeeSkill, SkillPackage)
        .join(SkillPackage, SkillPackage.id == EmployeeSkill.skill_id)
        .where(
            EmployeeSkill.tenant_id == tenant_id,
            EmployeeSkill.employee_id == employee_id,
        )
        .order_by(EmployeeSkill.id)
    )
    return [(row[0], row[1]) for row in rows]


async def build_skills_context(
    db: AsyncSession, tenant_id: int, employee_id: int | None
) -> str:
    if not employee_id:
        return ""
    rows = await installed_rows(db, tenant_id, employee_id)
    packages = [package for skill, package in rows if skill.status == "active"]
    if not packages:
        return ""
    return build_skills_context_from_packages(packages)


def serialize_skill(skill: EmployeeSkill, package: SkillPackage) -> dict:
    return {
        "id": skill.id,
        "employee_id": skill.employee_id,
        "skill_code": skill.skill_code,
        "version": skill.version,
        "status": skill.status,
        "source": skill.source,
        "config": skill.config or {},
        "installed_at": skill.created_at,
        "package_name": package.name,
        "category": package.category,
        "description": package.description,
        "tool_codes": package.tool_codes or [],
        "prompt_template": package.prompt_template or "",
    }


def _permission_warnings(before: dict, after: dict) -> list[str]:
    warnings: list[str] = []
    if RISK_ORDER.get(after.get("risk_level", "low"), 0) > RISK_ORDER.get(
        before.get("risk_level", "low"), 0
    ):
        warnings.append(
            f"组合后风险等级提升：{before.get('risk_level')} → {after.get('risk_level')}"
        )
    added_scopes = set(after.get("data_scopes") or []) - set(before.get("data_scopes") or [])
    if added_scopes:
        warnings.append(f"组合后可触达新数据范围：{', '.join(sorted(added_scopes))}")
    added_tools = set(after.get("tool_codes") or []) - set(before.get("tool_codes") or [])
    if added_tools:
        warnings.append(f"组合后新增工具权限：{', '.join(sorted(added_tools))}")
    if not after.get("read_only") and before.get("read_only"):
        warnings.append("组合后由只读变为可写，请确认岗位契约与审批阈值")
    before_amount = before.get("amount_threshold")
    after_amount = after.get("amount_threshold")
    if after_amount is not None and (before_amount is None or after_amount < before_amount):
        warnings.append(f"组合后金额阈值收紧为 {after_amount:g}，超阈值将转人工")
    return warnings


async def install_skill(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    payload: SkillInstallRequest,
    *,
    user_id: int | None = None,
) -> dict:
    plan = await resolve_install_plan(
        db, tenant_id, payload.code, version=payload.version
    )
    rows = await installed_rows(db, tenant_id, employee_id)
    installed = {skill.skill_code: (skill, package) for skill, package in rows}
    plan_codes = {package.code for package in plan}

    for package in plan:
        for conflict_code in package.conflicts_with or []:
            if conflict_code == package.code:
                continue
            if conflict_code in plan_codes:
                raise ConflictError(
                    f"技能冲突：{package.code} 声明与 {conflict_code} 不能同时安装"
                )
            current = installed.get(conflict_code)
            if (
                current is not None
                and current[0].status == "active"
                and conflict_code not in plan_codes
            ):
                raise ConflictError(
                    f"技能冲突：{package.code} 与已安装的 {conflict_code} 不能同时使用"
                )

    before = merge_permissions(
        [package for skill, package in installed.values() if skill.status == "active"]
    )
    changed: list[tuple[EmployeeSkill, SkillPackage]] = []
    for package in plan:
        current = installed.get(package.code)
        if current is not None:
            skill, current_package = current
            if current_package.version == package.version:
                if skill.status != "active":
                    skill.status = "active"
                    skill.source = payload.source
                changed.append((skill, package))
                continue
            raise ConflictError(
                f"{package.code} 已安装 v{current_package.version}，请使用升级接口"
            )
        skill = EmployeeSkill(
            tenant_id=tenant_id,
            employee_id=employee_id,
            skill_code=package.code,
            skill_id=package.id,
            version=package.version,
            status="active",
            source=payload.source,
            installed_by=user_id,
        )
        db.add(skill)
        await db.flush()
        changed.append((skill, package))
        installed[package.code] = (skill, package)

    rows_after = await installed_rows(db, tenant_id, employee_id)
    after = merge_permissions(
        [package for skill, package in rows_after if skill.status == "active"]
    )
    warnings = _permission_warnings(before, after)
    return {
        "installed": [serialize_skill(skill, package) for skill, package in changed],
        "warnings": warnings,
        "permissions": after,
    }


async def upgrade_skill(
    db: AsyncSession,
    tenant_id: int,
    employee,
    code: str,
    *,
    user_id: int | None = None,
) -> dict:
    """升级到最新版本（含依赖）；有评估套件时执行升级前后回归。"""
    rows = await installed_rows(db, tenant_id, employee.id)
    matched = next(((skill, package) for skill, package in rows if skill.skill_code == code), None)
    if matched is None:
        raise NotFoundError(f"员工未安装技能: {code}")
    _skill, current_package = matched

    plan = await resolve_install_plan(db, tenant_id, code)
    latest = plan[-1]
    if latest.code != code:
        raise BadRequestError("技能依赖解析异常")
    if latest.version <= current_package.version:
        raise BadRequestError(f"{code} 已是最新版本 v{current_package.version}")

    plan_codes = {package.code for package in plan}
    installed_map = {skill.skill_code: (skill, package) for skill, package in rows}
    for package in plan:
        for conflict_code in package.conflicts_with or []:
            if conflict_code in plan_codes:
                raise ConflictError(
                    f"技能冲突：{package.code} 声明与 {conflict_code} 不能同时安装"
                )
            if conflict_code in installed_map:
                raise ConflictError(
                    f"技能冲突：{package.code} 与已安装的 {conflict_code} 不能同时使用"
                )

    suites = await suites_for_employee(db, tenant_id, employee.id)

    from app.domains.workforce.prompting import build_employee_prompt

    before_runs = []
    if suites:
        before_prompt = await build_employee_prompt(db, tenant_id, employee)
        for suite in suites:
            before_runs.append(
                await run_suite(
                    db,
                    suite,
                    employee=employee,
                    system_prompt=before_prompt,
                    trigger="skill_upgrade",
                    user_id=user_id,
                )
            )

    changes: list[tuple[EmployeeSkill, int | None, int | None, bool]] = []
    for package in plan:
        current = installed_map.get(package.code)
        if current is None:
            created = EmployeeSkill(
                tenant_id=tenant_id,
                employee_id=employee.id,
                skill_code=package.code,
                skill_id=package.id,
                version=package.version,
                status="active",
                source="marketplace",
                installed_by=user_id,
            )
            db.add(created)
            await db.flush()
            changes.append((created, None, None, True))
            installed_map[package.code] = (created, package)
            continue
        skill, installed_package = current
        if installed_package.version >= package.version:
            continue
        changes.append((skill, skill.skill_id, skill.version, False))
        skill.skill_id = package.id
        skill.version = package.version
    await db.flush()

    after_rows = await installed_rows(db, tenant_id, employee.id)

    if before_runs:
        after_prompt = await build_employee_prompt(db, tenant_id, employee)
        after_runs = []
        regressions = []
        for suite, before in zip(suites, before_runs, strict=False):
            after = await run_suite(
                db,
                suite,
                employee=employee,
                system_prompt=after_prompt,
                trigger="skill_upgrade",
                user_id=user_id,
            )
            after_runs.append(after)
            if after.score < before.score - suite.regression_tolerance:
                regressions.append((suite, before, after))

        if regressions:
            for changed, previous_id, previous_version, created in reversed(changes):
                if created:
                    await db.delete(changed)
                else:
                    changed.skill_id = previous_id
                    changed.version = previous_version
            await db.flush()
            summary = "；".join(
                f"{suite.code} {before.score} → {after.score}"
                for suite, before, after in regressions
            )
            await record_audit(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                employee_id=employee.id,
                action="skill.upgrade_blocked",
                resource_type="employee_skill",
                resource_id=matched[0].id,
                detail={"skill_code": code, "reason": summary},
            )
            # 评估记录与回滚结果必须落库，否则异常回滚会丢失证据
            await db.commit()
            raise BadRequestError(f"技能升级导致评估回归，已回滚：{summary}")

        before_by_suite = {run.suite_id: run for run in before_runs}
        run_details = [
            {
                "suite_id": run.suite_id,
                "before": before_by_suite.get(run.suite_id).score
                if before_by_suite.get(run.suite_id)
                else None,
                "after": run.score,
                "passed": run.passed,
                "run_id": run.id,
            }
            for run in after_runs
        ]
    else:
        run_details = []

    before_union = merge_permissions(
        [package for item, package in rows if item.status == "active"]
    )
    after_union = merge_permissions(
        [package for item, package in after_rows if item.status == "active"]
    )
    warnings = _permission_warnings(before_union, after_union)
    upgraded_skill = installed_map[code][0]
    return {
        "skill": serialize_skill(upgraded_skill, latest),
        "runs": run_details,
        "warnings": warnings,
    }


async def copy_skill(
    db: AsyncSession,
    tenant_id: int,
    target_employee_id: int,
    source_employee_id: int,
    code: str,
    *,
    user_id: int | None = None,
) -> dict:
    source_rows = await installed_rows(db, tenant_id, source_employee_id)
    source = next(
        (
            (skill, package)
            for skill, package in source_rows
            if skill.skill_code == code and skill.status == "active"
        ),
        None,
    )
    if source is None:
        raise NotFoundError(f"源员工未装配技能: {code}")
    skill, package = source
    payload = SkillInstallRequest(
        code=code, version=package.version, source="copy"
    )
    return await install_skill(
        db, tenant_id, target_employee_id, payload, user_id=user_id
    )


def _tokens(text: str) -> list[str]:
    return [item for item in re.split(r"[\s,，。;；/]+", text.lower()) if item]


def _score_llm(value) -> float:
    try:
        score = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if score <= 1:
        score *= 10
    return max(0.0, min(10.0, score))


def _parse_llm_recommendations(
    picks: list,
    packages: list,
    *,
    limit: int = 8,
) -> list[dict]:
    """校验 LLM 选择：只接受候选目录内且不重复的技能编码。"""
    by_code = {package.code: package for package in packages}
    results: list[dict] = []
    seen: set[str] = set()
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        code = str(pick.get("code") or "").strip()
        package = by_code.get(code)
        if package is None or code in seen:
            continue
        seen.add(code)
        reason = str(pick.get("reason") or "LLM 根据岗位需求推荐").strip()
        results.append(
            {
                "code": package.code,
                "name": package.name,
                "category": package.category,
                "version": package.version,
                "score": round(_score_llm(pick.get("score")), 2),
                "reason": f"LLM：{reason[:240]}",
                "source": "llm",
            }
        )
        if len(results) >= limit:
            break
    return results


def _skill_recommend_messages(
    employee,
    catalog: list[dict],
    need: str,
    limit: int,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "你是数字员工技能组合推荐器，只输出 JSON，不要输出解释。",
        },
        {
            "role": "user",
            "content": (
                f"员工岗位：{employee.position or employee.name}\n"
                f"职责：{employee.description or '未填写'}\n"
                f"能力需求：{need}\n\n"
                f"候选技能（只能从这里选）：\n"
                f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
                f"请推荐最多 {limit} 个互补技能，优先考虑依赖完整性与岗位匹配。"
                "输出 JSON："
                '{"recommendations":[{"code":"技能编码","score":0.0,'
                '"reason":"推荐理由"}]}'
            ),
        },
    ]


async def recommend_skills_llm(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    need: str,
    *,
    limit: int = 8,
) -> list[dict]:
    """让 LLM 从候选技能中选组合；未配置或失败时返回空，由规则推荐兜底。"""
    if not is_configured():
        return []
    employee = await db.scalar(
        select(DigitalEmployee).where(
            DigitalEmployee.id == employee_id,
            DigitalEmployee.tenant_id == tenant_id,
        )
    )
    if employee is None:
        return []

    rows = await installed_rows(db, tenant_id, employee_id)
    installed_codes = {skill.skill_code for skill, _ in rows}
    packages = [
        package
        for package in await list_latest_packages(db, tenant_id)
        if package.code not in installed_codes
    ]
    if not packages:
        return []
    catalog = [
        {
            "code": package.code,
            "name": package.name,
            "category": package.category,
            "version": package.version,
            "description": package.description,
            "algorithm": package.algorithm,
            "tags": package.tags,
            "dependencies": package.dependencies,
        }
        for package in packages
    ]
    messages = _skill_recommend_messages(employee, catalog, need, limit)
    try:
        data, _tokens = await chat_json(
            messages, timeout=settings.llm_recommend_timeout
        )
    except LLMError as exc:
        logger.warning("LLM 技能推荐失败，回退规则: %s", exc)
        return []
    except Exception:  # noqa: BLE001
        logger.exception("LLM 技能推荐异常，回退规则")
        return []

    picks = data.get("recommendations") or data.get("items") or []
    if not isinstance(picks, list):
        return []
    return _parse_llm_recommendations(picks, packages, limit=limit)


async def recommend_skills(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    need: str,
    *,
    limit: int = 8,
    use_llm: bool = False,
) -> list[dict]:
    if use_llm:
        llm_items = await recommend_skills_llm(
            db, tenant_id, employee_id, need, limit=limit
        )
        if llm_items:
            return llm_items

    rows = await installed_rows(db, tenant_id, employee_id)
    installed_codes = {skill.skill_code for skill, _ in rows}
    installed_packages = [package for _skill, package in rows]
    packages = await list_latest_packages(db, tenant_id)
    lowered = need.lower()
    tokens = _tokens(need)
    combo_codes: set[str] = set()
    for package in installed_packages:
        combo_codes.update(str(item) for item in (package.common_combos or []))

    results = []
    for package in packages:
        if package.code in installed_codes:
            continue
        score = 0.0
        reasons: list[str] = []
        if lowered and lowered in package.name.lower():
            score += 4
            reasons.append("名称直接匹配")
        if lowered and lowered in package.description.lower():
            score += 2
            reasons.append("描述匹配")
        haystack = " ".join(
            [
                package.name,
                package.description,
                package.algorithm,
                package.category,
                CATEGORY_LABELS.get(package.category, ""),
                *[str(item) for item in package.tags or []],
            ]
        ).lower()
        hits = [token for token in tokens if token and token in haystack]
        if hits:
            score += min(len(hits), 4)
            reasons.append(f"关键词命中：{', '.join(hits[:4])}")
        if package.code in combo_codes:
            score += 2
            reasons.append("与已装配技能常见组合")
        if score <= 0:
            continue
        results.append(
            {
                "code": package.code,
                "name": package.name,
                "category": package.category,
                "version": package.version,
                "score": round(score, 2),
                "reason": "；".join(reasons),
                "source": "rule",
            }
        )
    results.sort(key=lambda item: (-item["score"], item["code"]))
    return results[:limit]


async def create_package(
    db: AsyncSession,
    tenant_id: int,
    payload: SkillPackageCreate,
    *,
    user_id: int | None = None,
) -> SkillPackage:
    exists = await db.scalar(
        select(SkillPackage.id).where(
            SkillPackage.tenant_id == tenant_id, SkillPackage.code == payload.code
        )
    )
    if exists:
        raise ConflictError("技能编码已存在，请通过“新建版本”升级")
    package = SkillPackage(
        tenant_id=tenant_id,
        version=1,
        status="draft",
        is_builtin=False,
        created_by=user_id,
        **payload.model_dump(),
    )
    db.add(package)
    await db.flush()
    return package


async def create_version(
    db: AsyncSession,
    tenant_id: int,
    code: str,
    payload: SkillPackageVersionCreate,
    *,
    user_id: int | None = None,
) -> SkillPackage:
    versions = list(
        (
            await db.scalars(
                select(SkillPackage)
                .where(
                    SkillPackage.tenant_id == tenant_id, SkillPackage.code == code
                )
                .order_by(SkillPackage.version.desc())
            )
        ).all()
    )
    if not versions:
        raise NotFoundError("只能为租户自定义技能创建新版本")
    latest = versions[0]
    updates = payload.model_dump(exclude_unset=True)
    package = SkillPackage(
        tenant_id=tenant_id,
        code=code,
        name=updates.get("name", latest.name),
        category=updates.get("category", latest.category),
        description=updates.get("description", latest.description),
        version=latest.version + 1,
        status="draft",
        is_builtin=False,
        algorithm=updates.get("algorithm", latest.algorithm),
        tool_codes=updates.get("tool_codes", latest.tool_codes),
        knowledge_base_ids=updates.get("knowledge_base_ids", latest.knowledge_base_ids),
        prompt_template=updates.get("prompt_template", latest.prompt_template),
        eval_case_ids=updates.get("eval_case_ids", latest.eval_case_ids),
        dependencies=updates.get("dependencies", latest.dependencies),
        conflicts_with=updates.get("conflicts_with", latest.conflicts_with),
        permissions=updates.get("permissions", latest.permissions),
        common_combos=updates.get("common_combos", latest.common_combos),
        tags=updates.get("tags", latest.tags),
        extra=updates.get("extra", latest.extra),
        created_by=user_id,
    )
    db.add(package)
    await db.flush()
    return package


def deprecate_package(package: SkillPackage) -> None:
    package.status = "deprecated"
    package.updated_at = utcnow()
