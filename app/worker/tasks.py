"""Celery 任务：复用 LangGraph 任务引擎。"""

import asyncio
import logging

import app.domains.models  # noqa: F401  注册全部模型，Celery 进程同样需要
from app.core.database import engine
from app.domains.workflows.tasks.engine import run_task_graph
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="digital_employee.run_task")
def run_task_task(instance_id: int, start_index: int = 0) -> None:
    async def _run() -> None:
        try:
            await run_task_graph(instance_id, start_index)
        finally:
            # 每个 Celery 任务使用独立事件循环，必须释放连接池
            await engine.dispose()

    asyncio.run(_run())
