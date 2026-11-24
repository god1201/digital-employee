from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，全部可通过环境变量或 .env 覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用
    app_name: str = "Digital Employee Platform"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    strict_config_check: bool = False

    # 本地启动（python -m app.main）
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    # 前后端分离后的前端地址；根路径 / 会重定向到这里
    frontend_url: str = "http://localhost:5173"

    # 安全
    secret_key: str = "dev-secret-change-me-please-use-32-bytes"
    access_token_expire_minutes: int = 60 * 24

    # 数据库
    database_url: str = (
        "postgresql+asyncpg://de:de@192.168.100.168:5432/digital_employee_platform"
    )
    auto_create_tables: bool = True
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # CORS（前后端分离后按前端实际地址配置）
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    # 大模型
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = ""
    # 兼容直接配置 DEEPSEEK_API_KEY 环境变量的场景
    deepseek_api_key: str = ""
    # LLM 归因：默认关闭，开启后日结批次会复核低置信度规则归因
    llm_attribution_enabled: bool = False
    llm_attribution_min_confidence: float = 0.75
    llm_attribution_max_per_run: int = 5
    # LLM 技能组合推荐超时
    llm_recommend_timeout: float = 60.0

    # MCP stdio 命令白名单，空字符串表示不限制
    mcp_allowed_commands: str = "python,python3,node,npx,uvx,uv"

    # 任务队列 / Worker
    queue_backend: str = "db"  # db|celery；celery 需安装 workers extra 并启动 Redis
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_queue: str = "tasks"
    inline_worker: bool = True
    worker_poll_interval: float = 0.5
    worker_concurrency: int = 2
    worker_stale_seconds: int = 600
    task_max_attempts: int = 3
    task_retry_base_seconds: int = 10
    task_retry_max_seconds: int = 300

    # 失败反思与自我修正
    reflection_enabled: bool = True
    reflection_auto_retry: bool = True
    reflection_llm_enabled: bool = False
    reflection_max_retries: int = 1

    # 任务触发器
    trigger_worker_enabled: bool = True
    trigger_poll_interval: int = 30

    # 学习节奏自动化：日结批量归因 + 自动提问 + 周报生成与投递
    learning_scheduler_enabled: bool = True
    learning_scheduler_poll_interval: int = 60
    # 以下时间均按 UTC 解释
    learning_daily_at: str = "02:00"
    learning_daily_lookback_hours: int = 24
    learning_weekly_weekday: int = 0  # 0=周一
    learning_weekly_at: str = "09:00"
    learning_auto_question_enabled: bool = True
    learning_auto_question_confidence: float = 0.6
    learning_auto_question_recurrence: int = 2
    learning_auto_question_max_per_run: int = 2
    weekly_review_delivery_url: str = ""
    weekly_review_delivery_timeout: float = 10.0

    # 监控 / 告警
    worker_heartbeat_interval: int = 10
    worker_heartbeat_timeout: int = 30
    alert_check_interval: int = 60
    llm_cost_per_1k_tokens: float = 0.0

    # AIGC 内容生成
    aigc_storage_dir: str = "./data/aigc"
    aigc_public_prefix: str = "/media"
    aigc_worker_enabled: bool = True
    aigc_worker_poll_interval: float = 1.0
    aigc_worker_concurrency: int = 2
    aigc_job_max_attempts: int = 2
    aigc_stale_seconds: int = 1800
    aigc_request_timeout_seconds: int = 180
    aigc_download_max_bytes: int = 200 * 1024 * 1024
    aigc_upload_max_bytes: int = 20 * 1024 * 1024

    # 对话附件
    chat_attachment_dir: str = "./data/chat_attachments"
    chat_attachment_max_bytes: int = 10 * 1024 * 1024
    chat_attachment_text_limit: int = 8000

    # 审批流
    approval_worker_enabled: bool = True
    approval_timeout_check_interval: int = 60

    # 知识检索 / Embedding
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_dim: int = 256
    local_embedding_enabled: bool = True
    # auto=检测到 pgvector 就用；json=强制 JSON 内积；pgvector=强制要求扩展
    vector_backend: str = "auto"

    # 多模态解析（OCR/ASR/PDF）；为空时仅本地文本/CSV/JSON
    multimodal_provider_url: str = ""
    multimodal_provider_api_key: str = ""
    multimodal_timeout: float = 120.0
    multimodal_max_bytes: int = 20 * 1024 * 1024

    # 外部训练服务（DPO/SFT）；为空时只维护训练台账
    training_provider_url: str = ""
    training_provider_api_key: str = ""
    training_provider_timeout: float = 60.0
    training_dataset_max_bytes: int = 50 * 1024 * 1024

    # 可观测性
    metrics_enabled: bool = True

    # 登录限流（进程内滑动窗口；多实例部署时每个进程独立计数）
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_per_minute: int = 10

    @property
    def use_celery(self) -> bool:
        return self.queue_backend.lower() == "celery"

    @property
    def effective_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def mcp_allowed_command_list(self) -> list[str]:
        return [
            item.strip().lower() for item in self.mcp_allowed_commands.split(",") if item.strip()
        ]

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
