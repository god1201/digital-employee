from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.llm import LLMError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workflows.storyboards.models import (
    StoryboardProject,
    StoryboardScene,
    StoryboardShot,
)
from app.domains.workflows.storyboards.schemas import (
    ShotOut,
    StoryboardCreate,
    StoryboardDetail,
    StoryboardOut,
    StoryboardUpdate,
)
from app.domains.workflows.storyboards.service import generate_storyboard, storyboard_to_csv

router = APIRouter(prefix="/storyboards", tags=["AI 剧本分镜"])


async def _get_project(db: DbSession, tenant_id: int, project_id: int) -> StoryboardProject:
    project = await db.scalar(
        select(StoryboardProject).where(
            StoryboardProject.id == project_id,
            StoryboardProject.tenant_id == tenant_id,
        )
    )
    if project is None:
        raise NotFoundError("分镜项目不存在")
    return project


async def _build_detail(db: DbSession, project: StoryboardProject) -> dict:
    scenes = list(
        (
            await db.scalars(
                select(StoryboardScene)
                .where(
                    StoryboardScene.project_id == project.id,
                    StoryboardScene.tenant_id == project.tenant_id,
                )
                .order_by(StoryboardScene.scene_index)
            )
        ).all()
    )
    shots = list(
        (
            await db.scalars(
                select(StoryboardShot)
                .where(
                    StoryboardShot.project_id == project.id,
                    StoryboardShot.tenant_id == project.tenant_id,
                )
                .order_by(StoryboardShot.shot_index)
            )
        ).all()
    )
    shots_by_scene: dict[int, list] = {}
    for shot in shots:
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)

    data = StoryboardOut.model_validate(project).model_dump(mode="json")
    data["script"] = project.script
    data["scenes"] = [
        {
            "id": scene.id,
            "project_id": scene.project_id,
            "scene_index": scene.scene_index,
            "location": scene.location,
            "time_of_day": scene.time_of_day,
            "characters": scene.characters,
            "summary": scene.summary,
            "mood": scene.mood,
            "shots": [
                ShotOut.model_validate(shot).model_dump(mode="json")
                for shot in shots_by_scene.get(scene.id, [])
            ],
        }
        for scene in scenes
    ]
    return StoryboardDetail(**data).model_dump(mode="json")


@router.get("", summary="分镜项目列表")
async def list_projects(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
):
    conditions = [StoryboardProject.tenant_id == current_user.tenant_id]
    if status:
        conditions.append(StoryboardProject.status == status)

    stmt = select(StoryboardProject).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(StoryboardProject.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [StoryboardOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建分镜项目")
async def create_project(
    payload: StoryboardCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = StoryboardProject(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(project)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="storyboard.create",
        resource_type="storyboard_project",
        resource_id=project.id,
        detail={"title": project.title, "genre": project.genre},
        ip_address=client_ip(request),
    )
    return success(StoryboardOut.model_validate(project).model_dump(mode="json"))


@router.get("/{project_id}", summary="分镜项目详情")
async def get_project(
    project_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await _get_project(db, current_user.tenant_id, project_id)
    return success(await _build_detail(db, project))


@router.patch("/{project_id}", summary="更新分镜项目")
async def update_project(
    project_id: int,
    payload: StoryboardUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await _get_project(db, current_user.tenant_id, project_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)

    if any(key in changes for key in ("script", "genre", "style")):
        await db.execute(
            delete(StoryboardShot).where(
                StoryboardShot.project_id == project.id,
                StoryboardShot.tenant_id == current_user.tenant_id,
            )
        )
        await db.execute(
            delete(StoryboardScene).where(
                StoryboardScene.project_id == project.id,
                StoryboardScene.tenant_id == current_user.tenant_id,
            )
        )
        project.status = "draft"
        project.scene_count = 0
        project.shot_count = 0
        project.tokens = 0
        project.model = None
        project.error = None

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="storyboard.update",
        resource_type="storyboard_project",
        resource_id=project.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(StoryboardOut.model_validate(project).model_dump(mode="json"))


@router.delete("/{project_id}", summary="删除分镜项目")
async def delete_project(
    project_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await _get_project(db, current_user.tenant_id, project_id)
    await db.execute(
        delete(StoryboardShot).where(
            StoryboardShot.project_id == project.id,
            StoryboardShot.tenant_id == current_user.tenant_id,
        )
    )
    await db.execute(
        delete(StoryboardScene).where(
            StoryboardScene.project_id == project.id,
            StoryboardScene.tenant_id == current_user.tenant_id,
        )
    )
    await db.delete(project)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="storyboard.delete",
        resource_type="storyboard_project",
        resource_id=project_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/{project_id}/generate", summary="生成分镜")
async def generate(
    project_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    project = await _get_project(db, current_user.tenant_id, project_id)
    if project.status == "generating":
        raise BadRequestError("分镜正在生成中")

    project.status = "generating"
    project.error = None
    await db.commit()

    try:
        normalized, tokens = await generate_storyboard(project)
    except LLMError as exc:
        project.status = "failed"
        project.error = str(exc)
        await db.commit()
        raise BadRequestError(str(exc)) from exc

    await db.execute(
        delete(StoryboardShot).where(
            StoryboardShot.project_id == project.id,
            StoryboardShot.tenant_id == current_user.tenant_id,
        )
    )
    await db.execute(
        delete(StoryboardScene).where(
            StoryboardScene.project_id == project.id,
            StoryboardScene.tenant_id == current_user.tenant_id,
        )
    )

    shot_count = 0
    for scene_data in normalized["scenes"]:
        scene = StoryboardScene(
            tenant_id=current_user.tenant_id,
            project_id=project.id,
            scene_index=scene_data["scene_index"],
            location=scene_data["location"],
            time_of_day=scene_data["time_of_day"],
            characters=scene_data["characters"],
            summary=scene_data["summary"],
            mood=scene_data["mood"],
        )
        db.add(scene)
        await db.flush()

        for shot_data in scene_data["shots"]:
            db.add(
                StoryboardShot(
                    tenant_id=current_user.tenant_id,
                    project_id=project.id,
                    scene_id=scene.id,
                    shot_index=shot_data["shot_index"],
                    shot_type=shot_data["shot_type"],
                    camera_movement=shot_data["camera_movement"],
                    duration_seconds=shot_data["duration_seconds"],
                    dialogue=shot_data["dialogue"],
                    description=shot_data["description"],
                    image_prompt=shot_data["image_prompt"],
                    audio_note=shot_data["audio_note"],
                )
            )
            shot_count += 1

    project.scene_count = len(normalized["scenes"])
    project.shot_count = shot_count
    project.tokens = tokens
    project.model = settings.llm_model
    project.status = "ready"
    project.error = None
    await db.flush()

    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="storyboard.generate",
        resource_type="storyboard_project",
        resource_id=project.id,
        detail={
            "scenes": project.scene_count,
            "shots": project.shot_count,
            "tokens": project.tokens,
        },
        ip_address=client_ip(request),
    )
    await db.commit()
    return success(await _build_detail(db, project))


@router.get("/{project_id}/export", summary="导出分镜")
async def export_storyboard(
    project_id: int,
    db: DbSession,
    current_user: CurrentUser,
    format: str = Query("json", pattern="^(json|csv)$"),
):
    project = await _get_project(db, current_user.tenant_id, project_id)
    detail = await _build_detail(db, project)
    filename = f"storyboard_{project.id}"
    if format == "csv":
        content = storyboard_to_csv(project, detail["scenes"])
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    return JSONResponse(
        content=detail,
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
    )
