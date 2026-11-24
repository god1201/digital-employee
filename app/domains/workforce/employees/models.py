from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class DigitalEmployee(IdMixin, TenantMixin, TimestampMixin, Base):
    """数字员工：平台中的“任职主体”。"""

    __tablename__ = "digital_employees"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_employees_tenant_code"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id"), index=True, comment="绑定的可复用 Agent"
    )
    avatar: Mapped[str | None] = mapped_column(String(512))
    position: Mapped[str | None] = mapped_column(String(128), comment="岗位名称")
    description: Mapped[str | None] = mapped_column(String(1024), comment="岗位职责")
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, comment="draft/active/disabled"
    )
    model_provider: Mapped[str] = mapped_column(String(64), default="openai", nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    config: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False, comment="并发、预算、超时等运行参数"
    )
    created_by: Mapped[int | None] = mapped_column(Integer)
