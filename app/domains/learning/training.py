"""DPO/RLHF 数据资产：偏好对采集、JSONL 导出与训练任务台账。"""

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.deps import hash_callback_token
from app.core.exceptions import BadRequestError, NotFoundError
from app.domains.learning.models import (
    EvaluationRun,
    FeedbackSample,
    InterventionDelta,
    PreferencePair,
    TrainingJob,
)
from app.domains.learning.schemas import (
    PreferenceCollectRequest,
    PreferenceExportRequest,
    TrainingJobCreate,
    TrainingJobStatusUpdate,
)
from app.domains.workflows.tasks.models import TaskInstance

TRAINING_DIR = Path("data/training")
MAX_PAIRS = 5000


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def _instance_prompt(db: AsyncSession, instance_id: int | None) -> str:
    if not instance_id:
        return ""
    instance = await db.get(TaskInstance, instance_id)
    if instance is None:
        return ""
    request = ""
    if isinstance(instance.input, dict):
        request = str(instance.input.get("request") or instance.input.get("prompt") or "")
    return f"{instance.title}\n{request}".strip()


def _expected_text(expected: dict) -> str:
    if not isinstance(expected, dict):
        return str(expected or "")
    if expected.get("text"):
        return str(expected["text"])
    if expected.get("keywords"):
        return "、".join(str(item) for item in expected["keywords"])
    if expected.get("exact") is not None:
        return str(expected["exact"])
    return ""


async def collect_preference_pairs(
    db: AsyncSession,
    tenant_id: int,
    payload: PreferenceCollectRequest,
    *,
    user_id: int | None = None,
) -> dict:
    sources = set(payload.sources)
    limit = max(1, min(payload.limit, MAX_PAIRS))
    candidates: list[dict] = []

    if "intervention" in sources:
        conditions = [InterventionDelta.tenant_id == tenant_id]
        if payload.employee_id is not None:
            conditions.append(InterventionDelta.employee_id == payload.employee_id)
        deltas = list(
            (
                await db.scalars(
                    select(InterventionDelta)
                    .where(*conditions)
                    .order_by(InterventionDelta.id.desc())
                    .limit(limit)
                )
            ).all()
        )
        for delta in deltas:
            if not delta.original_output or not delta.final_output:
                continue
            if _dumps(delta.original_output) == _dumps(delta.final_output):
                continue
            candidates.append(
                {
                    "employee_id": delta.employee_id,
                    "source_type": "intervention",
                    "source_ref": f"intervention:{delta.id}",
                    "prompt": await _instance_prompt(db, delta.instance_id)
                    or (delta.comment or "人工接管纠错"),
                    "chosen": _dumps(delta.final_output),
                    "rejected": _dumps(delta.original_output),
                    "chosen_score": 1.0,
                    "rejected_score": 0.0,
                    "pair_metadata": {
                        "comment": delta.comment,
                        "diff": delta.diff,
                        "trace_id": delta.trace_id,
                    },
                }
            )

    if "evaluation" in sources:
        conditions = [EvaluationRun.tenant_id == tenant_id]
        if payload.employee_id is not None:
            conditions.append(EvaluationRun.employee_id == payload.employee_id)
        runs = list(
            (
                await db.scalars(
                    select(EvaluationRun)
                    .where(*conditions)
                    .order_by(EvaluationRun.id.desc())
                    .limit(20)
                )
            ).all()
        )
        for run in runs:
            for detail in run.details or []:
                actual = str(detail.get("actual") or "").strip()
                expected = _expected_text(detail.get("expected") or {})
                score = float(detail.get("score") or 0)
                if not actual or not expected or score >= 0.999:
                    continue
                candidates.append(
                    {
                        "employee_id": run.employee_id,
                        "source_type": "evaluation",
                        "source_ref": f"evaluation:{run.id}:{detail.get('case_id')}",
                        "prompt": str(detail.get("name") or "评估用例"),
                        "chosen": expected,
                        "rejected": actual,
                        "chosen_score": 1.0,
                        "rejected_score": score,
                        "pair_metadata": {
                            "run_id": run.id,
                            "case_id": detail.get("case_id"),
                        },
                    }
                )

    if "feedback" in sources:
        conditions = [FeedbackSample.tenant_id == tenant_id]
        if payload.employee_id is not None:
            conditions.append(FeedbackSample.employee_id == payload.employee_id)
        samples = list(
            (
                await db.scalars(
                    select(FeedbackSample)
                    .where(*conditions)
                    .order_by(FeedbackSample.id.desc())
                    .limit(limit)
                )
            ).all()
        )
        for sample in samples:
            if not sample.corrected_output:
                continue
            instance = (
                await db.get(TaskInstance, sample.instance_id)
                if sample.instance_id
                else None
            )
            if instance is None or not instance.output:
                continue
            candidates.append(
                {
                    "employee_id": sample.employee_id or instance.employee_id,
                    "source_type": "feedback",
                    "source_ref": f"feedback:{sample.id}",
                    "prompt": await _instance_prompt(db, sample.instance_id)
                    or (sample.comment or "人工反馈修正"),
                    "chosen": _dumps(sample.corrected_output),
                    "rejected": _dumps(instance.output),
                    "chosen_score": 1.0,
                    "rejected_score": round(sample.rating / 5.0, 4),
                    "pair_metadata": {
                        "rating": sample.rating,
                        "verdict": sample.verdict,
                        "comment": sample.comment,
                    },
                }
            )

    refs = [item["source_ref"] for item in candidates]
    existing = set()
    if refs:
        existing = set(
            (
                await db.scalars(
                    select(PreferencePair.source_ref).where(
                        PreferencePair.tenant_id == tenant_id,
                        PreferencePair.source_ref.in_(refs),
                    )
                )
            ).all()
        )

    created: list[PreferencePair] = []
    skipped = 0
    for item in candidates:
        if item["source_ref"] in existing:
            skipped += 1
            continue
        if len(created) >= limit:
            skipped += 1
            continue
        pair = PreferencePair(
            tenant_id=tenant_id,
            created_by=user_id,
            status="draft",
            **item,
        )
        db.add(pair)
        created.append(pair)
    await db.flush()
    return {"created": len(created), "skipped": skipped, "pairs": created}


async def export_pairs(
    db: AsyncSession,
    tenant_id: int,
    payload: PreferenceExportRequest,
    *,
    user_id: int | None = None,
) -> dict:
    conditions = [PreferencePair.tenant_id == tenant_id, PreferencePair.status == "draft"]
    if payload.employee_id is not None:
        conditions.append(PreferencePair.employee_id == payload.employee_id)
    if payload.pair_ids:
        conditions.append(PreferencePair.id.in_(payload.pair_ids))
    pairs = list(
        (
            await db.scalars(
                select(PreferencePair)
                .where(*conditions)
                .order_by(PreferencePair.id)
                .limit(MAX_PAIRS)
            )
        ).all()
    )
    if not pairs:
        raise BadRequestError("没有可导出的偏好对")

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = TRAINING_DIR / f"dpo_{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(
                json.dumps(
                    {
                        "prompt": pair.prompt,
                        "chosen": pair.chosen,
                        "rejected": pair.rejected,
                        "metadata": pair.pair_metadata or {},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    for pair in pairs:
        pair.status = "exported"
    await db.flush()
    return {"path": str(path), "count": len(pairs), "bytes": path.stat().st_size}


async def create_training_job(
    db: AsyncSession,
    tenant_id: int,
    payload: TrainingJobCreate,
    *,
    user_id: int | None = None,
) -> TrainingJob:
    base = TRAINING_DIR.resolve()
    dataset = Path(payload.dataset_path).resolve()
    try:
        dataset.relative_to(base)
    except ValueError as exc:
        raise BadRequestError("数据集必须位于 data/training 目录下") from exc
    if not dataset.is_file():
        raise NotFoundError("数据集文件不存在")

    line_count = 0
    with dataset.open("r", encoding="utf-8") as handle:
        for _line in handle:
            line_count += 1

    job = TrainingJob(
        tenant_id=tenant_id,
        employee_id=payload.employee_id,
        method=payload.method,
        dataset_path=str(dataset),
        dataset_size=line_count,
        status="pending",
        config=payload.config,
        metrics={},
        created_by=user_id,
    )
    db.add(job)
    await db.flush()
    return job


def build_dispatch_payload(job: TrainingJob, lines: list[str]) -> dict:
    dataset = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            dataset.append(json.loads(line))
        except json.JSONDecodeError:
            dataset.append({"raw": line})
    return {
        "job_id": job.id,
        "method": job.method,
        "config": job.config or {},
        "dataset_size": len(dataset),
        "dataset": dataset,
    }


async def dispatch_training_job(db: AsyncSession, job: TrainingJob) -> TrainingJob:
    if job.status != "pending":
        raise BadRequestError(f"只有 pending 任务可以派发，当前 {job.status}")
    if not settings.training_provider_url:
        raise BadRequestError("未配置 TRAINING_PROVIDER_URL，无法派发外部 trainer")
    parsed = urlparse(settings.training_provider_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BadRequestError("TRAINING_PROVIDER_URL 必须是 http(s) 地址")

    dataset = Path(job.dataset_path)
    if not dataset.is_file():
        raise NotFoundError("训练数据集文件不存在")
    if dataset.stat().st_size > settings.training_dataset_max_bytes:
        raise BadRequestError(
            f"训练数据集超过上限 {settings.training_dataset_max_bytes} 字节"
        )
    lines = dataset.read_text(encoding="utf-8").splitlines()
    payload = build_dispatch_payload(job, lines)
    callback_token = secrets.token_urlsafe(32)
    payload["callback_token"] = callback_token
    job.config = {
        **(job.config or {}),
        "callback_token_hash": hash_callback_token(callback_token),
    }

    headers = {"Content-Type": "application/json"}
    if settings.training_provider_api_key:
        headers["Authorization"] = f"Bearer {settings.training_provider_api_key}"
    try:
        async with httpx.AsyncClient(
            timeout=settings.training_provider_timeout
        ) as client:
            response = await client.post(
                settings.training_provider_url, headers=headers, json=payload
            )
    except httpx.HTTPError as exc:
        job.error = f"派发失败: {exc}"
        await db.commit()
        raise BadRequestError(f"外部 trainer 不可达: {exc}") from exc

    if response.status_code >= 400:
        job.error = f"派发失败（{response.status_code}）: {response.text[:300]}"
        await db.commit()
        raise BadRequestError(job.error)

    body = {}
    try:
        body = response.json()
    except ValueError:
        body = {}
    job.status = "dispatched"
    job.started_at = utcnow()
    job.metrics = {
        **(job.metrics or {}),
        "dispatch": {
            "external_job_id": body.get("job_id") or body.get("id"),
            "status_code": response.status_code,
            "dispatched_at": utcnow().isoformat(),
        },
    }
    job.error = None
    await db.flush()
    return job


def apply_job_status(job: TrainingJob, payload: TrainingJobStatusUpdate) -> None:
    transitions = {
        "pending": {"dispatched", "running", "cancelled"},
        "dispatched": {"running", "failed", "cancelled"},
        "running": {"succeeded", "failed", "cancelled"},
    }
    if job.status not in transitions or payload.status not in transitions[job.status]:
        raise BadRequestError(f"训练任务状态不可从 {job.status} 变为 {payload.status}")
    now = utcnow()
    job.status = payload.status
    if payload.status == "running":
        job.started_at = now
    if payload.status in {"succeeded", "failed", "cancelled"}:
        job.finished_at = now
    # 外部 trainer 回调的指标与派发元信息合并，避免覆盖 dispatch 记录
    job.metrics = {**(job.metrics or {}), **(payload.metrics or {})}
    job.error = payload.error
