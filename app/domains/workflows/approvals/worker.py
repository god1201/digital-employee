"""审批超时扫描 Worker。

按 ``APPROVAL_TIMEOUT_CHECK_INTERVAL`` 扫描到期的审批任务，执行提醒、自动通过、
自动驳回或升级转办；同时写入 Worker 心跳，便于监控页面看到它存活。
"""

import asyncio
import logging
import os
import socket
import time
import uuid

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.domains.operations.service import update_heartbeat
from app.domains.workflows.approvals.service import scan_timeouts

logger = logging.getLogger(__name__)


async def run_approval_worker(stop_event: asyncio.Event | None = None) -> None:
    hostname = socket.gethostname()
    pid = os.getpid()
    worker_id = f"approval-{hostname}-{pid}-{uuid.uuid4().hex[:6]}"
    started_at = utcnow()
    scan_interval = max(5, int(settings.approval_timeout_check_interval))
    heartbeat_interval = max(5, int(settings.worker_heartbeat_interval))
    next_scan = 0.0
    next_heartbeat = 0.0

    logger.info("审批超时 Worker 启动: %s（扫描间隔 %ss）", worker_id, scan_interval)
    try:
        while stop_event is None or not stop_event.is_set():
            now = time.monotonic()

            if now >= next_heartbeat:
                try:
                    await update_heartbeat(
                        worker_id,
                        hostname=hostname,
                        pid=pid,
                        status="running",
                        current_tasks=0,
                        started_at=started_at,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("审批 Worker 心跳写入失败")
                next_heartbeat = now + heartbeat_interval

            if now >= next_scan:
                try:
                    async with SessionLocal() as session:
                        processed = await scan_timeouts(session)
                        await session.commit()
                    if processed:
                        logger.info("审批超时扫描处理 %s 个任务", processed)
                except Exception:  # noqa: BLE001
                    logger.exception("审批超时扫描失败")
                next_scan = time.monotonic() + scan_interval

            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(5)
    finally:
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
            logger.exception("审批 Worker 心跳停止写入失败")
        logger.info("审批超时 Worker 停止: %s", worker_id)
