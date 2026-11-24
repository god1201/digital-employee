"""岗位模板查询与一键装配。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.domains.knowledge.models import KnowledgeBase
from app.domains.learning.models import EvaluationSuite
from app.domains.skills.marketplace.schemas import SkillInstallRequest
from app.domains.skills.marketplace.service import install_skill, installed_rows
from app.domains.workforce.contracts.models import JobContract
from app.domains.workforce.contracts.service import get_contract
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.persona.schemas import PersonaUpsert
from app.domains.workforce.persona.service import upsert_persona
from app.domains.workforce.templates.models import JobTemplate
from app.domains.workforce.templates.schemas import ApplyTemplateRequest


async def list_templates(
    db: AsyncSession, tenant_id: int
) -> list[JobTemplate]:
    return list(
        (
            await db.scalars(
                select(JobTemplate)
                .where(
                    or_(
                        JobTemplate.tenant_id.is_(None),
                        JobTemplate.tenant_id == tenant_id,
                    ),
                    JobTemplate.enabled.is_(True),
                )
                .order_by(JobTemplate.is_builtin.desc(), JobTemplate.id)
            )
        ).all()
    )


async def get_template(
    db: AsyncSession, tenant_id: int, code: str
) -> JobTemplate:
    template = await db.scalar(
        select(JobTemplate)
        .where(
            JobTemplate.code == code,
            or_(
                JobTemplate.tenant_id.is_(None),
                JobTemplate.tenant_id == tenant_id,
            ),
            JobTemplate.enabled.is_(True),
        )
        .order_by(JobTemplate.tenant_id.is_(None))
    )
    if template is None:
        raise NotFoundError("岗位模板不存在")
    return template


async def apply_template(
    db: AsyncSession,
    tenant_id: int,
    employee: DigitalEmployee,
    payload: ApplyTemplateRequest,
    *,
    user_id: int | None = None,
) -> dict:
    template = await get_template(db, tenant_id, payload.template_code)
    notes: list[str] = []

    skill_report = {"installed": [], "skipped": [], "conflicts": []}
    if payload.install_skills:
        existing = {
            skill.skill_code: skill.version
            for skill, _package in await installed_rows(db, tenant_id, employee.id)
        }
        for code in template.skill_codes or []:
            if existing.get(code):
                skill_report["skipped"].append(code)
                continue
            try:
                result = await install_skill(
                    db,
                    tenant_id,
                    employee.id,
                    SkillInstallRequest(code=code, source="role_preset"),
                    user_id=user_id,
                )
                for item in result["installed"]:
                    if item["skill_code"] not in skill_report["installed"]:
                        skill_report["installed"].append(item["skill_code"])
            except ConflictError as exc:
                skill_report["conflicts"].append(f"{code}: {exc.message}")

    persona_report = {"updated": False}
    if payload.upsert_persona and template.persona:
        await upsert_persona(
            db,
            tenant_id,
            employee.id,
            PersonaUpsert(**template.persona),
            user_id=user_id,
        )
        persona_report["updated"] = True

    contract_report = {"created": False}
    if payload.create_contract_draft and template.contract:
        existing_contract = await get_contract(db, tenant_id, employee.id)
        if existing_contract is not None:
            contract_report["reason"] = "目标已有岗位契约，未覆盖"
        else:
            contract = template.contract or {}
            db.add(
                JobContract(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    role=contract.get("role", template.name),
                    can_do=contract.get("can_do", []),
                    cannot_do=contract.get("cannot_do", []),
                    must_ask=contract.get("must_ask", []),
                    kpi=contract.get("kpi", {}),
                    autonomy_level=contract.get("autonomy_level", "L2"),
                    red_lines={},
                    status="draft",
                    created_by=user_id,
                )
            )
            await db.flush()
            contract_report["created"] = True
            notes.append("岗位契约为草稿，请人工确认后启用")

    if template.eval_suite_code:
        suite = await db.scalar(
            select(EvaluationSuite).where(
                EvaluationSuite.tenant_id == tenant_id,
                EvaluationSuite.code == template.eval_suite_code,
            )
        )
        if suite is None:
            notes.append(
                f"评估套件 {template.eval_suite_code} 尚未创建，请先建套件再绑定"
            )
        else:
            notes.append(
                f"评估套件 {suite.code} 已存在，需在评估页手动绑定到本员工"
            )

    knowledge_report: dict = {"bound": [], "missing": [], "names": []}
    if template.knowledge_base_ids:
        requested: list[int] = []
        for item in template.knowledge_base_ids:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in requested:
                requested.append(value)
        if payload.bind_knowledge_bases and requested:
            bases = list(
                (
                    await db.scalars(
                        select(KnowledgeBase).where(
                            KnowledgeBase.tenant_id == tenant_id,
                            KnowledgeBase.id.in_(requested),
                            KnowledgeBase.status == "active",
                        )
                    )
                ).all()
            )
            found = {base.id: base for base in bases}
            missing = [item for item in requested if item not in found]
            knowledge_report["missing"] = missing
            if found:
                config = dict(employee.config or {})
                current: list[int] = []
                for item in config.get("knowledge_base_ids") or []:
                    try:
                        value = int(item)
                    except (TypeError, ValueError):
                        continue
                    if value > 0 and value not in current:
                        current.append(value)
                config["knowledge_base_ids"] = current + [
                    item for item in sorted(found) if item not in current
                ]
                employee.config = config
                knowledge_report["bound"] = sorted(found)
                knowledge_report["names"] = [
                    found[item].name for item in sorted(found)
                ]
                notes.append(
                    "已绑定知识库: " + "、".join(knowledge_report["names"])
                )
                await db.flush()
            if missing:
                notes.append(
                    "以下知识库不存在或未启用，未绑定: "
                    + "、".join(str(item) for item in missing)
                )
        elif not payload.bind_knowledge_bases:
            notes.append("模板声明的知识库未自动绑定（bind_knowledge_bases=false）")
        else:
            notes.append("模板声明的知识库 ID 无效，未绑定")

    return {
        "template": template,
        "skills": skill_report,
        "persona": persona_report,
        "contract": contract_report,
        "knowledge_bases": knowledge_report,
        "notes": notes,
    }
