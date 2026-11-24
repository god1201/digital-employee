from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class TaskDefinition(IdMixin, TenantMixin, TimestampMixin, Base):
    """任务定义：固定流程或自由任务模板。"""

    __tablename__ = "task_definitions"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(
        String(32), default="fixed", nullable=False, comment="fixed/free"
    )
    description: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class TaskInstance(IdMixin, TenantMixin, TimestampMixin, Base):
    """任务实例：一次具体的工作执行。"""

    __tablename__ = "task_instances"
    __table_args__ = (
        Index("ix_task_instances_status_next_run", "status", "next_run_at"),
    )

    definition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_definitions.id"), index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        comment="pending/running/waiting_human/succeeded/failed/cancelled",
    )
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    plan: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="固化后的执行计划，保证恢复时一致"
    )
    current_step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_step_index: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="下次执行的起始步骤，用于恢复/重试"
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, comment="重试退避的可执行时间"
    )
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class TaskTrigger(IdMixin, TenantMixin, TimestampMixin, Base):
    """任务触发器：定时、每日或事件驱动，支撑主动汇报与周期任务。"""

    __tablename__ = "task_triggers"
    __table_args__ = (
        Index("ix_task_triggers_enabled_next_run", "enabled", "next_run_at"),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    definition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_definitions.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_type: Mapped[str] = mapped_column(
        String(16),
        default="interval",
        nullable=False,
        comment="interval/daily/event",
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    daily_at: Mapped[str | None] = mapped_column(String(5), comment="HH:MM (UTC)")
    event_name: Mapped[str | None] = mapped_column(String(64), index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class TaskStep(IdMixin, TimestampMixin, Base):
    """任务步骤级执行轨迹，用于监控与审计。"""

    __tablename__ = "task_steps"

    instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True, nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    step_type: Mapped[str] = mapped_column(
        String(32), default="tool", nullable=False, comment="llm/tool/agent/human"
    )
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tool_code: Mapped[str | None] = mapped_column(String(64))
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
