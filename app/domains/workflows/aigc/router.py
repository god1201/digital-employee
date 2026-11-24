from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import delete, func, select, update

from app.core.base import utcnow
from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workflows.aigc.jobs import (
    compute_stats,
    create_generation,
    job_to_dict,
)
from app.domains.workflows.aigc.models import (
    AigcAsset,
    AigcJob,
    AigcPromptTemplate,
    AigcProvider,
    AigcReview,
)
from app.domains.workflows.aigc.providers import (
    DEFAULT_SUPPORTED_TYPES,
    SUPPORTED_JOB_TYPES,
    missing_placeholders,
    render_placeholders,
    test_provider_connection,
)
from app.domains.workflows.aigc.schemas import (
    AssetOut,
    AssetReviewRequest,
    GenerationCreate,
    GenerationOut,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    ReviewOut,
    TemplateCreate,
    TemplateOut,
    TemplateRenderRequest,
    TemplateUpdate,
)
from app.domains.workflows.aigc.storage import (
    delete_stored,
    mime_for_path,
    safe_upload_extension,
    save_bytes,
)

router = APIRouter(prefix="/aigc", tags=["AIGC 内容生成"])


# ---------------------------------------------------------------- helpers


async def _get_provider(db: DbSession, tenant_id: int, provider_id: int) -> AigcProvider:
    provider = await db.scalar(
        select(AigcProvider).where(
            AigcProvider.id == provider_id,
            AigcProvider.tenant_id == tenant_id,
        )
    )
    if provider is None:
        raise NotFoundError("生成服务不存在")
    return provider


async def _get_template(
    db: DbSession, tenant_id: int, template_id: int
) -> AigcPromptTemplate:
    template = await db.scalar(
        select(AigcPromptTemplate).where(
            AigcPromptTemplate.id == template_id,
            AigcPromptTemplate.tenant_id == tenant_id,
        )
    )
    if template is None:
        raise NotFoundError("提示词模板不存在")
    return template


async def _get_job(db: DbSession, tenant_id: int, job_id: int) -> AigcJob:
    job = await db.scalar(
        select(AigcJob).where(AigcJob.id == job_id, AigcJob.tenant_id == tenant_id)
    )
    if job is None:
        raise NotFoundError("生成任务不存在")
    return job


async def _get_asset(db: DbSession, tenant_id: int, asset_id: int) -> AigcAsset:
    asset = await db.scalar(
        select(AigcAsset).where(
            AigcAsset.id == asset_id, AigcAsset.tenant_id == tenant_id
        )
    )
    if asset is None:
        raise NotFoundError("素材不存在")
    return asset


async def _name_maps(db: DbSession, tenant_id: int, jobs: list[AigcJob]) -> tuple[dict, dict]:
    provider_ids = {job.provider_id for job in jobs if job.provider_id}
    template_ids = {job.template_id for job in jobs if job.template_id}
    providers: dict[int, str] = {}
    templates: dict[int, str] = {}
    if provider_ids:
        rows = await db.scalars(
            select(AigcProvider).where(
                AigcProvider.tenant_id == tenant_id,
                AigcProvider.id.in_(provider_ids),
            )
        )
        providers = {row.id: row.name for row in rows}
    if template_ids:
        rows = await db.scalars(
            select(AigcPromptTemplate).where(
                AigcPromptTemplate.tenant_id == tenant_id,
                AigcPromptTemplate.id.in_(template_ids),
            )
        )
        templates = {row.id: row.name for row in rows}
    return providers, templates


async def _unset_other_defaults(db: DbSession, tenant_id: int, provider_id: int | None) -> None:
    stmt = update(AigcProvider).where(AigcProvider.tenant_id == tenant_id)
    if provider_id is not None:
        stmt = stmt.where(AigcProvider.id != provider_id)
    await db.execute(stmt.values(is_default=False))


# ---------------------------------------------------------------- providers


@router.get("/providers", summary="生成服务列表")
async def list_providers(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    enabled: bool | None = None,
):
    conditions = [AigcProvider.tenant_id == current_user.tenant_id]
    if enabled is not None:
        conditions.append(AigcProvider.enabled.is_(enabled))
    stmt = select(AigcProvider).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(
                    AigcProvider.is_default.desc(),
                    AigcProvider.priority.desc(),
                    AigcProvider.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [ProviderOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/providers", summary="创建生成服务")
async def create_provider(
    payload: ProviderCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    duplicate = await db.scalar(
        select(AigcProvider.id).where(
            AigcProvider.tenant_id == current_user.tenant_id,
            AigcProvider.name == payload.name,
        )
    )
    if duplicate:
        raise ConflictError("同名生成服务已存在")

    data = payload.model_dump()
    api_key = data.pop("api_key", None)
    if data.get("supported_types") is None:
        data["supported_types"] = list(
            DEFAULT_SUPPORTED_TYPES.get(payload.provider_type, SUPPORTED_JOB_TYPES)
        )
    provider = AigcProvider(
        tenant_id=current_user.tenant_id,
        api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        created_by=current_user.id,
        **data,
    )
    db.add(provider)
    await db.flush()
    if provider.is_default:
        await _unset_other_defaults(db, current_user.tenant_id, provider.id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.provider.create",
        resource_type="aigc_provider",
        resource_id=provider.id,
        detail={"name": provider.name, "type": provider.provider_type},
        ip_address=client_ip(request),
    )
    return success(ProviderOut.model_validate(provider).model_dump(mode="json"))


@router.patch("/providers/{provider_id}", summary="更新生成服务")
async def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    provider = await _get_provider(db, current_user.tenant_id, provider_id)
    changes = payload.model_dump(exclude_unset=True)
    api_key = changes.pop("api_key", None)
    if "name" in changes and changes["name"] != provider.name:
        duplicate = await db.scalar(
            select(AigcProvider.id).where(
                AigcProvider.tenant_id == current_user.tenant_id,
                AigcProvider.name == changes["name"],
                AigcProvider.id != provider.id,
            )
        )
        if duplicate:
            raise ConflictError("同名生成服务已存在")
    if changes.get("supported_types") is None and "provider_type" in changes:
        changes["supported_types"] = list(
            DEFAULT_SUPPORTED_TYPES.get(
                changes["provider_type"] or "mock", SUPPORTED_JOB_TYPES
            )
        )
    for field, value in changes.items():
        setattr(provider, field, value)
    if api_key is not None:
        provider.api_key_encrypted = encrypt_secret(api_key) if api_key else None
    await db.flush()
    if provider.is_default:
        await _unset_other_defaults(db, current_user.tenant_id, provider.id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.provider.update",
        resource_type="aigc_provider",
        resource_id=provider.id,
        detail={"fields": sorted(changes.keys()) + (["api_key"] if api_key else [])},
        ip_address=client_ip(request),
    )
    return success(ProviderOut.model_validate(provider).model_dump(mode="json"))


@router.delete("/providers/{provider_id}", summary="删除生成服务")
async def delete_provider(
    provider_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    provider = await _get_provider(db, current_user.tenant_id, provider_id)
    used = await db.scalar(
        select(func.count())
        .select_from(AigcJob)
        .where(AigcJob.provider_id == provider.id)
    )
    if used:
        raise ConflictError("已有生成任务使用该服务，不能删除，可改为停用")
    await db.delete(provider)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.provider.delete",
        resource_type="aigc_provider",
        resource_id=provider_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/providers/{provider_id}/test", summary="测试生成服务连通性")
async def test_provider(
    provider_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    provider = await _get_provider(db, current_user.tenant_id, provider_id)
    result = await test_provider_connection(provider)
    return success(result)


# ---------------------------------------------------------------- templates


@router.get("/templates", summary="提示词模板列表")
async def list_templates(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    enabled: bool | None = None,
    q: str | None = None,
):
    conditions = [AigcPromptTemplate.tenant_id == current_user.tenant_id]
    if category:
        conditions.append(AigcPromptTemplate.category == category)
    if enabled is not None:
        conditions.append(AigcPromptTemplate.enabled.is_(enabled))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            AigcPromptTemplate.name.ilike(like) | AigcPromptTemplate.code.ilike(like)
        )
    stmt = select(AigcPromptTemplate).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AigcPromptTemplate.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [TemplateOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/templates", summary="创建提示词模板")
async def create_template(
    payload: TemplateCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    duplicate = await db.scalar(
        select(AigcPromptTemplate.id).where(
            AigcPromptTemplate.tenant_id == current_user.tenant_id,
            AigcPromptTemplate.code == payload.code,
        )
    )
    if duplicate:
        raise ConflictError("模板编码已存在")
    template = AigcPromptTemplate(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(template)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.template.create",
        resource_type="aigc_prompt_template",
        resource_id=template.id,
        detail={"name": template.name, "code": template.code},
        ip_address=client_ip(request),
    )
    return success(TemplateOut.model_validate(template).model_dump(mode="json"))


@router.patch("/templates/{template_id}", summary="更新提示词模板")
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    template = await _get_template(db, current_user.tenant_id, template_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != template.code:
        duplicate = await db.scalar(
            select(AigcPromptTemplate.id).where(
                AigcPromptTemplate.tenant_id == current_user.tenant_id,
                AigcPromptTemplate.code == changes["code"],
                AigcPromptTemplate.id != template.id,
            )
        )
        if duplicate:
            raise ConflictError("模板编码已存在")
    for field, value in changes.items():
        setattr(template, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.template.update",
        resource_type="aigc_prompt_template",
        resource_id=template.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(TemplateOut.model_validate(template).model_dump(mode="json"))


@router.delete("/templates/{template_id}", summary="删除提示词模板")
async def delete_template(
    template_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    template = await _get_template(db, current_user.tenant_id, template_id)
    used = await db.scalar(
        select(func.count())
        .select_from(AigcJob)
        .where(AigcJob.template_id == template.id)
    )
    if used:
        raise ConflictError("已有生成任务使用该模板，不能删除，可改为停用")
    await db.delete(template)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.template.delete",
        resource_type="aigc_prompt_template",
        resource_id=template_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/templates/{template_id}/render", summary="渲染提示词模板")
async def render_template(
    template_id: int,
    payload: TemplateRenderRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    template = await _get_template(db, current_user.tenant_id, template_id)
    values = dict(template.variables or {})
    values.update(payload.values or {})
    prompt = render_placeholders(template.body, values)
    return success(
        {
            "prompt": prompt,
            "negative_prompt": template.negative_prompt,
            "params": template.params or {},
            "missing": missing_placeholders(prompt),
        }
    )


# ---------------------------------------------------------------- generations


@router.get("/generations", summary="生成任务列表")
async def list_generations(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    job_type: str | None = None,
    provider_id: int | None = None,
):
    conditions = [AigcJob.tenant_id == current_user.tenant_id]
    if status:
        conditions.append(AigcJob.status == status)
    if job_type:
        conditions.append(AigcJob.job_type == job_type)
    if provider_id:
        conditions.append(AigcJob.provider_id == provider_id)
    stmt = select(AigcJob).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AigcJob.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    providers, templates = await _name_maps(db, current_user.tenant_id, items)
    return paged(
        [
            job_to_dict(
                job,
                provider_name=providers.get(job.provider_id),
                template_name=templates.get(job.template_id),
            )
            for job in items
        ],
        total,
        page,
        page_size,
    )


@router.post("/generations", summary="创建生成任务")
async def create_generation_job(
    payload: GenerationCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    job, provider, template = await create_generation(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        job_type=payload.job_type,
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        provider_id=payload.provider_id,
        template_id=payload.template_id,
        template_values=payload.template_values,
        employee_id=payload.employee_id,
        input_asset_id=payload.input_asset_id,
        params=payload.params,
        priority=payload.priority,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.generate",
        resource_type="aigc_job",
        resource_id=job.id,
        detail={
            "job_type": job.job_type,
            "provider": provider.name,
            "template": template.name if template else None,
            "estimated_cost": job.estimated_cost,
            "risk": job.risk.get("decision"),
        },
        ip_address=client_ip(request),
    )
    return success(
        GenerationOut.model_validate(job).model_dump(mode="json") | {
            "provider_name": provider.name,
            "template_name": template.name if template else None,
            "assets": [],
        }
    )


@router.get("/generations/{job_id}", summary="生成任务详情")
async def get_generation(
    job_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await _get_job(db, current_user.tenant_id, job_id)
    providers, templates = await _name_maps(db, current_user.tenant_id, [job])
    assets = list(
        (
            await db.scalars(
                select(AigcAsset)
                .where(
                    AigcAsset.tenant_id == current_user.tenant_id,
                    AigcAsset.job_id == job.id,
                )
                .order_by(AigcAsset.id.asc())
            )
        ).all()
    )
    return success(
        job_to_dict(
            job,
            provider_name=providers.get(job.provider_id),
            template_name=templates.get(job.template_id),
            assets=assets,
        )
    )


@router.post("/generations/{job_id}/cancel", summary="取消生成任务")
async def cancel_generation(
    job_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await _get_job(db, current_user.tenant_id, job_id)
    if job.status not in ("pending", "running"):
        raise BadRequestError("只有等待中或运行中的任务可以取消")
    job.status = "cancelled"
    job.next_run_at = None
    job.finished_at = utcnow()
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.cancel",
        resource_type="aigc_job",
        resource_id=job.id,
        ip_address=client_ip(request),
    )
    return success(GenerationOut.model_validate(job).model_dump(mode="json"))


@router.post("/generations/{job_id}/retry", summary="重试生成任务")
async def retry_generation(
    job_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await _get_job(db, current_user.tenant_id, job_id)
    if job.status not in ("failed", "cancelled"):
        raise BadRequestError("只有失败或已取消的任务可以重试")
    job.status = "pending"
    job.attempt = 0
    job.next_run_at = None
    job.error = None
    job.finished_at = None
    job.locked_by = None
    job.locked_at = None
    job.result = {}
    job.cost = 0.0
    job.latency_ms = 0
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.retry",
        resource_type="aigc_job",
        resource_id=job.id,
        ip_address=client_ip(request),
    )
    return success(GenerationOut.model_validate(job).model_dump(mode="json"))


@router.delete("/generations/{job_id}", summary="删除生成任务与素材")
async def delete_generation(
    job_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    job = await _get_job(db, current_user.tenant_id, job_id)
    if job.status in ("pending", "running"):
        raise BadRequestError("等待中或运行中的任务不能删除，请先取消")
    assets = list(
        (
            await db.scalars(
                select(AigcAsset).where(
                    AigcAsset.tenant_id == current_user.tenant_id,
                    AigcAsset.job_id == job.id,
                )
            )
        ).all()
    )
    if assets:
        referenced = await db.scalar(
            select(func.count())
            .select_from(AigcJob)
            .where(
                AigcJob.input_asset_id.in_([asset.id for asset in assets]),
                AigcJob.id != job.id,
            )
        )
        if referenced:
            raise BadRequestError("该任务生成的素材被其他任务作为输入引用，不能删除")
    for asset in assets:
        delete_stored(asset.storage_path)
    if assets:
        await db.execute(
            delete(AigcReview).where(
                AigcReview.tenant_id == current_user.tenant_id,
                AigcReview.asset_id.in_([asset.id for asset in assets]),
            )
        )
        await db.execute(
            delete(AigcAsset).where(
                AigcAsset.tenant_id == current_user.tenant_id,
                AigcAsset.job_id == job.id,
            )
        )
    await db.delete(job)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.job.delete",
        resource_type="aigc_job",
        resource_id=job_id,
        detail={"assets": len(assets)},
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


# ---------------------------------------------------------------- assets


@router.get("/assets", summary="素材库列表")
async def list_assets(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=200),
    asset_type: str | None = None,
    review_status: str | None = None,
    source: str | None = None,
    job_id: int | None = None,
    q: str | None = None,
):
    conditions = [AigcAsset.tenant_id == current_user.tenant_id]
    if asset_type:
        conditions.append(AigcAsset.asset_type == asset_type)
    if review_status:
        conditions.append(AigcAsset.review_status == review_status)
    if source:
        conditions.append(AigcAsset.source == source)
    if job_id:
        conditions.append(AigcAsset.job_id == job_id)
    if q:
        conditions.append(AigcAsset.prompt.ilike(f"%{q.strip()}%"))
    stmt = select(AigcAsset).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(AigcAsset.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [AssetOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/assets/upload", summary="上传源图片")
async def upload_asset(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    content_type = (file.content_type or "").lower()
    extension = safe_upload_extension(file.filename, content_type)
    detected_mime = (
        content_type if content_type.startswith("image/") else mime_for_path(file.filename)
    )
    if not detected_mime.startswith("image/"):
        raise BadRequestError("只支持上传图片文件")
    if detected_mime.split(";")[0].strip() == "image/svg+xml" or extension == "svg":
        raise BadRequestError("为安全起见不支持上传 SVG，请使用 PNG/JPG/WebP")

    data = await file.read(settings.aigc_upload_max_bytes + 1)
    if not data:
        raise BadRequestError("上传文件为空")
    if len(data) > settings.aigc_upload_max_bytes:
        raise BadRequestError(
            f"图片超过大小限制（{settings.aigc_upload_max_bytes // (1024 * 1024)}MB）"
        )

    storage_path, public_url = save_bytes(current_user.tenant_id, data, extension)
    mime_type = detected_mime or mime_for_path(storage_path)
    asset = AigcAsset(
        tenant_id=current_user.tenant_id,
        job_id=None,
        asset_type="image",
        source="uploaded",
        storage_path=storage_path,
        public_url=public_url,
        thumbnail_url=public_url,
        file_name=file.filename,
        mime_type=mime_type,
        size_bytes=len(data),
        prompt="",
        negative_prompt="",
        provider_name=None,
        model=None,
        review_status="approved",
        review_note="用户上传的源图片",
        reviewed_by=current_user.id,
        reviewed_at=utcnow(),
        tags=[],
        metadata_={"uploaded": True},
        created_by=current_user.id,
    )
    db.add(asset)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.asset.upload",
        resource_type="aigc_asset",
        resource_id=asset.id,
        detail={"file": file.filename, "size": len(data)},
        ip_address=client_ip(request),
    )
    return success(AssetOut.model_validate(asset).model_dump(mode="json"))


@router.get("/assets/{asset_id}", summary="素材详情")
async def get_asset(
    asset_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    asset = await _get_asset(db, current_user.tenant_id, asset_id)
    return success(AssetOut.model_validate(asset).model_dump(mode="json"))


@router.get("/assets/{asset_id}/reviews", summary="素材审核记录")
async def list_asset_reviews(
    asset_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await _get_asset(db, current_user.tenant_id, asset_id)
    items = list(
        (
            await db.scalars(
                select(AigcReview)
                .where(
                    AigcReview.tenant_id == current_user.tenant_id,
                    AigcReview.asset_id == asset_id,
                )
                .order_by(AigcReview.id.desc())
            )
        ).all()
    )
    return success(
        [ReviewOut.model_validate(item).model_dump(mode="json") for item in items]
    )


@router.post("/assets/{asset_id}/review", summary="审核素材")
async def review_asset(
    asset_id: int,
    payload: AssetReviewRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    asset = await _get_asset(db, current_user.tenant_id, asset_id)
    asset.review_status = "approved" if payload.decision == "approve" else "rejected"
    asset.review_note = payload.note
    asset.reviewed_by = current_user.id
    asset.reviewed_at = utcnow()
    review = AigcReview(
        tenant_id=current_user.tenant_id,
        asset_id=asset.id,
        decision=payload.decision,
        score=payload.score,
        note=payload.note,
        reviewer_id=current_user.id,
    )
    db.add(review)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.asset.review",
        resource_type="aigc_asset",
        resource_id=asset.id,
        detail={"decision": payload.decision, "note": payload.note},
        ip_address=client_ip(request),
    )
    return success(
        {
            "asset": AssetOut.model_validate(asset).model_dump(mode="json"),
            "review": ReviewOut.model_validate(review).model_dump(mode="json"),
        }
    )


@router.delete("/assets/{asset_id}", summary="删除素材")
async def delete_asset(
    asset_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    asset = await _get_asset(db, current_user.tenant_id, asset_id)
    used = await db.scalar(
        select(func.count()).select_from(AigcJob).where(AigcJob.input_asset_id == asset.id)
    )
    if used:
        raise BadRequestError("该图片已被生成任务引用，不能删除")
    delete_stored(asset.storage_path)
    await db.execute(
        delete(AigcReview).where(
            AigcReview.tenant_id == current_user.tenant_id,
            AigcReview.asset_id == asset.id,
        )
    )
    await db.delete(asset)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="aigc.asset.delete",
        resource_type="aigc_asset",
        resource_id=asset_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


# ---------------------------------------------------------------- stats


@router.get("/stats", summary="AIGC 成本与产出统计")
async def aigc_stats(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(7, ge=1, le=90),
):
    return success(await compute_stats(db, current_user.tenant_id, days=days))
