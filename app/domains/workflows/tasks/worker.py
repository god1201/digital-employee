"""数据库持久化任务队列与 Worker。

设计：
- task_instances 同时作为队列表，status=pending 的任务可被 Worker 领取。
- 通过条件 UPDATE 原子领取，多个 Worker 不会重复执行同一任务。
- 失败后按指数退避重试，只重试基础设施类错误（超时、连接、5xx 等）。
- 进程重启时，超时未释放的 running 任务会被回收为 pending。
"""

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select, update

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.domains.operations.alerting import evaluate_all_rules
from app.domains.operations.service import update_heartbeat
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workflows.tasks.runner import run_task_instance

logger = logging.getLogger(__name__)

RETRYABLE_MARKERS = (
    "超时",
    "timeout",
    "timed out",
    "连接",
    "connect",
    "connection",
    "http 5",
    "429",
    "暂时",
    "temporarily",
    "database is locked",
    "database table is locked",
    "mcp 连接失败",
    "网络",
)

NON_RETRYABLE_MARKERS = (
    "访问被拒绝",
    "工具不存在",
    "agent 不存在",
    "未配置 llm_api_key",
    "不支持的",
    "已取消",
    "缺少",
    "无效",
    "参数校验",
    "未配置可执行步骤",
    "mcp server 已停用",
    "不存在或已停用",
)


def is_retryable(error: str | None) -> bool:
    """只对基础设施类错误重试，业务错误不重试。"""
    if not error:
        return False
    text = error.lower()
    if any(marker.lower() in text for marker in NON_RETRYABLE_MARKERS):
        return False
    return any(marker.lower() in text for marker in RETRYABLE_MARKERS)


async def claim_next_instance(worker_id: str) -> int | None:
    """原子领取一个待执行任务。"""
    now = utcnow()
    async with SessionLocal() as session:
        candidate = await session.scalar(
            select(TaskInstance.id)
            .where(
                TaskInstance.status == "pending",
                or_(
                    TaskInstance.next_run_at.is_(None),
                    TaskInstance.next_run_at <= now,
                ),
                TaskInstance.attempt < TaskInstance.max_attempts,
            )
            .order_by(TaskInstance.priority.desc(), TaskInstance.id.asc())
            .limit(1)
        )
        if candidate is None:
            return None

        result = await session.execute(
            update(TaskInstance)
            .where(
                TaskInstance.id == candidate,
                TaskInstance.status == "pending",
            )
            .values(
                status="running",
                locked_by=worker_id,
                locked_at=now,
                attempt=TaskInstance.attempt + 1,
                next_run_at=None,
                started_at=func.coalesce(TaskInstance.started_at, now),
                error=None,
                finished_at=None,
            )
        )
        await session.commit()
        if (result.rowcount or 0) != 1:
            return None
        return candidate


async def _finalize(instance_id: int, worker_id: str) -> None:
    """释放锁；可重试的失败重新入队。"""
    async with SessionLocal() as session:
        instance = await session.get(TaskInstance, instance_id)
        if instance is None or instance.locked_by != worker_id:
            return

        instance.locked_by = None
        instance.locked_at = None

        if instance.status == "failed" and instance.attempt < instance.max_attempts:
            error = instance.error or ""
            if is_retryable(error):
                delay = min(
                    settings.task_retry_base_seconds * (2 ** max(0, instance.attempt - 1)),
                    settings.task_retry_max_seconds,
                )
                instance.status = "pending"
                instance.next_run_at = utcnow() + timedelta(seconds=delay)
                instance.next_step_index = max(0, instance.current_step_index)
                instance.finished_at = None
                logger.warning(
                    "任务 %s 失败，%ss 后重试（%s/%s）: %s",
                    instance_id,
                    delay,
                    instance.attempt,
                    instance.max_attempts,
                    error[:200],
                )

        await session.commit()


async def _execute_instance(instance_id: int, worker_id: str) -> None:
    try:
        async with SessionLocal() as session:
            instance = await session.get(TaskInstance, instance_id)
            start_index = instance.next_step_index if instance else 0
        await run_task_instance(instance_id, start_index=start_index)
    except Exception:  # noqa: BLE001
        logger.exception("任务执行异常: %s", instance_id)
    finally:
        await _finalize(instance_id, worker_id)


async def recover_stale_tasks() -> int:
    """回收进程异常退出后遗留的 running 任务。"""
    cutoff = utcnow() - timedelta(seconds=settings.worker_stale_seconds)
    async with SessionLocal() as session:
        result = await session.execute(
            update(TaskInstance)
            .where(
                TaskInstance.status == "running",
                TaskInstance.locked_at.is_not(None),
                TaskInstance.locked_at < cutoff,
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
        logger.warning("已回收 %s 个僵死任务", count)
    return count


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    hostname = socket.gethostname()
    pid = os.getpid()
    worker_id = f"{hostname}-{pid}-{uuid.uuid4().hex[:6]}"
    started_at = utcnow()
    poll_interval = max(0.1, float(settings.worker_poll_interval))
    concurrency = max(1, int(settings.worker_concurrency))
    running: set[asyncio.Task] = set()

    next_heartbeat = 0.0
    next_alert = time.monotonic() + max(1, settings.alert_check_interval)

    logger.info("任务 Worker 启动: %s（并发 %s）", worker_id, concurrency)
    try:
        while stop_event is None or not stop_event.is_set():
            now_monotonic = time.monotonic()

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
                    logger.exception("Worker 心跳写入失败")
                next_heartbeat = now_monotonic + max(1, settings.worker_heartbeat_interval)

            if now_monotonic >= next_alert:
                try:
                    await evaluate_all_rules()
                except Exception:  # noqa: BLE001
                    logger.exception("告警规则评估失败")
                next_alert = now_monotonic + max(1, settings.alert_check_interval)

            for task in list(running):
                if task.done():
                    running.discard(task)
                    try:
                        task.result()
                    except Exception:  # noqa: BLE001
                        logger.exception("Worker 子任务异常")

            if len(running) < concurrency:
                instance_id = await claim_next_instance(worker_id)
                if instance_id is not None:
                    running.add(asyncio.create_task(_execute_instance(instance_id, worker_id)))
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
            logger.exception("Worker 心跳停止写入失败")
        logger.info("任务 Worker 停止: %s", worker_id)
