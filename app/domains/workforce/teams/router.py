from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentAdmin, CurrentUser, DbSession
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.teams.models import RolePreset, Team, TeamMember, TeamTemplate
from app.domains.workforce.teams.schemas import (
    RolePresetCreate,
    RolePresetOut,
    RolePresetUpdate,
    TeamCreate,
    TeamOut,
    TeamTemplateCreate,
    TeamTemplateOut,
)
from app.domains.workforce.teams.service import (
    build_team_detail,
    create_team_record,
    get_template,
    set_team_status,
)

router = APIRouter(tags=["团队模板"])


async def _get_team(db: DbSession, tenant_id: int, team_id: int) -> Team:
    team = await db.scalar(select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id))
    if team is None:
        raise NotFoundError("团队不存在")
    return team


@router.get("/role-presets", summary="角色预设库")
async def list_role_presets(
    db: DbSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    conditions = [
        or_(
            RolePreset.tenant_id.is_(None),
            RolePreset.tenant_id == current_user.tenant_id,
        )
    ]
    if status:
        conditions.append(RolePreset.status == status)

    items = list(
        (
            await db.scalars(
                select(RolePreset)
                .where(*conditions)
                .order_by(RolePreset.is_builtin.desc(), RolePreset.id)
            )
        ).all()
    )
    return paged(
        [RolePresetOut.model_validate(item).model_dump(mode="json") for item in items],
        len(items),
        1,
        len(items) or 1,
    )


@router.post("/role-presets", summary="创建自定义角色")
async def create_role_preset(
    payload: RolePresetCreate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    exists = await db.scalar(
        select(RolePreset.id).where(
            RolePreset.tenant_id == current_admin.tenant_id,
            RolePreset.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("角色编码已存在")

    preset = RolePreset(
        tenant_id=current_admin.tenant_id,
        is_builtin=False,
        **payload.model_dump(),
    )
    db.add(preset)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="role_preset.create",
        resource_type="role_preset",
        resource_id=preset.id,
        detail={"code": preset.code},
        ip_address=client_ip(request),
    )
    return success(RolePresetOut.model_validate(preset).model_dump(mode="json"))


@router.patch("/role-presets/{preset_id}", summary="更新自定义角色")
async def update_role_preset(
    preset_id: int,
    payload: RolePresetUpdate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    preset = await db.scalar(
        select(RolePreset).where(
            RolePreset.id == preset_id,
            RolePreset.tenant_id == current_admin.tenant_id,
        )
    )
    if preset is None:
        raise ForbiddenError("只能编辑本租户的自定义角色")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(preset, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="role_preset.update",
        resource_type="role_preset",
        resource_id=preset.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(RolePresetOut.model_validate(preset).model_dump(mode="json"))


@router.delete("/role-presets/{preset_id}", summary="删除自定义角色")
async def delete_role_preset(
    preset_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    preset = await db.scalar(
        select(RolePreset).where(
            RolePreset.id == preset_id,
            RolePreset.tenant_id == current_admin.tenant_id,
        )
    )
    if preset is None:
        raise ForbiddenError("只能删除本租户的自定义角色")
    await db.delete(preset)
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="role_preset.delete",
        resource_type="role_preset",
        resource_id=preset_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.get("/team-templates", summary="团队模板列表")
async def list_templates(
    db: DbSession,
    current_user: CurrentUser,
    category: str | None = None,
):
    conditions = [
        TeamTemplate.enabled.is_(True),
        or_(
            TeamTemplate.tenant_id.is_(None),
            TeamTemplate.tenant_id == current_user.tenant_id,
        ),
    ]
    if category:
        conditions.append(TeamTemplate.category == category)

    items = list(
        (
            await db.scalars(
                select(TeamTemplate)
                .where(*conditions)
                .order_by(TeamTemplate.is_builtin.desc(), TeamTemplate.id)
            )
        ).all()
    )
    return paged(
        [TeamTemplateOut.model_validate(item).model_dump(mode="json") for item in items],
        len(items),
        1,
        len(items) or 1,
    )


@router.get("/team-templates/{template_id}", summary="团队模板详情")
async def get_template_detail(
    template_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    template = await get_template(db, current_user.tenant_id, template_id)
    return success(TeamTemplateOut.model_validate(template).model_dump(mode="json"))


@router.post("/team-templates", summary="创建自定义团队模板")
async def create_template(
    payload: TeamTemplateCreate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    exists = await db.scalar(
        select(TeamTemplate.id).where(
            TeamTemplate.tenant_id == current_admin.tenant_id,
            TeamTemplate.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("模板编码已存在")

    template = TeamTemplate(
        tenant_id=current_admin.tenant_id,
        is_builtin=False,
        enabled=True,
        created_by=current_admin.id,
        **payload.model_dump(),
    )
    db.add(template)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="team_template.create",
        resource_type="team_template",
        resource_id=template.id,
        detail={"code": template.code, "roles": len(template.roles)},
        ip_address=client_ip(request),
    )
    return success(TeamTemplateOut.model_validate(template).model_dump(mode="json"))


@router.get("/teams", summary="团队列表")
async def list_teams(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
):
    conditions = [Team.tenant_id == current_user.tenant_id]
    if status:
        conditions.append(Team.status == status)

    stmt = select(Team).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    teams = list(
        (
            await db.scalars(
                stmt.order_by(Team.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    counts = {}
    if teams:
        rows = (
            await db.execute(
                select(TeamMember.team_id, func.count())
                .where(TeamMember.tenant_id == current_user.tenant_id)
                .group_by(TeamMember.team_id)
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in rows}

    template_names = {}
    template_ids = {team.template_id for team in teams if team.template_id}
    if template_ids:
        rows = (
            await db.execute(
                select(TeamTemplate.id, TeamTemplate.name).where(TeamTemplate.id.in_(template_ids))
            )
        ).all()
        template_names = {row[0]: row[1] for row in rows}

    items = []
    for team in teams:
        data = TeamOut.model_validate(team).model_dump(mode="json")
        data["member_count"] = counts.get(team.id, 0)
        data["template_name"] = template_names.get(team.template_id)
        items.append(data)
    return paged(items, total, page, page_size)


@router.post("/teams", summary="从模板创建团队")
async def create_team(
    payload: TeamCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    team = await create_team_record(db, current_user.tenant_id, current_user.id, payload)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="team.create",
        resource_type="team",
        resource_id=team.id,
        detail={
            "template_id": payload.template_id,
            "status": team.status,
        },
        ip_address=client_ip(request),
    )
    return success(await build_team_detail(db, team))


@router.get("/teams/{team_id}", summary="团队详情")
async def get_team(
    team_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    team = await _get_team(db, current_user.tenant_id, team_id)
    return success(await build_team_detail(db, team))


@router.post("/teams/{team_id}/activate", summary="确认并启用团队")
async def activate_team(
    team_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    team = await _get_team(db, current_admin.tenant_id, team_id)
    await set_team_status(db, team, "active")
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="team.activate",
        resource_type="team",
        resource_id=team.id,
        ip_address=client_ip(request),
    )
    return success(await build_team_detail(db, team))


@router.post("/teams/{team_id}/pause", summary="暂停团队")
async def pause_team(
    team_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    team = await _get_team(db, current_admin.tenant_id, team_id)
    await set_team_status(db, team, "paused")
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="team.pause",
        resource_type="team",
        resource_id=team.id,
        ip_address=client_ip(request),
    )
    return success(await build_team_detail(db, team))


@router.delete("/teams/{team_id}", summary="停用团队")
async def disable_team(
    team_id: int,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    team = await _get_team(db, current_admin.tenant_id, team_id)
    await set_team_status(db, team, "disabled")
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="team.disable",
        resource_type="team",
        resource_id=team.id,
        ip_address=client_ip(request),
    )
    return success(None, "团队已停用")
