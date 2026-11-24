from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class PersonaProfile(IdMixin, TenantMixin, TimestampMixin, Base):
    """员工人格表现层；技能只输出结构化结果，由该层统一表达。"""

    __tablename__ = "persona_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", name="uq_persona_profiles_employee"),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    tone: Mapped[str] = mapped_column(
        String(32), default="professional", nullable=False, comment="professional/friendly/concise"
    )
    address_style: Mapped[str | None] = mapped_column(String(128))
    output_format: Mapped[str] = mapped_column(
        String(32),
        default="conclusion_first",
        nullable=False,
        comment="conclusion_first/bullets/table/detailed",
    )
    report_style: Mapped[str] = mapped_column(
        String(32), default="conclusion_first", nullable=False
    )
    taboo_words: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    signature: Mapped[str | None] = mapped_column(String(255))
    polish_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
