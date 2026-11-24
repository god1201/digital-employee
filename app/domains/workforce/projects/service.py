"""项目服务：成员、任务/会话关联与 Token 汇总。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domains.workflows.tasks.models import TaskInstance, TaskStep
from app.domains.workforce.conversations.models import ChatMessage, Conversation
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.projects.models import Project, ProjectMember
from app.domains.workforce.projects.schemas import (
    ProjectCreate,
    ProjectUpdate,
)


async def get_project(
    db: AsyncSession, tenant_id: int, project_id: int
) -> Project:
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id, Project.tenant_id == tenant_id
        )
    )
    if project is None:
        raise NotFoundError("项目不存在")
    return project


async def create_project(
    db: AsyncSession,
    tenant_id: int,
    payload: ProjectCreate,
    *,
    user_id: int | None = None,
) -> Project:
    exists = await db.scalar(
        select(Project.id).where(
            Project.tenant_id == tenant_id, Project.code == payload.code
        )
    )
    if exists:
        raise ConflictError("项目编码已存在")
    if payload.owner_employee_id is not None:
        await _require_employee(db, tenant_id, payload.owner_employee_id)
    project = Project(
        tenant_id=tenant_id,
        created_by=user_id,
        **payload.model_dump(),
    )
    db.add(project)
    await db.flush()
    if payload.owner_employee_id is not None:
        db.add(
            ProjectMember(
                tenant_id=tenant_id,
                project_id=project.id,
                employee_id=payload.owner_employee_id,
                role="owner",
                created_by=user_id,
            )
        )
        await db.flush()
    return project


async def list_projects(
    db: AsyncSession, tenant_id: int, *, status: str | None = None
) -> list[Project]:
    conditions = [Project.tenant_id == tenant_id]
    if status:
        conditions.append(Project.status == status)
    return list(
        (
            await db.scalars(
                select(Project)
                .where(*conditions)
                .order_by(Project.id.desc())
            )
        ).all()
    )


async def update_project(
    db: AsyncSession, project: Project, payload: ProjectUpdate
) -> Project:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("owner_employee_id") is not None:
        await _require_employee(db, project.tenant_id, changes["owner_employee_id"])
    for field, value in changes.items():
        setattr(project, field, value)
    await db.flush()
    return project


async def add_member(
    db: AsyncSession,
    project: Project,
    employee_id: int,
    *,
    role: str = "member",
    user_id: int | None = None,
) -> ProjectMember:
    await _require_employee(db, project.tenant_id, employee_id)
    exists = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.employee_id == employee_id,
        )
    )
    if exists is not None:
        exists.role = role
        await db.flush()
        return exists
    member = ProjectMember(
        tenant_id=project.tenant_id,
        project_id=project.id,
        employee_id=employee_id,
        role=role,
        created_by=user_id,
    )
    db.add(member)
    await db.flush()
    return member


async def remove_member(
    db: AsyncSession, project: Project, employee_id: int
) -> None:
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.employee_id == employee_id,
        )
    )
    if member is None:
        raise NotFoundError("项目成员不存在")
    await db.delete(member)
    await db.flush()


async def link_task(
    db: AsyncSession, project: Project, instance_id: int
) -> TaskInstance:
    instance = await db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == instance_id,
            TaskInstance.tenant_id == project.tenant_id,
        )
    )
    if instance is None:
        raise NotFoundError("任务实例不存在")
    instance.project_id = project.id
    await db.flush()
    return instance


async def unlink_task(
    db: AsyncSession, project: Project, instance_id: int
) -> None:
    instance = await db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == instance_id,
            TaskInstance.tenant_id == project.tenant_id,
            TaskInstance.project_id == project.id,
        )
    )
    if instance is None:
        raise NotFoundError("任务未关联到该项目")
    instance.project_id = None
    await db.flush()


async def link_conversation(
    db: AsyncSession, project: Project, conversation_id: int
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == project.tenant_id,
        )
    )
    if conversation is None:
        raise NotFoundError("会话不存在")
    conversation.project_id = project.id
    await db.flush()
    return conversation


async def unlink_conversation(
    db: AsyncSession, project: Project, conversation_id: int
) -> None:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == project.tenant_id,
            Conversation.project_id == project.id,
        )
    )
    if conversation is None:
        raise NotFoundError("会话未关联到该项目")
    conversation.project_id = None
    await db.flush()


async def project_stats_map(
    db: AsyncSession, tenant_id: int, project_ids: list[int]
) -> dict[int, dict]:
    """一次查询聚合多个项目的成员/任务/会话/Token，避免列表 N+1。"""
    if not project_ids:
        return {}

    stats: dict[int, dict] = {
        project_id: {
            "member_count": 0,
            "task_count": 0,
            "conversation_count": 0,
            "tokens": 0,
            "cost": 0.0,
            "task_tokens": 0,
            "chat_tokens": 0,
        }
        for project_id in project_ids
    }

    member_rows = await db.execute(
        select(ProjectMember.project_id, func.count())
        .where(ProjectMember.project_id.in_(project_ids))
        .group_by(ProjectMember.project_id)
    )
    for project_id, count in member_rows.all():
        stats[project_id]["member_count"] = int(count)

    task_rows = await db.execute(
        select(TaskInstance.project_id, func.count())
        .where(
            TaskInstance.tenant_id == tenant_id,
            TaskInstance.project_id.in_(project_ids),
        )
        .group_by(TaskInstance.project_id)
    )
    for project_id, count in task_rows.all():
        stats[project_id]["task_count"] = int(count)

    task_token_rows = await db.execute(
        select(
            TaskInstance.project_id,
            func.coalesce(func.sum(TaskStep.tokens), 0),
            func.coalesce(func.sum(TaskStep.cost), 0),
        )
        .select_from(TaskStep)
        .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
        .where(TaskInstance.project_id.in_(project_ids))
        .group_by(TaskInstance.project_id)
    )
    for project_id, tokens, cost in task_token_rows.all():
        stats[project_id]["task_tokens"] = int(tokens or 0)
        stats[project_id]["tokens"] += int(tokens or 0)
        stats[project_id]["cost"] += float(cost or 0)

    conversation_rows = await db.execute(
        select(Conversation.project_id, func.count())
        .where(Conversation.project_id.in_(project_ids))
        .group_by(Conversation.project_id)
    )
    for project_id, count in conversation_rows.all():
        stats[project_id]["conversation_count"] = int(count)

    chat_token_rows = await db.execute(
        select(
            Conversation.project_id,
            func.coalesce(func.sum(ChatMessage.tokens), 0),
            func.coalesce(func.sum(ChatMessage.cost), 0),
        )
        .select_from(ChatMessage)
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.project_id.in_(project_ids))
        .group_by(Conversation.project_id)
    )
    for project_id, tokens, cost in chat_token_rows.all():
        stats[project_id]["chat_tokens"] = int(tokens or 0)
        stats[project_id]["tokens"] += int(tokens or 0)
        stats[project_id]["cost"] += float(cost or 0)

    for bucket in stats.values():
        bucket["cost"] = round(bucket["cost"], 6)
    return stats


async def employee_name_map(
    db: AsyncSession, tenant_id: int, employee_ids: set[int]
) -> dict[int, str]:
    if not employee_ids:
        return {}
    rows = await db.execute(
        select(DigitalEmployee.id, DigitalEmployee.name).where(
            DigitalEmployee.tenant_id == tenant_id,
            DigitalEmployee.id.in_(employee_ids),
        )
    )
    return {employee_id: name for employee_id, name in rows.all()}


async def project_token_totals(
    db: AsyncSession, project: Project
) -> dict:
    task_tokens = int(
        await db.scalar(
            select(func.coalesce(func.sum(TaskStep.tokens), 0))
            .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
            .where(TaskInstance.project_id == project.id)
        )
        or 0
    )
    task_cost = float(
        await db.scalar(
            select(func.coalesce(func.sum(TaskStep.cost), 0))
            .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
            .where(TaskInstance.project_id == project.id)
        )
        or 0
    )
    chat_tokens = int(
        await db.scalar(
            select(func.coalesce(func.sum(ChatMessage.tokens), 0))
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(Conversation.project_id == project.id)
        )
        or 0
    )
    chat_cost = float(
        await db.scalar(
            select(func.coalesce(func.sum(ChatMessage.cost), 0))
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(Conversation.project_id == project.id)
        )
        or 0
    )
    return {
        "tokens": task_tokens + chat_tokens,
        "cost": round(task_cost + chat_cost, 6),
        "task_tokens": task_tokens,
        "chat_tokens": chat_tokens,
        "budget": project.token_budget,
    }


async def project_detail(db: AsyncSession, project: Project) -> dict:
    members = list(
        (
            await db.scalars(
                select(ProjectMember)
                .where(ProjectMember.project_id == project.id)
                .order_by(ProjectMember.id)
            )
        ).all()
    )
    employees: dict[int, DigitalEmployee] = {}
    if members:
        employee_rows = await db.scalars(
            select(DigitalEmployee).where(
                DigitalEmployee.id.in_(
                    [member.employee_id for member in members]
                )
            )
        )
        employees = {employee.id: employee for employee in employee_rows.all()}

    tasks = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(TaskInstance.project_id == project.id)
                .order_by(TaskInstance.id.desc())
                .limit(50)
            )
        ).all()
    )
    token_map: dict[int, int] = {}
    if tasks:
        rows = await db.execute(
            select(TaskStep.instance_id, func.coalesce(func.sum(TaskStep.tokens), 0))
            .where(TaskStep.instance_id.in_([task.id for task in tasks]))
            .group_by(TaskStep.instance_id)
        )
        token_map = {row[0]: int(row[1] or 0) for row in rows}

    conversations = list(
        (
            await db.scalars(
                select(Conversation)
                .where(Conversation.project_id == project.id)
                .order_by(Conversation.id.desc())
                .limit(20)
            )
        ).all()
    )

    return {
        "project": project,
        "members": [
            {
                "employee_id": member.employee_id,
                "name": employees[member.employee_id].name
                if member.employee_id in employees
                else "",
                "position": employees[member.employee_id].position
                if member.employee_id in employees
                else "",
                "role": member.role,
            }
            for member in members
        ],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "task_type": task.task_type,
                "tokens": token_map.get(task.id, 0),
                "created_at": task.created_at.isoformat(),
            }
            for task in tasks
        ],
        "conversations": [
            {
                "id": item.id,
                "title": item.title,
                "mode": item.mode,
                "last_message_at": item.last_message_at.isoformat()
                if item.last_message_at
                else None,
            }
            for item in conversations
        ],
        "token_usage": await project_token_totals(db, project),
    }


async def employee_projects(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> list[dict]:
    memberships = list(
        (
            await db.scalars(
                select(ProjectMember).where(
                    ProjectMember.tenant_id == tenant_id,
                    ProjectMember.employee_id == employee_id,
                )
            )
        ).all()
    )
    member_projects = {
        member.project_id: member.role for member in memberships
    }
    linked_ids = set(
        (
            await db.scalars(
                select(TaskInstance.project_id).where(
                    TaskInstance.tenant_id == tenant_id,
                    TaskInstance.employee_id == employee_id,
                    TaskInstance.project_id.is_not(None),
                )
            )
        ).all()
    )
    project_ids = set(member_projects) | {int(item) for item in linked_ids if item}
    if not project_ids:
        return []
    projects = list(
        (
            await db.scalars(
                select(Project)
                .where(
                    Project.tenant_id == tenant_id,
                    Project.id.in_(project_ids),
                )
                .order_by(Project.id.desc())
            )
        ).all()
    )
    result = []
    for project in projects:
        result.append(
            {
                "id": project.id,
                "name": project.name,
                "code": project.code,
                "status": project.status,
                "role": member_projects.get(project.id, "task_member"),
                "token_usage": await project_token_totals(db, project),
            }
        )
    return result


async def _require_employee(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> DigitalEmployee:
    employee = await db.scalar(
        select(DigitalEmployee).where(
            DigitalEmployee.id == employee_id,
            DigitalEmployee.tenant_id == tenant_id,
        )
    )
    if employee is None:
        raise BadRequestError("数字员工不存在")
    return employee
