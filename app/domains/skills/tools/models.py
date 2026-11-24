from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class Tool(IdMixin, TenantMixin, TimestampMixin, Base):
    """数字员工可调用的工具：HTTP 接口、Python 沙箱或 MCP 工具。"""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_tools_tenant_code"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_type: Mapped[str] = mapped_column(
        String(32), default="http", nullable=False, comment="http/python/mcp"
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parameters_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), default="custom", nullable=False, comment="custom/third_party/mcp"
    )
    api_registry_id: Mapped[int | None] = mapped_column(Integer)
    mcp_server: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(Integer)
