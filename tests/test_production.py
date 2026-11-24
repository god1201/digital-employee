import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.metrics import MetricsRegistry, normalize_path
from app.core.observability import SECURITY_HEADERS
from app.core.rate_limit import SlidingWindowLimiter
from app.core.startup import validate_settings
from app.domains.identity.schemas import UserCreate
from app.domains.knowledge.vector_store import vector_literal
from app.domains.workflows.tasks.budget import budget_exceeded, budget_limits


def test_normalize_path() -> None:
    assert normalize_path("/api/v1/tasks/123") == "/api/v1/tasks/{id}"
    assert normalize_path("/api/v1/tasks/123/steps/9") == "/api/v1/tasks/{id}/steps/{id}"
    assert normalize_path("/health") == "/health"


def test_metrics_render() -> None:
    registry = MetricsRegistry()
    registry.observe_http("GET", "/api/v1/tasks/12", 200, 0.1)
    registry.observe_http("GET", "/api/v1/tasks/13", 200, 0.3)
    text = registry.render()
    assert (
        'http_requests_total{method="GET",path="/api/v1/tasks/{id}",status="200"} 2'
        in text
    )
    assert "http_request_duration_seconds_sum" in text
    assert (
        'http_request_duration_seconds_count{method="GET",'
        'path="/api/v1/tasks/{id}",status="200"} 2'
    ) in text
    assert "app_uptime_seconds" in text


def test_vector_literal() -> None:
    assert vector_literal([1, 0.5]) == "[1.000000,0.500000]"


def test_budget_limits_and_exceeded() -> None:
    limits = budget_limits(
        {"max_tokens_per_task": "1000", "max_cost_per_task": 0.5}
    )
    assert limits == (1000.0, 0.5)
    assert budget_exceeded(900, 0.2, limits) is None
    assert "Token" in budget_exceeded(1200, 0.2, limits)
    assert "成本" in budget_exceeded(900, 0.8, limits)
    assert budget_exceeded(10_000, 10, (0, 0)) is None


def test_production_config_warnings() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        secret_key="short",
        debug=True,
        auto_create_tables=True,
        cors_origins="http://localhost:5173",
        frontend_url="http://console.example.com",
    )
    warnings = validate_settings(settings)
    assert any("SECRET_KEY" in item for item in warnings)
    assert any("DEBUG" in item for item in warnings)
    assert any("AUTO_CREATE_TABLES" in item for item in warnings)
    assert any("CORS" in item for item in warnings)
    assert any("FRONTEND_URL" in item for item in warnings)

    clean = Settings(
        _env_file=None,
        app_env="production",
        secret_key="x" * 40,
        debug=False,
        auto_create_tables=False,
        cors_origins="https://console.example.com",
        frontend_url="https://console.example.com",
    )
    assert validate_settings(clean) == []

    dev = Settings(_env_file=None, app_env="development")
    assert validate_settings(dev) == []


def test_rate_limiter_window() -> None:
    limiter = SlidingWindowLimiter(2, 60)
    assert limiter.allow("ip:login", now=0)[0]
    assert limiter.allow("ip:login", now=1)[0]
    allowed, retry = limiter.allow("ip:login", now=2)
    assert allowed is False
    assert retry > 0
    assert limiter.allow("other:login", now=2)[0]
    assert limiter.allow("ip:login", now=61)[0]


def test_security_headers_defined() -> None:
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"


def test_password_min_length() -> None:
    with pytest.raises(ValidationError):
        UserCreate(username="viewer", password="short")
    user = UserCreate(username="viewer", password="longenough")
    assert user.password == "longenough"


def test_enqueue_task_db_backend(monkeypatch) -> None:
    from app.worker import enqueue

    monkeypatch.setattr(enqueue.settings, "queue_backend", "db")
    assert enqueue.enqueue_task(1) is False


def test_celery_settings() -> None:
    settings = Settings(
        _env_file=None,
        queue_backend="celery",
        redis_url="redis://example:6379/2",
    )
    assert settings.use_celery is True
    assert settings.effective_broker_url == "redis://example:6379/2"
    assert settings.effective_result_backend == "redis://example:6379/2"

    db_settings = Settings(_env_file=None, queue_backend="db")
    assert db_settings.use_celery is False
