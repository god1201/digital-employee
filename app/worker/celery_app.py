"""Celery 应用配置；仅在 QUEUE_BACKEND=celery 时使用。"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "digital_employee",
    broker=settings.effective_broker_url,
    backend=settings.effective_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.celery_task_queue,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
