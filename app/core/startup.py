"""生产启动配置校验：把危险的默认配置显式暴露出来。"""

from urllib.parse import urlparse

from app.core.config import Settings

DEFAULT_SECRET = "dev-secret-change-me-please-use-32-bytes"
PROD_ENVS = {"production", "prod"}


def validate_settings(config: Settings) -> list[str]:
    warnings: list[str] = []
    if config.app_env.lower() not in PROD_ENVS:
        return warnings

    if config.secret_key == DEFAULT_SECRET or len(config.secret_key) < 32:
        warnings.append("SECRET_KEY 仍为默认值或长度不足 32 字节")
    if config.debug:
        warnings.append("生产环境应关闭 DEBUG")
    if config.auto_create_tables:
        warnings.append("生产环境应设置 AUTO_CREATE_TABLES=false 并使用 Alembic")
    if any(
        "localhost" in origin or "127.0.0.1" in origin
        for origin in config.cors_origin_list
    ):
        warnings.append("生产 CORS_ORIGINS 仍包含 localhost/127.0.0.1")
    if config.queue_backend.lower() == "celery" and not config.redis_url:
        warnings.append("QUEUE_BACKEND=celery 但未配置 REDIS_URL")
    if config.training_provider_url:
        parsed = urlparse(config.training_provider_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            warnings.append("TRAINING_PROVIDER_URL 必须是 http(s) 地址")
    if config.weekly_review_delivery_url:
        parsed = urlparse(config.weekly_review_delivery_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            warnings.append("WEEKLY_REVIEW_DELIVERY_URL 必须是 http(s) 地址")
    if not 0 <= config.learning_weekly_weekday <= 6:
        warnings.append("LEARNING_WEEKLY_WEEKDAY 必须在 0-6 之间（0=周一）")
    if config.llm_attribution_enabled and not (
        config.llm_api_key or config.deepseek_api_key
    ):
        warnings.append("LLM_ATTRIBUTION_ENABLED=true 但未配置 LLM_API_KEY")
    if config.reflection_llm_enabled and not (
        config.llm_api_key or config.deepseek_api_key
    ):
        warnings.append("REFLECTION_LLM_ENABLED=true 但未配置 LLM_API_KEY")
    if config.frontend_url and not config.frontend_url.startswith("https://"):
        warnings.append("生产 FRONTEND_URL 建议使用 https")
    return warnings
