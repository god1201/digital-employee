from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class WorkerHeartbeat(IdMixin, TimestampMixin, Base):
    """Worker 心跳，用于监控队列消费者是否存活。"""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(128), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    current_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )


class AlertRule(IdMixin, TenantMixin, TimestampMixin, Base):
    """告警规则：指标 + 比较符 + 阈值 + 窗口 + 冷却。"""

    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), default="gt", nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(1024))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class AlertEvent(IdMixin, TenantMixin, TimestampMixin, Base):
    """告警事件，触发后进入 open，人工确认后 acked。"""

    __tablename__ = "alert_events"

    rule_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    webhook_status: Mapped[str | None] = mapped_column(String(64))
