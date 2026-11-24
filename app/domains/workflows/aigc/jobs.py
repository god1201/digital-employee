"""AIGC 生成任务：创建、执行、素材落库与成本统计。"""

import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.governance.risk.service import evaluate_risk
from app.domains.workflows.aigc.models import AigcAsset, AigcJob, AigcPromptTemplate, AigcProvider
from app.domains.workflows.aigc.providers import (
    JOB_TYPE_LABELS,
    ProviderError,
    build_provider,
    estimate_cost,
    missing_placeholders,
    render_placeholders,
)
from app.domains.workflows.aigc.schemas import AssetOut, GenerationOut
from app.domains.workflows.aigc.storage import save_bytes
from app.domains.workforce.employees.models import DigitalEmployee

logger = logging.getLogger(__name__)


async def resolve_provider(
    db: AsyncSession, tenant_id: int, provider_id: int | None, job_type: str
) -> AigcProvider:
    if provider_id:
        provider = await db.scalar(
            select(AigcProvider).where(
                AigcProvider.id == provider_id,
                AigcProvider.tenant_id == tenant_id,
            )
        )
        if provider is None:
            raise NotFoundError("生成服务不存在")
        if not provider.enabled:
            raise BadRequestError("生成服务已停用")
        supported = provider.supported_types or []
        if job_type not in supported:
            label = JOB_TYPE_LABELS.get(job_type, job_type)
            raise BadRequestError(f"生成服务「{provider.name}」不支持{label}")
        return provider

    providers = list(
        (
            await db.scalars(
                select(AigcProvider)
                .where(
                    AigcProvider.tenant_id == tenant_id,
                    AigcProvider.enabled.is_(True),
                )
                .order_by(
                    AigcProvider.is_default.desc(),
                    AigcProvider.priority.desc(),
                    AigcProvider.id.asc(),
                )
            )
        ).all()
    )
    for provider in providers:
        if job_type in (provider.supported_types or []):
            return provider

    label = JOB_TYPE_LABELS.get(job_type, job_type)
    raise BadRequestError(f"没有可用于{label}的生成服务，请先添加生成服务")


async def resolve_template(
    db: AsyncSession, tenant_id: int, template_id: int | None, job_type: str
) -> AigcPromptTemplate | None:
    if not template_id:
        return None
    template = await db.scalar(
        select(AigcPromptTemplate).where(
            AigcPromptTemplate.id == template_id,
            AigcPromptTemplate.tenant_id == tenant_id,
        )
    )
    if template is None:
        raise NotFoundError("提示词模板不存在")
    if not template.enabled:
        raise BadRequestError("提示词模板已停用")
    if template.category != job_type:
        label = JOB_TYPE_LABELS.get(template.category, template.category)
        raise BadRequestError(f"提示词模板属于{label}，与当前生成类型不匹配")
    return template


def build_prompt(
    template: AigcPromptTemplate | None,
    prompt: str | None,
    negative_prompt: str | None,
    template_values: dict | None,
) -> tuple[str, str]:
    if template is None:
        final_prompt = (prompt or "").strip()
        final_negative = (negative_prompt or "").strip()
    else:
        final_prompt = (prompt or "").strip()
        if not final_prompt:
            values = dict(template.variables or {})
            values.update(template_values or {})
            rendered = render_placeholders(template.body, values)
            missing = missing_placeholders(rendered)
            if missing:
                raise BadRequestError(f"提示词模板缺少变量: {', '.join(missing)}")
            final_prompt = rendered
        final_negative = (negative_prompt or "").strip() or (template.negative_prompt or "")

    if not final_prompt:
        raise BadRequestError("请输入提示词或选择提示词模板")
    if len(final_prompt) > 8000:
        raise BadRequestError("提示词过长，请控制在 8000 字以内")
    return final_prompt, final_negative


async def create_generation(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int | None,
    job_type: str,
    prompt: str | None = None,
    negative_prompt: str | None = None,
    provider_id: int | None = None,
    template_id: int | None = None,
    template_values: dict | None = None,
    employee_id: int | None = None,
    input_asset_id: int | None = None,
    params: dict | None = None,
    priority: int = 100,
) -> tuple[AigcJob, AigcProvider, AigcPromptTemplate | None]:
    provider = await resolve_provider(db, tenant_id, provider_id, job_type)
    template = await resolve_template(db, tenant_id, template_id, job_type)
    final_prompt, final_negative = build_prompt(
        template, prompt, negative_prompt, template_values
    )

    merged_params = dict(template.params or {}) if template else {}
    merged_params.update(params or {})

    source_asset: AigcAsset | None = None
    if job_type == "image_to_video":
        if not input_asset_id:
            raise BadRequestError("图生视频需要选择一张输入图片")
        source_asset = await db.scalar(
            select(AigcAsset).where(
                AigcAsset.id == input_asset_id,
                AigcAsset.tenant_id == tenant_id,
            )
        )
        if source_asset is None or source_asset.asset_type != "image":
            raise NotFoundError("输入图片不存在")
        if source_asset.review_status == "rejected":
            raise BadRequestError("输入图片已被审核驳回，不能用于生成")
    else:
        input_asset_id = None

    if employee_id:
        employee = await db.get(DigitalEmployee, employee_id)
        if employee is None or employee.tenant_id != tenant_id:
            raise NotFoundError("数字员工不存在")

    risk = await evaluate_risk(
        db, tenant_id, f"{final_prompt}\n{final_negative}", category="content"
    )
    if risk["decision"] == "block":
        names = "、".join(sorted({item["name"] for item in risk["matched_rules"]}))
        raise BadRequestError(f"提示词命中内容风控规则，已拒绝生成: {names}")

    job = AigcJob(
        tenant_id=tenant_id,
        provider_id=provider.id,
        template_id=template.id if template else None,
        employee_id=employee_id,
        job_type=job_type,
        prompt=final_prompt,
        negative_prompt=final_negative,
        params=merged_params,
        input_asset_id=input_asset_id,
        status="pending",
        priority=priority,
        attempt=0,
        max_attempts=max(1, int(settings.aigc_job_max_attempts)),
        risk=risk,
        estimated_cost=estimate_cost(provider, job_type, merged_params),
        trace_id=uuid4().hex,
        created_by=user_id,
    )
    db.add(job)
    await db.flush()

    if template is not None:
        template.usage_count = (template.usage_count or 0) + 1
    return job, provider, template


async def _persist_media(
    db: AsyncSession,
    *,
    tenant_id: int,
    job: AigcJob,
    provider_name: str | None,
    model: str | None,
    media,
    created_by: int | None,
) -> AigcAsset | None:
    if media.data is None:
        if not media.url:
            return None
        storage_path = None
        public_url = media.url
        size_bytes = 0
        file_name = Path(str(media.url).split("?")[0]).name or None
    else:
        storage_path, public_url = await asyncio.to_thread(
            save_bytes, tenant_id, media.data, media.extension
        )
        size_bytes = len(media.data)
        file_name = Path(storage_path).name

    mime_type = media.mime_type or "application/octet-stream"
    if mime_type.startswith("video/"):
        asset_type = "video"
    elif job.job_type != "text_to_image" and (media.metadata or {}).get("mock"):
        asset_type = "video"
    else:
        asset_type = "image"

    metadata = {
        **(media.metadata or {}),
        "job_type": job.job_type,
        "risk": job.risk or {},
        "estimated_cost": job.estimated_cost,
    }
    asset = AigcAsset(
        tenant_id=tenant_id,
        job_id=job.id,
        asset_type=asset_type,
        source="generated",
        storage_path=storage_path,
        public_url=public_url,
        thumbnail_url=public_url if asset_type == "image" else None,
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
        prompt=job.prompt,
        negative_prompt=job.negative_prompt,
        provider_name=provider_name,
        model=model,
        review_status="pending",
        tags=[],
        metadata_=metadata,
        created_by=created_by,
    )
    db.add(asset)
    await db.flush()
    return asset


async def execute_job(job_id: int) -> None:
    """执行一个已领取的生成任务。失败只记录状态，重试交给 Worker。"""
    async with SessionLocal() as session:
        job = await session.get(AigcJob, job_id)
        if job is None or job.status != "running":
            return
        provider_row = (
            await session.get(AigcProvider, job.provider_id) if job.provider_id else None
        )
        input_snapshot = None
        if job.input_asset_id:
            source = await session.get(AigcAsset, job.input_asset_id)
            if source is not None and source.tenant_id == job.tenant_id:
                input_snapshot = {
                    "public_url": source.public_url,
                    "storage_path": source.storage_path,
                    "mime_type": source.mime_type,
                    "file_name": source.file_name,
                }
        snapshot = {
            "tenant_id": job.tenant_id,
            "job_type": job.job_type,
            "prompt": job.prompt,
            "negative_prompt": job.negative_prompt,
            "params": dict(job.params or {}),
            "risk": dict(job.risk or {}),
            "created_by": job.created_by,
        }
        provider_name = provider_row.name if provider_row else None

    if provider_row is None:
        await _mark_failed(job_id, "生成服务不存在或已删除", 0)
        return

    started = time.monotonic()
    try:
        provider = build_provider(provider_row)
        media_list = await provider.generate(
            job_type=snapshot["job_type"],
            prompt=snapshot["prompt"],
            negative_prompt=snapshot["negative_prompt"],
            params=snapshot["params"],
            input_asset=input_snapshot,
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        message = str(exc) or exc.__class__.__name__
        if not isinstance(exc, ProviderError):
            logger.exception("AIGC 任务 %s 执行异常", job_id)
        await _mark_failed(job_id, message, latency)
        return

    latency = int((time.monotonic() - started) * 1000)
    try:
        async with SessionLocal() as session:
            job = await session.get(AigcJob, job_id)
            if job is None:
                return
            if job.status == "cancelled":
                logger.info("AIGC 任务 %s 已取消，丢弃生成结果", job_id)
                return

            asset_ids: list[int] = []
            total_cost = 0.0
            for media in media_list:
                asset = await _persist_media(
                    session,
                    tenant_id=snapshot["tenant_id"],
                    job=job,
                    provider_name=provider_name,
                    model=provider_row.model,
                    media=media,
                    created_by=snapshot["created_by"],
                )
                if asset is not None:
                    asset_ids.append(asset.id)
                total_cost += float(media.cost or 0.0)

            job.status = "succeeded"
            job.error = None
            job.cost = round(total_cost, 4)
            job.latency_ms = latency
            job.result = {"asset_ids": asset_ids, "count": len(asset_ids)}
            job.finished_at = utcnow()
            await session.commit()
            logger.info(
                "AIGC 任务 %s 完成：%s 个素材，耗时 %sms",
                job_id,
                len(asset_ids),
                latency,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AIGC 任务 %s 保存生成结果失败", job_id)
        await _mark_failed(job_id, f"保存生成结果失败: {exc}", latency)


async def _mark_failed(job_id: int, message: str, latency_ms: int) -> None:
    async with SessionLocal() as session:
        job = await session.get(AigcJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error = message[:4000]
        job.latency_ms = latency_ms
        job.finished_at = utcnow()
        await session.commit()
    logger.warning("AIGC 任务 %s 失败: %s", job_id, message[:300])


def asset_to_dict(asset: AigcAsset) -> dict:
    return AssetOut.model_validate(asset).model_dump(mode="json")


def job_to_dict(
    job: AigcJob,
    *,
    provider_name: str | None = None,
    template_name: str | None = None,
    assets: list[AigcAsset] | None = None,
) -> dict:
    data = GenerationOut.model_validate(job).model_dump(mode="json")
    data["provider_name"] = provider_name
    data["template_name"] = template_name
    data["assets"] = [asset_to_dict(asset) for asset in assets or []]
    return data


async def compute_stats(db: AsyncSession, tenant_id: int, days: int = 7) -> dict:
    since = utcnow() - timedelta(days=days)
    jobs = list(
        (
            await db.scalars(
                select(AigcJob).where(
                    AigcJob.tenant_id == tenant_id,
                    AigcJob.created_at >= since,
                )
            )
        ).all()
    )
    assets = list(
        (await db.scalars(select(AigcAsset).where(AigcAsset.tenant_id == tenant_id))).all()
    )
    providers = list(
        (
            await db.scalars(
                select(AigcProvider).where(AigcProvider.tenant_id == tenant_id)
            )
        ).all()
    )
    provider_names = {provider.id: provider.name for provider in providers}

    by_type: dict[str, dict] = {
        key: {
            "job_type": key,
            "label": label,
            "jobs": 0,
            "succeeded": 0,
            "failed": 0,
            "cost": 0.0,
        }
        for key, label in JOB_TYPE_LABELS.items()
    }
    by_provider: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    today = utcnow().date()
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        daily[day] = {"date": day, "jobs": 0, "succeeded": 0, "failed": 0, "cost": 0.0}

    succeeded = failed = total_cost = 0
    latency_total = latency_count = 0
    for job in jobs:
        bucket = by_type.setdefault(
            job.job_type,
            {
                "job_type": job.job_type,
                "label": JOB_TYPE_LABELS.get(job.job_type, job.job_type),
                "jobs": 0,
                "succeeded": 0,
                "failed": 0,
                "cost": 0.0,
            },
        )
        bucket["jobs"] += 1
        bucket["cost"] += float(job.cost or 0)
        provider_key = provider_names.get(job.provider_id, "未知服务")
        provider_bucket = by_provider.setdefault(
            provider_key,
            {"provider": provider_key, "jobs": 0, "succeeded": 0, "failed": 0, "cost": 0.0},
        )
        provider_bucket["jobs"] += 1
        provider_bucket["cost"] += float(job.cost or 0)

        created = job.created_at
        day_key = (created.date() if created else today).isoformat()
        day_bucket = daily.setdefault(
            day_key, {"date": day_key, "jobs": 0, "succeeded": 0, "failed": 0, "cost": 0.0}
        )
        day_bucket["jobs"] += 1
        day_bucket["cost"] += float(job.cost or 0)

        if job.status == "succeeded":
            succeeded += 1
            bucket["succeeded"] += 1
            provider_bucket["succeeded"] += 1
            day_bucket["succeeded"] += 1
            latency_total += int(job.latency_ms or 0)
            latency_count += 1
        elif job.status == "failed":
            failed += 1
            bucket["failed"] += 1
            provider_bucket["failed"] += 1
            day_bucket["failed"] += 1
        total_cost += float(job.cost or 0)

    finished = succeeded + failed
    pending_review = sum(1 for asset in assets if asset.review_status == "pending")
    return {
        "days": days,
        "totals": {
            "jobs": len(jobs),
            "succeeded": succeeded,
            "failed": failed,
            "pending": sum(1 for job in jobs if job.status == "pending"),
            "running": sum(1 for job in jobs if job.status == "running"),
            "cancelled": sum(1 for job in jobs if job.status == "cancelled"),
            "success_rate": round(succeeded / finished, 4) if finished else 0.0,
            "cost": round(total_cost, 4),
            "avg_latency_ms": round(latency_total / latency_count) if latency_count else 0,
        },
        "assets": {
            "total": len(assets),
            "images": sum(1 for asset in assets if asset.asset_type == "image"),
            "videos": sum(1 for asset in assets if asset.asset_type == "video"),
            "pending_review": pending_review,
            "approved": sum(1 for asset in assets if asset.review_status == "approved"),
            "rejected": sum(1 for asset in assets if asset.review_status == "rejected"),
        },
        "by_type": list(by_type.values()),
        "by_provider": sorted(
            by_provider.values(), key=lambda item: item["jobs"], reverse=True
        ),
        "daily": list(daily.values()),
    }
