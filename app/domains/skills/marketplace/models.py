from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class SkillPackage(IdMixin, TimestampMixin, Base):
    """可插拔技能包；tenant_id 为空表示平台内置。

    同一 code 的每个版本是一行，便于“保持旧版 / 一键升级 / 回滚”。
    """

    __tablename__ = "skill_packages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", "version", name="uq_skill_packages_tenant_code_version"
        ),
    )

    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32),
        default="language",
        nullable=False,
        comment="language/data/process/audit/learning",
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="draft",
        nullable=False,
        comment="draft/published/deprecated",
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    algorithm: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    tool_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    knowledge_base_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    eval_case_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    dependencies: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment='[{"code": "...", "min_version": 1}]'
    )
    conflicts_with: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    permissions: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="read_only/amount_threshold/risk_level/data_scopes",
    )
    common_combos: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class EmployeeSkill(IdMixin, TenantMixin, TimestampMixin, Base):
    """员工已装配技能；每个 code 只保留一个当前版本。"""

    __tablename__ = "employee_skills"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employee_id", "skill_code", name="uq_employee_skills_code"
        ),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_packages.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False, comment="active/disabled"
    )
    source: Mapped[str] = mapped_column(
        String(32),
        default="marketplace",
        nullable=False,
        comment="marketplace/copy/ai_suggest/role_preset",
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    installed_by: Mapped[int | None] = mapped_column(Integer)
