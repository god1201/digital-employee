from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class InspectionRule(IdMixin, TenantMixin, TimestampMixin, Base):
    """质检规则：关键词、正则或长度约束。"""

    __tablename__ = "inspection_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_inspection_rules_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), default="content", nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(32), default="keyword", nullable=False, comment="keyword/regex/min_length/max_length"
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    penalty: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class InspectionRecord(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次质检结果，支持人工复核。"""

    __tablename__ = "inspection_records"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="content", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    grade: Mapped[str] = mapped_column(String(4), default="A", nullable=False)
    decision: Mapped[str] = mapped_column(
        String(16), default="pass", nullable=False, comment="pass/review/reject"
    )
    rule_results: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False, comment="pending/reviewed"
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer)


class HallucinationCheck(IdMixin, TenantMixin, TimestampMixin, Base):
    """幻觉检测记录：答案与给定来源的支撑度。"""

    __tablename__ = "hallucination_checks"

    employee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    instance_id: Mapped[int | None] = mapped_column(Integer, index=True)
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
