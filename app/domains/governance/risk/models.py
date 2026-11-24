from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class RiskRule(IdMixin, TenantMixin, TimestampMixin, Base):
    """内容/业务风控规则：关键词命中 + 处置动作。"""

    __tablename__ = "risk_rules"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), default="content", nullable=False, comment="content/business"
    )
    keywords: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    action: Mapped[str] = mapped_column(
        String(32), default="review", nullable=False, comment="block/review/allow"
    )
    severity: Mapped[str] = mapped_column(
        String(16), default="medium", nullable=False, comment="low/medium/high"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class RiskCheck(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "risk_checks"

    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="content", nullable=False)
    decision: Mapped[str] = mapped_column(String(32), default="allow", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    matched_rules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
