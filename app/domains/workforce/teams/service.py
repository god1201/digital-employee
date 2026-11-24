import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.utils import slugify
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.teams.models import RolePreset, Team, TeamMember, TeamTemplate
from app.domains.workforce.teams.schemas import (
    TeamCreate,
    TeamDetail,
    TeamMemberInput,
    TeamMemberOut,
    TeamOut,
)


async def get_template(db: AsyncSession, tenant_id: int, template_id: int) -> TeamTemplate:
    template = await db.scalar(
        select(TeamTemplate).where(
            TeamTemplate.id == template_id,
            TeamTemplate.enabled.is_(True),
            or_(
                TeamTemplate.tenant_id.is_(None),
                TeamTemplate.tenant_id == tenant_id,
            ),
        )
    )
    if template is None:
        raise NotFoundError("团队模板不存在")
    return template


async def get_preset(db: AsyncSession, tenant_id: int, code: str) -> RolePreset | None:
    return await db.scalar(
        select(RolePreset).where(
            RolePreset.code == code,
            RolePreset.status == "active",
            or_(
                RolePreset.tenant_id.is_(None),
                RolePreset.tenant_id == tenant_id,
            ),
        )
    )


async def create_team_record(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    payload: TeamCreate,
) -> Team:
    template = None
    if payload.template_id is not None:
        template = await get_template(db, tenant_id, payload.template_id)

    template_roles = {role.get("code"): role for role in (template.roles if template else [])}

    member_inputs = payload.members
    if member_inputs is None:
        if template is None:
            raise BadRequestError("请选择团队模板或提供成员")
        member_inputs = [TeamMemberInput(role_code=role["code"]) for role in template.roles]
    if not member_inputs:
        raise BadRequestError("团队成员不能为空")

    code = (payload.code or f"team_{uuid.uuid4().hex[:10]}")[:64]
    exists = await db.scalar(select(Team.id).where(Team.tenant_id == tenant_id, Team.code == code))
    if exists:
        raise ConflictError("团队编码已存在")

    auto_activate = bool(payload.auto_activate)
    team = Team(
        tenant_id=tenant_id,
        template_id=template.id if template else None,
        name=payload.name,
        code=code,
        description=payload.description,
        status="active" if auto_activate else "pending_confirmation",
        topology=payload.topology
        or (template.topology if template else {"mode": "flat", "edges": []}),
        config={"auto_activate": auto_activate},
        created_by=user_id,
    )
    db.add(team)
    await db.flush()

    for index, member in enumerate(member_inputs):
        role_default = template_roles.get(member.role_code)
        preset = None
        if role_default is None:
            preset = await get_preset(db, tenant_id, member.role_code)

        role_name = (
            member.role_name
            or (role_default or {}).get("name")
            or (preset.name if preset else member.role_code)
        )
        description = (role_default or {}).get("description") or (
            preset.description if preset else ""
        )
        skills = member.skills
        if skills is None:
            skills = (role_default or {}).get("skills") or (preset.default_skills if preset else [])
        tools = member.tools
        if tools is None:
            tools = (role_default or {}).get("tools") or (preset.tool_groups if preset else [])
        approval_threshold = (
            member.approval_threshold
            or (role_default or {}).get("approval_threshold")
            or (preset.approval_threshold if preset else "medium")
        )
        sandbox = (
            member.sandbox
            or (role_default or {}).get("sandbox")
            or (preset.sandbox if preset else "none")
        )
        model_name = (
            member.model_name or (role_default or {}).get("model_name") or settings.llm_model
        )
        reports_to = (
            member.reports_to
            if member.reports_to is not None
            else (role_default or {}).get("reports_to")
        )

        employee_name = member.employee_name or f"{role_name}-{index + 1}"
        employee_code = f"tm_{team.id}_{slugify(member.role_code)}_{index + 1}"[:64]
        employee = DigitalEmployee(
            tenant_id=tenant_id,
            name=employee_name,
            code=employee_code,
            position=role_name,
            description=description,
            status="active" if auto_activate else "draft",
            model_provider=settings.llm_provider,
            model_name=model_name,
            system_prompt=f"你是{role_name}。{description}".strip(),
            config={
                "team_id": team.id,
                "role_code": member.role_code,
                "skills": skills,
                "tools": tools,
                "approval_threshold": approval_threshold,
                "sandbox": sandbox,
            },
            created_by=user_id,
        )
        db.add(employee)
        await db.flush()

        db.add(
            TeamMember(
                tenant_id=tenant_id,
                team_id=team.id,
                employee_id=employee.id,
                role_code=member.role_code,
                role_name=role_name,
                skills=skills,
                tools=tools,
                approval_threshold=approval_threshold,
                sandbox=sandbox,
                reports_to=reports_to,
                status="active" if auto_activate else "pending",
            )
        )

    await db.flush()
    return team


async def build_team_detail(db: AsyncSession, team: Team) -> dict:
    members = list(
        (
            await db.scalars(
                select(TeamMember)
                .where(
                    TeamMember.team_id == team.id,
                    TeamMember.tenant_id == team.tenant_id,
                )
                .order_by(TeamMember.id)
            )
        ).all()
    )

    employee_ids = [member.employee_id for member in members if member.employee_id]
    employees: dict[int, tuple] = {}
    if employee_ids:
        rows = (
            await db.execute(
                select(
                    DigitalEmployee.id,
                    DigitalEmployee.name,
                    DigitalEmployee.code,
                    DigitalEmployee.status,
                ).where(DigitalEmployee.id.in_(employee_ids))
            )
        ).all()
        employees = {row[0]: row for row in rows}

    template_name = None
    if team.template_id:
        template_name = await db.scalar(
            select(TeamTemplate.name).where(TeamTemplate.id == team.template_id)
        )

    data = TeamOut.model_validate(team).model_dump(mode="json")
    data["template_name"] = template_name
    member_data = []
    for member in members:
        item = TeamMemberOut.model_validate(member).model_dump(mode="json")
        employee = employees.get(member.employee_id)
        if employee:
            item["employee_name"] = employee[1]
            item["employee_code"] = employee[2]
            item["employee_status"] = employee[3]
        member_data.append(item)
    data["members"] = member_data
    return TeamDetail(**data).model_dump(mode="json")


async def set_team_status(db: AsyncSession, team: Team, status: str) -> None:
    team.status = status
    members = list(
        (
            await db.scalars(
                select(TeamMember).where(
                    TeamMember.team_id == team.id,
                    TeamMember.tenant_id == team.tenant_id,
                )
            )
        ).all()
    )
    employee_ids = [member.employee_id for member in members if member.employee_id]
    employees: dict[int, DigitalEmployee] = {}
    if employee_ids:
        rows = list(
            (
                await db.scalars(
                    select(DigitalEmployee).where(DigitalEmployee.id.in_(employee_ids))
                )
            ).all()
        )
        employees = {employee.id: employee for employee in rows}

    member_status = {
        "active": "active",
        "paused": "paused",
        "disabled": "disabled",
    }.get(status, "pending")
    employee_status = {
        "active": "active",
        "paused": "disabled",
        "disabled": "disabled",
    }.get(status, "draft")

    for member in members:
        member.status = member_status
        employee = employees.get(member.employee_id)
        if employee:
            employee.status = employee_status

    await db.flush()
