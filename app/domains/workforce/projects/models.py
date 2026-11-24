from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class Project(IdMixin, TenantMixin, TimestampMixin, Base):
    """项目：把任务、会话与员工组织到同一业务目标下。"""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_projects_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )
    owner_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    token_budget: Mapped[float | None] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class ProjectMember(IdMixin, TenantMixin, TimestampMixin, Base):
    """项目成员。"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "employee_id", name="uq_project_members"),
    )

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(16), default="member", nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer)
