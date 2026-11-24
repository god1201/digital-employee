import re
from datetime import UTC, datetime

from fastapi import Request


def as_utc(value: datetime | None) -> datetime | None:
    """数据库读出的时间戳可能没有时区，统一补成 UTC。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def slugify(value: str, max_length: int = 64) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return (value or "item")[:max_length]
