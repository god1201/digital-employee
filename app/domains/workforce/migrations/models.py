from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class CapabilityMigration(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次跨员工能力迁移的记录与报告。"""

    __tablename__ = "capability_migrations"

    source_employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    target_employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    components: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="completed",
        nullable=False,
        comment="completed/partial/failed",
    )
    report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
