from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class CollaborationRun(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次多员工协作会话，底层复用一个父任务实例。"""

    __tablename__ = "collaboration_runs"

    owner_employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mode: Mapped[str] = mapped_column(
        String(16),
        default="sequential",
        nullable=False,
        comment="sequential/parallel",
    )
    participants: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    parent_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        index=True,
        nullable=False,
        comment="pending/running/succeeded/failed/cancelled",
    )
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
