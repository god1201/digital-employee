"""协作路由：根据团队关系、岗位与技能推荐“该问谁”。"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.skills.marketplace.service import installed_rows
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.teams.models import TeamMember

_TOKEN = re.compile(r"[\s,，、;；/]+")


def score_contact(topic: str, text: str) -> int:
    tokens = [item for item in _TOKEN.split(topic.lower()) if item]
    haystack = text.lower()
    return sum(1 for item in tokens if item in haystack)


async def build_routing_context(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    *,
    topic: str = "",
    limit: int = 5,
) -> str:
    team_ids = select(TeamMember.team_id).where(
        TeamMember.tenant_id == tenant_id,
        TeamMember.employee_id == employee_id,
    )
    members = list(
        (
            await db.scalars(
                select(TeamMember)
                .where(
                    TeamMember.tenant_id == tenant_id,
                    TeamMember.team_id.in_(team_ids),
                    TeamMember.employee_id.is_not(None),
                    TeamMember.employee_id != employee_id,
                )
                .limit(30)
            )
        ).all()
    )
    if not members:
        return ""

    contacts: list[tuple[int, DigitalEmployee, TeamMember, list[str]]] = []
    for member in members:
        if member.employee_id is None:
            continue
        employee = await db.get(DigitalEmployee, member.employee_id)
        if employee is None or employee.tenant_id != tenant_id:
            continue
        skills = await installed_rows(db, tenant_id, employee.id)
        skill_names = [
            package.name
            for skill, package in skills
            if skill.status == "active"
        ]
        text = " ".join(
            [
                member.role_name or "",
                employee.name or "",
                employee.position or "",
                *skill_names,
            ]
        )
        score = score_contact(topic, text) if topic else 0
        contacts.append((score, employee, member, skill_names))

    contacts.sort(key=lambda item: (-item[0], item[1].id))
    selected = contacts[: max(1, min(limit, 10))]
    lines = ["【可咨询的同事（按职责与技能）】"]
    for _score, employee, member, skill_names in selected:
        role = member.role_name or employee.position or "同事"
        skills_text = "、".join(skill_names[:4]) or "未装配技能"
        lines.append(f"- {employee.name}（{role}）：{skills_text}")
    return "\n".join(lines)
