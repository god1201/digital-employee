"""独立 Worker 启动入口。

API 进程设置 INLINE_WORKER=false 时，用这个脚本单独跑 Worker：
    python -m scripts.worker

同时启动任务队列 Worker 与 AIGC 生成 Worker（AIGC_WORKER_ENABLED=false 可关闭后者）。
"""

import asyncio

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logging import setup_logging
from app.domains.workflows.aigc.worker import recover_stale_jobs as recover_stale_aigc_jobs
from app.domains.workflows.aigc.worker import run_aigc_worker
from app.domains.workflows.approvals.worker import run_approval_worker
from app.domains.workflows.tasks.triggers import run_trigger_scheduler
from app.domains.workflows.tasks.worker import recover_stale_tasks, run_worker


async def main() -> None:
    setup_logging()
    await init_db()
    await recover_stale_tasks()
    await recover_stale_aigc_jobs()

    tasks = []
    if not settings.use_celery:
        tasks.append(asyncio.create_task(run_worker()))
    trigger_stop = asyncio.Event()
    if settings.trigger_worker_enabled:
        tasks.append(asyncio.create_task(run_trigger_scheduler(trigger_stop)))
    if settings.aigc_worker_enabled:
        tasks.append(asyncio.create_task(run_aigc_worker()))
    if settings.approval_worker_enabled:
        tasks.append(asyncio.create_task(run_approval_worker()))
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
