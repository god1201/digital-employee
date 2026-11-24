"""任务入队抽象：Celery 可用时投递，否则保留在数据库队列。"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def enqueue_task(instance_id: int, start_index: int = 0) -> bool:
    if not settings.use_celery:
        return False
    try:
        from app.worker.tasks import run_task_task
    except ImportError:
        logger.exception(
            "Celery 未安装，回退数据库队列；请执行 pip install '.[workers]'"
        )
        return False
    try:
        run_task_task.apply_async(
            args=[instance_id, start_index], queue=settings.celery_task_queue
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Celery 入队失败，任务保留在数据库队列")
        return False
