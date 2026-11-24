from fastapi import APIRouter, Query, Request

from app.core.deps import CurrentUser, DbSession
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.projects.schemas import (
    ProjectConversationLink,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectOut,
    ProjectTaskLink,
    ProjectUpdate,
)
from app.domains.workforce.projects.service import (
    add_member,
    create_project,
    employee_name_map,
    get_project,
    link_conversation,
    link_task,
    list_projects,
    project_detail,
    project_stats_map,
    remove_member,
    unlink_conversation,
    unlink_task,
    update_project,
)

router = APIRouter(prefix="/projects", tags=["项目"])


@router.get("", summary="项目列表")
async def list_projects_endpoint(
    db: DbSession,
    current_user: CurrentUser,
    status: str | None = Query(None),
):
    projects = await list_projects(db, current_user.tenant_id, status=status)
    stats = await project_stats_map(
        db, current_user.tenant_id, [project.id for project in projects]
    )
    owner_names = await employee_name_map(
        db,
        current_user.tenant_id,
        {
            project.owner_employee_id
            for project in projects
            if project.owner_employee_id
        },
    )
    items = []
    for project in projects:
        payload = ProjectOut.model_validate(project).model_dump(mode="json")
        bucket = stats.get(project.id) or {}
        payload["owner_name"] = (
            owner_names.get(project.owner_employee_id or 0) or None
        )
        payload["member_count"] = bucket.get("member_count", 0)
        payload["task_count"] = bucket.get("task_count", 0)
        payload["conversation_count"] = bucket.get("conversation_count", 0)
        payload["token_usage"] = {
            "tokens": bucket.get("tokens", 0),
            "cost": bucket.get("cost", 0.0),
            "task_tokens": bucket.get("task_tokens", 0),
            "chat_tokens": bucket.get("chat_tokens", 0),
            "budget": project.token_budget,
        }
        items.append(payload)
    return success(items)


@router.post("", summary="创建项目")
async def create_project_endpoint(
    payload: ProjectCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await create_project(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.create",
        resource_type="project",
        resource_id=project.id,
        detail={"code": project.code, "name": project.name},
        ip_address=client_ip(request),
    )
    return success(ProjectOut.model_validate(project).model_dump(mode="json"))


@router.get("/{project_id}", summary="项目详情")
async def get_project_endpoint(
    project_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    detail = await project_detail(db, project)
    return success(
        {
            "project": ProjectOut.model_validate(project).model_dump(mode="json"),
            "members": detail["members"],
            "tasks": detail["tasks"],
            "conversations": detail["conversations"],
            "token_usage": detail["token_usage"],
        }
    )


@router.patch("/{project_id}", summary="更新项目")
async def update_project_endpoint(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    project = await update_project(db, project, payload)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.update",
        resource_type="project",
        resource_id=project.id,
        detail={"fields": sorted(payload.model_fields_set)},
        ip_address=client_ip(request),
    )
    return success(ProjectOut.model_validate(project).model_dump(mode="json"))


@router.post("/{project_id}/members", summary="添加项目成员")
async def add_member_endpoint(
    project_id: int,
    payload: ProjectMemberAdd,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    member = await add_member(
        db,
        project,
        payload.employee_id,
        role=payload.role,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=member.employee_id,
        action="project.member.add",
        resource_type="project",
        resource_id=project.id,
        detail={"employee_id": member.employee_id, "role": member.role},
        ip_address=client_ip(request),
    )
    return success(
        {"project_id": project.id, "employee_id": member.employee_id, "role": member.role}
    )


@router.delete(
    "/{project_id}/members/{employee_id}", summary="移除项目成员"
)
async def remove_member_endpoint(
    project_id: int,
    employee_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    await remove_member(db, project, employee_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="project.member.remove",
        resource_type="project",
        resource_id=project.id,
        detail={"employee_id": employee_id},
        ip_address=client_ip(request),
    )
    return success(None, "成员已移除")


@router.post("/{project_id}/tasks", summary="把任务关联到项目")
async def link_task_endpoint(
    project_id: int,
    payload: ProjectTaskLink,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    instance = await link_task(db, project, payload.instance_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=instance.employee_id,
        action="project.task.link",
        resource_type="project",
        resource_id=project.id,
        detail={"instance_id": instance.id},
        ip_address=client_ip(request),
    )
    return success(
        {"project_id": project.id, "instance_id": instance.id}
    )


@router.delete(
    "/{project_id}/tasks/{instance_id}", summary="取消任务与项目关联"
)
async def unlink_task_endpoint(
    project_id: int,
    instance_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    await unlink_task(db, project, instance_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.task.unlink",
        resource_type="project",
        resource_id=project.id,
        detail={"instance_id": instance_id},
        ip_address=client_ip(request),
    )
    return success(None, "任务已取消关联")


@router.post("/{project_id}/conversations", summary="把会话关联到项目")
async def link_conversation_endpoint(
    project_id: int,
    payload: ProjectConversationLink,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    conversation = await link_conversation(db, project, payload.conversation_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.conversation.link",
        resource_type="project",
        resource_id=project.id,
        detail={"conversation_id": conversation.id},
        ip_address=client_ip(request),
    )
    return success(
        {"project_id": project.id, "conversation_id": conversation.id}
    )


@router.delete(
    "/{project_id}/conversations/{conversation_id}",
    summary="取消会话与项目关联",
)
async def unlink_conversation_endpoint(
    project_id: int,
    conversation_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await get_project(db, current_user.tenant_id, project_id)
    await unlink_conversation(db, project, conversation_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.conversation.unlink",
        resource_type="project",
        resource_id=project.id,
        detail={"conversation_id": conversation_id},
        ip_address=client_ip(request),
    )
    return success(None, "会话已取消关联")
