"""跨员工能力迁移：复制技能、经验、偏好与契约草稿。"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.domains.learning.models import LearningArtifact, PreferenceMemory
from app.domains.skills.marketplace.schemas import SkillInstallRequest
from app.domains.skills.marketplace.service import install_skill, installed_rows
from app.domains.workforce.contracts.models import JobContract
from app.domains.workforce.contracts.service import get_contract
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.migrations.models import CapabilityMigration
from app.domains.workforce.migrations.schemas import CapabilityMigrationCreate


def _proposal_hash(proposal: dict) -> str:
    payload = json.dumps(proposal or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _get_employee(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> DigitalEmployee:
    employee = await db.get(DigitalEmployee, employee_id)
    if employee is None or employee.tenant_id != tenant_id:
        raise BadRequestError(f"员工不存在: {employee_id}")
    return employee


async def _migrate_skills(
    db: AsyncSession,
    tenant_id: int,
    source: DigitalEmployee,
    target: DigitalEmployee,
    *,
    dry_run: bool,
    user_id: int | None,
) -> dict:
    source_rows = await installed_rows(db, tenant_id, source.id)
    target_rows = await installed_rows(db, tenant_id, target.id)
    target_versions = {skill.skill_code: skill.version for skill, _package in target_rows}

    planned: list[str] = []
    installed: list[str] = []
    skipped: list[str] = []
    conflicts: list[str] = []
    warnings: list[str] = []

    for skill, _package in source_rows:
        if skill.status != "active":
            continue
        current_version = target_versions.get(skill.skill_code)
        if current_version == skill.version:
            skipped.append(skill.skill_code)
            continue
        if current_version is not None:
            conflicts.append(
                f"{skill.skill_code}: 目标已装 v{current_version}，源为 v{skill.version}"
            )
            continue
        if dry_run:
            planned.append(skill.skill_code)
            continue
        try:
            result = await install_skill(
                db,
                tenant_id,
                target.id,
                SkillInstallRequest(
                    code=skill.skill_code,
                    version=skill.version,
                    source="copy",
                ),
                user_id=user_id,
            )
            for item in result["installed"]:
                code = item["skill_code"]
                if code not in installed:
                    installed.append(code)
            warnings.extend(result["warnings"])
        except ConflictError as exc:
            conflicts.append(f"{skill.skill_code}: {exc.message}")

    return {
        "planned": planned,
        "installed": installed,
        "skipped": skipped,
        "conflicts": conflicts,
        "warnings": warnings,
    }


async def _migrate_artifacts(
    db: AsyncSession,
    tenant_id: int,
    source: DigitalEmployee,
    target: DigitalEmployee,
    *,
    dry_run: bool,
    user_id: int | None,
) -> dict:
    source_artifacts = list(
        (
            await db.scalars(
                select(LearningArtifact)
                .where(
                    LearningArtifact.tenant_id == tenant_id,
                    LearningArtifact.employee_id == source.id,
                    LearningArtifact.status.in_(["active", "approved"]),
                )
                .order_by(LearningArtifact.id)
            )
        ).all()
    )
    target_artifacts = list(
        (
            await db.scalars(
                select(LearningArtifact).where(
                    LearningArtifact.tenant_id == tenant_id,
                    LearningArtifact.employee_id == target.id,
                )
            )
        ).all()
    )
    target_hashes = {_proposal_hash(item.proposal) for item in target_artifacts}

    planned: list[int] = []
    created: list[int] = []
    skipped: list[int] = []
    for artifact in source_artifacts:
        if artifact.attribution == "越权/合规":
            continue
        digest = _proposal_hash(artifact.proposal)
        if digest in target_hashes:
            skipped.append(artifact.id)
            continue
        if dry_run:
            planned.append(artifact.id)
            continue
        copy = LearningArtifact(
            tenant_id=tenant_id,
            employee_id=target.id,
            source={
                "type": "capability_migration",
                "from_artifact_id": artifact.id,
                "source_employee_id": source.id,
            },
            attribution=artifact.attribution,
            target_layer=artifact.target_layer,
            proposal=artifact.proposal,
            evidence=artifact.evidence,
            eval_result={},
            risk=artifact.risk,
            scope="personal",
            status="pending_approval",
            rollout={"migrated_from": artifact.id},
            version=artifact.version,
            created_by=user_id,
        )
        db.add(copy)
        await db.flush()
        target_hashes.add(digest)
        created.append(copy.id)

    return {"planned": planned, "created": created, "skipped": skipped}


async def _migrate_preferences(
    db: AsyncSession,
    tenant_id: int,
    source: DigitalEmployee,
    target: DigitalEmployee,
    *,
    dry_run: bool,
    user_id: int | None,
) -> dict:
    source_preferences = list(
        (
            await db.scalars(
                select(PreferenceMemory).where(
                    PreferenceMemory.tenant_id == tenant_id,
                    PreferenceMemory.employee_id == source.id,
                    PreferenceMemory.status == "active",
                )
            )
        ).all()
    )
    target_keys = set(
        (
            await db.scalars(
                select(PreferenceMemory.key).where(
                    PreferenceMemory.tenant_id == tenant_id,
                    PreferenceMemory.employee_id == target.id,
                )
            )
        ).all()
    )
    planned: list[str] = []
    created: list[str] = []
    skipped: list[str] = []
    for preference in source_preferences:
        if preference.key in target_keys:
            skipped.append(preference.key)
            continue
        if dry_run:
            planned.append(preference.key)
            continue
        db.add(
            PreferenceMemory(
                tenant_id=tenant_id,
                employee_id=target.id,
                key=preference.key,
                value=preference.value,
                scope="personal",
                source="migration",
                confidence=preference.confidence,
                expires_at=preference.expires_at,
                created_by=user_id,
            )
        )
        created.append(preference.key)
    await db.flush()
    return {"planned": planned, "created": created, "skipped": skipped}


async def _migrate_contract(
    db: AsyncSession,
    tenant_id: int,
    source: DigitalEmployee,
    target: DigitalEmployee,
    *,
    dry_run: bool,
    user_id: int | None,
) -> dict:
    source_contract = await get_contract(db, tenant_id, source.id)
    if source_contract is None:
        return {"created": False, "reason": "源员工未配置岗位契约"}
    target_contract = await get_contract(db, tenant_id, target.id)
    if target_contract is not None:
        return {"created": False, "reason": "目标员工已有岗位契约，未覆盖"}
    if dry_run:
        return {"planned": True}

    db.add(
        JobContract(
            tenant_id=tenant_id,
            employee_id=target.id,
            role=source_contract.role,
            can_do=source_contract.can_do,
            cannot_do=source_contract.cannot_do,
            must_ask=source_contract.must_ask,
            kpi=source_contract.kpi,
            report_to=source_contract.report_to,
            report_freq=source_contract.report_freq,
            work_hours=source_contract.work_hours,
            escalation_path=source_contract.escalation_path,
            autonomy_level=source_contract.autonomy_level,
            autonomy_overrides=source_contract.autonomy_overrides,
            red_lines=source_contract.red_lines,
            version=1,
            status="draft",
            created_by=user_id,
        )
    )
    await db.flush()
    return {"created": True, "status": "draft"}


async def migrate_capabilities(
    db: AsyncSession,
    tenant_id: int,
    payload: CapabilityMigrationCreate,
    *,
    user_id: int | None = None,
) -> CapabilityMigration:
    if payload.source_employee_id == payload.target_employee_id:
        raise BadRequestError("源员工与目标员工不能相同")
    source = await _get_employee(db, tenant_id, payload.source_employee_id)
    target = await _get_employee(db, tenant_id, payload.target_employee_id)
    components = list(dict.fromkeys(payload.components))
    report: dict = {"dry_run": payload.dry_run}

    if "skills" in components:
        report["skills"] = await _migrate_skills(
            db,
            tenant_id,
            source,
            target,
            dry_run=payload.dry_run,
            user_id=user_id,
        )
    if "artifacts" in components:
        report["artifacts"] = await _migrate_artifacts(
            db,
            tenant_id,
            source,
            target,
            dry_run=payload.dry_run,
            user_id=user_id,
        )
    if "preferences" in components:
        report["preferences"] = await _migrate_preferences(
            db,
            tenant_id,
            source,
            target,
            dry_run=payload.dry_run,
            user_id=user_id,
        )
    if "contract" in components:
        report["contract"] = await _migrate_contract(
            db,
            tenant_id,
            source,
            target,
            dry_run=payload.dry_run,
            user_id=user_id,
        )

    conflicts = len((report.get("skills") or {}).get("conflicts") or [])
    status = "partial" if conflicts else "completed"
    migration = CapabilityMigration(
        tenant_id=tenant_id,
        source_employee_id=source.id,
        target_employee_id=target.id,
        components=components,
        dry_run=payload.dry_run,
        status=status,
        report=report,
        created_by=user_id,
    )
    db.add(migration)
    await db.flush()
    return migration
