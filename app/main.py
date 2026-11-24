import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db, engine, init_db
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.core.metrics import metrics
from app.core.observability import ObservabilityMiddleware
from app.core.startup import validate_settings
from app.domains.learning.scheduler import run_learning_scheduler
from app.domains.skills.marketplace.seed import seed_skill_packages
from app.domains.workflows.aigc.seed import seed_aigc_defaults
from app.domains.workflows.aigc.storage import ensure_storage_root
from app.domains.workflows.aigc.worker import recover_stale_jobs as recover_stale_aigc_jobs
from app.domains.workflows.aigc.worker import run_aigc_worker
from app.domains.workflows.approvals.seed import seed_approval_templates
from app.domains.workflows.approvals.worker import run_approval_worker
from app.domains.workflows.tasks.triggers import run_trigger_scheduler
from app.domains.workflows.tasks.worker import recover_stale_tasks, run_worker
from app.domains.workforce.teams.seed import seed_team_templates
from app.domains.workforce.templates.seed import seed_job_templates

logger = logging.getLogger(__name__)

MEDIA_DIR = ensure_storage_root()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    config_warnings = validate_settings(settings)
    for warning in config_warnings:
        logger.warning("配置检查: %s", warning)
    if settings.strict_config_check and config_warnings:
        raise RuntimeError("生产配置检查未通过: " + "; ".join(config_warnings))
    if settings.auto_create_tables:
        await init_db()
    try:
        await seed_team_templates()
    except Exception:  # noqa: BLE001
        logger.exception("团队模板种子初始化失败")
    try:
        await seed_skill_packages()
    except Exception:  # noqa: BLE001
        logger.exception("技能市场种子初始化失败")
    try:
        await seed_job_templates()
    except Exception:  # noqa: BLE001
        logger.exception("岗位模板种子初始化失败")
    try:
        await seed_aigc_defaults()
    except Exception:  # noqa: BLE001
        logger.exception("AIGC 默认数据初始化失败")
    try:
        await seed_approval_templates()
    except Exception:  # noqa: BLE001
        logger.exception("审批流模板初始化失败")
    await recover_stale_tasks()
    await recover_stale_aigc_jobs()

    workers: list[tuple[asyncio.Event, asyncio.Task]] = []
    if settings.inline_worker and not settings.use_celery:
        stop_event = asyncio.Event()
        workers.append((stop_event, asyncio.create_task(run_worker(stop_event))))
    if settings.trigger_worker_enabled and (
        settings.use_celery or settings.inline_worker
    ):
        trigger_stop_event = asyncio.Event()
        workers.append(
            (
                trigger_stop_event,
                asyncio.create_task(run_trigger_scheduler(trigger_stop_event)),
            )
        )
    if settings.learning_scheduler_enabled:
        learning_stop_event = asyncio.Event()
        workers.append(
            (
                learning_stop_event,
                asyncio.create_task(run_learning_scheduler(learning_stop_event)),
            )
        )
    if settings.aigc_worker_enabled:
        aigc_stop_event = asyncio.Event()
        workers.append(
            (aigc_stop_event, asyncio.create_task(run_aigc_worker(aigc_stop_event)))
        )
    if settings.approval_worker_enabled:
        approval_stop_event = asyncio.Event()
        workers.append(
            (
                approval_stop_event,
                asyncio.create_task(run_approval_worker(approval_stop_event)),
            )
        )

    display_host = "localhost" if settings.app_host in {"0.0.0.0", "::"} else settings.app_host
    logger.info("前端控制台: %s", settings.frontend_url)
    logger.info("API 文档: http://%s:%s/docs", display_host, settings.app_port)
    logger.info("健康检查: http://%s:%s/health", display_host, settings.app_port)
    logger.info(
        "%s 启动完成（env=%s, queue=%s）",
        settings.app_name,
        settings.app_env,
        settings.queue_backend,
    )
    try:
        yield
    finally:
        for stop_event, _ in workers:
            stop_event.set()
        for _, worker_task in workers:
            try:
                await asyncio.wait_for(worker_task, timeout=15)
            except TimeoutError:
                worker_task.cancel()
                await asyncio.gather(worker_task, return_exceptions=True)
            except Exception:  # noqa: BLE001
                logger.exception("后台 Worker 退出异常")
        await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="数字员工平台：授权、接口登记、工具、任务执行、监控与反馈闭环",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)

app.mount(
    settings.aigc_public_prefix.rstrip("/") or "/media",
    StaticFiles(directory=str(MEDIA_DIR)),
    name="media",
)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": 42200,
            "message": "参数校验失败",
            "data": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = str(exc.detail)
    if exc.status_code == 404:
        message = (
            f"接口不存在: {request.url.path}。"
            f"请确认路径前缀为 {settings.api_prefix}，接口文档见 /docs"
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code * 100, "message": message, "data": None},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 50000, "message": "服务器内部错误", "data": None},
    )


@app.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url=settings.frontend_url or "/docs")


@app.get("/info", tags=["系统"], summary="服务信息")
async def info() -> dict:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "env": settings.app_env,
        "message": "服务已启动，接口文档见 /docs，前端控制台见 FRONTEND_URL",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "frontend": settings.frontend_url,
        "api": settings.api_prefix,
    }


@app.get("/health", tags=["系统"], summary="健康检查")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "version": "0.1.0",
    }


async def _check_redis() -> str:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(settings.effective_broker_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379

    def ping() -> None:
        with socket.create_connection((host, port), timeout=1.0):
            return

    try:
        await asyncio.to_thread(ping)
        return "ok"
    except OSError as exc:
        return f"error: {type(exc).__name__}"


@app.get("/health/ready", tags=["系统"], summary="就绪检查（数据库/队列）")
async def readiness():
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    if settings.use_celery:
        checks["queue"] = await _check_redis()
    healthy = checks["database"] == "ok" and checks.get("queue", "ok") == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


async def _db_metrics_lines() -> str:
    try:
        from sqlalchemy import func, select

        from app.domains.operations.models import WorkerHeartbeat
        from app.domains.workflows.tasks.models import TaskInstance

        async with SessionLocal() as session:
            rows = await session.execute(
                select(TaskInstance.status, func.count(TaskInstance.id)).group_by(
                    TaskInstance.status
                )
            )
            counts = {row[0]: row[1] for row in rows}
            workers = await session.scalar(select(func.count(WorkerHeartbeat.id)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("指标查询失败: %s", exc)
        return ""

    lines = [
        "# HELP de_tasks_total 任务实例数量（按状态）",
        "# TYPE de_tasks_total gauge",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f'de_tasks_total{{status="{status}"}} {count}')
    lines += [
        "# HELP de_worker_heartbeats Worker 心跳记录数",
        "# TYPE de_worker_heartbeats gauge",
        f"de_worker_heartbeats {int(workers or 0)}",
    ]
    return "\n".join(lines) + "\n"


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> PlainTextResponse:
    body = metrics.render() + await _db_metrics_lines()
    return PlainTextResponse(
        body, media_type="text/plain; version=0.0.4; charset=utf-8"
    )


app.include_router(api_router, prefix=settings.api_prefix)


def run() -> None:
    """本地启动入口：python -m app.main"""
    import uvicorn

    uvicorn.run(
        # reload 需要导入字符串，否则 Uvicorn 无法在子进程中重新导入应用
        "app.main:app" if settings.app_reload else app,
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
