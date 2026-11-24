"""Celery Worker 启动入口。

先安装可选依赖并启动 Redis：

    pip install ".[workers]"
    # .env: QUEUE_BACKEND=celery、REDIS_URL=redis://127.0.0.1:6379/0

再运行：

    .venv\\Scripts\\python.exe scripts\\celery_worker.py

注意：QUEUE_BACKEND=celery 时 API 不会再启动内联 DB Worker，避免重复执行。
"""

from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings
from app.worker.celery_app import celery_app


def _masked_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.password is None:
        return url
    auth = f"{parsed.username or ''}:***"
    host = parsed.hostname or ""
    netloc = f"{auth}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def main() -> None:
    print(
        f"Celery worker queue={settings.celery_task_queue} "
        f"broker={_masked_url(settings.effective_broker_url)}"
    )
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            f"--queues={settings.celery_task_queue}",
            "--pool=solo",
            "--concurrency=1",
        ]
    )


if __name__ == "__main__":
    main()
