from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class RolePreset(IdMixin, TimestampMixin, Base):
    """角色预设库；tenant_id 为空表示平台内置。"""

    __tablename__ = "role_presets"

    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    default_skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tool_groups: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approval_threshold: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    sandbox: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class TeamTemplate(IdMixin, TimestampMixin, Base):
    """团队模板；tenant_id 为空表示平台内置。"""

    __tablename__ = "team_templates"

    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="通用", nullable=False)
    roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    topology: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class Team(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_teams_tenant_code"),)

    template_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_confirmation",
        nullable=False,
        comment="pending_confirmation/active/paused/disabled",
    )
    topology: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class TeamMember(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "team_members"

    team_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    employee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approval_threshold: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    sandbox: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    reports_to: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
