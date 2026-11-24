from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class MCPServer(IdMixin, TenantMixin, TimestampMixin, Base):
    """MCP Server 注册信息。stdio 命令受白名单约束。"""

    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_mcp_servers_tenant_code"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    transport: Mapped[str] = mapped_column(
        String(32), default="stdio", nullable=False, comment="stdio/sse/streamable_http"
    )
    command: Mapped[str | None] = mapped_column(String(512))
    args: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    env: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cwd: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(String(1024))
    headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
