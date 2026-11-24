"""AIGC 生成任务 Worker。

与任务 Worker 相同的设计：``aigc_jobs`` 同时作为队列表，条件 UPDATE 原子领取，
失败按指数退避重试，进程重启时回收僵死的 running 任务。
"""

import asyncio
import logging
import os
import socket
import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select, update

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.domains.operations.service import update_heartbeat
from app.domains.workflows.aigc.jobs import execute_job
from app.domains.workflows.aigc.models import AigcJob
from app.domains.workflows.tasks.worker import is_retryable

logger = logging.getLogger(__name__)


async def claim_next_job(worker_id: str) -> int | None:
    now = utcnow()
    async with SessionLocal() as session:
        candidate = await session.scalar(
            select(AigcJob.id)
            .where(
                AigcJob.status == "pending",
                or_(AigcJob.next_run_at.is_(None), AigcJob.next_run_at <= now),
                AigcJob.attempt < AigcJob.max_attempts,
            )
            .order_by(AigcJob.priority.desc(), AigcJob.id.asc())
            .limit(1)
        )
        if candidate is None:
            return None

        result = await session.execute(
            update(AigcJob)
            .where(AigcJob.id == candidate, AigcJob.status == "pending")
            .values(
                status="running",
                locked_by=worker_id,
                locked_at=now,
                attempt=AigcJob.attempt + 1,
                next_run_at=None,
                started_at=func.coalesce(AigcJob.started_at, now),
                error=None,
                finished_at=None,
            )
        )
        await session.commit()
        if (result.rowcount or 0) != 1:
            return None
        return candidate


async def _finalize(job_id: int, worker_id: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(AigcJob, job_id)
        if job is None or job.locked_by != worker_id:
            return

        job.locked_by = None
        job.locked_at = None

        if job.status == "failed" and job.attempt < job.max_attempts:
            if is_retryable(job.error):
                delay = min(
                    settings.task_retry_base_seconds * (2 ** max(0, job.attempt - 1)),
                    settings.task_retry_max_seconds,
                )
                job.status = "pending"
                job.next_run_at = utcnow() + timedelta(seconds=delay)
                job.finished_at = None
                logger.warning(
                    "AIGC 任务 %s 失败，%ss 后重试（%s/%s）: %s",
                    job_id,
                    delay,
                    job.attempt,
                    job.max_attempts,
                    (job.error or "")[:200],
                )
        await session.commit()


async def _execute(job_id: int, worker_id: str) -> None:
    try:
        await execute_job(job_id)
    except Exception:  # noqa: BLE001
        logger.exception("AIGC 任务执行异常: %s", job_id)
    finally:
        await _finalize(job_id, worker_id)


async def recover_stale_jobs() -> int:
    """回收进程异常退出后遗留的 running 生成任务。"""
    cutoff = utcnow() - timedelta(seconds=settings.aigc_stale_seconds)
    async with SessionLocal() as session:
        result = await session.execute(
            update(AigcJob)
            .where(
                AigcJob.status == "running",
                AigcJob.locked_at.is_not(None),
                AigcJob.locked_at < cutoff,
            )
            .values(
                status="pending",
                locked_by=None,
                locked_at=None,
                next_run_at=None,
                attempt=0,
                finished_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        count = result.rowcount or 0

    if count:
        logger.warning("已回收 %s 个僵死 AIGC 任务", count)
    return count


async def run_aigc_worker(stop_event: asyncio.Event | None = None) -> None:
    hostname = socket.gethostname()
    pid = os.getpid()
    worker_id = f"aigc-{hostname}-{pid}-{uuid.uuid4().hex[:6]}"
    started_at = utcnow()
    poll_interval = max(0.2, float(settings.aigc_worker_poll_interval))
    concurrency = max(1, int(settings.aigc_worker_concurrency))
    running: set[asyncio.Task] = set()
    next_heartbeat = 0.0

    logger.info("AIGC Worker 启动: %s（并发 %s）", worker_id, concurrency)
    try:
        while stop_event is None or not stop_event.is_set():
            now_monotonic = asyncio.get_event_loop().time()
            if now_monotonic >= next_heartbeat:
                try:
                    await update_heartbeat(
                        worker_id,
                        hostname=hostname,
                        pid=pid,
                        status="running",
                        current_tasks=len(running),
                        started_at=started_at,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("AIGC Worker 心跳写入失败")
                next_heartbeat = now_monotonic + max(1, settings.worker_heartbeat_interval)

            for task in list(running):
                if task.done():
                    running.discard(task)
                    try:
                        task.result()
                    except Exception:  # noqa: BLE001
                        logger.exception("AIGC Worker 子任务异常")

            if len(running) < concurrency:
                job_id = await claim_next_job(worker_id)
                if job_id is not None:
                    running.add(asyncio.create_task(_execute(job_id, worker_id)))
                    continue

            await asyncio.sleep(poll_interval)
    finally:
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        try:
            await update_heartbeat(
                worker_id,
                hostname=hostname,
                pid=pid,
                status="stopped",
                current_tasks=0,
                started_at=started_at,
            )
        except Exception:  # noqa: BLE001
            logger.exception("AIGC Worker 心跳停止写入失败")
        logger.info("AIGC Worker 停止: %s", worker_id)
