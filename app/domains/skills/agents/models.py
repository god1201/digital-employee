from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class Agent(IdMixin, TenantMixin, TimestampMixin, Base):
    """Agent 注册信息：内置 Agent 或第三方 Agent。"""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_agents_tenant_code"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(
        String(32), default="internal", nullable=False, comment="internal/third_party"
    )
    protocol: Mapped[str] = mapped_column(
        String(32), default="builtin", nullable=False, comment="builtin/openai/http"
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(1024))
    headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_provider: Mapped[str] = mapped_column(String(64), default="openai", nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tools: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="绑定的工具编码列表"
    )
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
