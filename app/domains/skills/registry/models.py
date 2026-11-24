from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class ApiRegistry(IdMixin, TenantMixin, TimestampMixin, Base):
    """企业接口目录，是工具层的上游数据源。"""

    __tablename__ = "api_registries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "system_code", "method", "path", name="uq_api_registry_entry"
        ),
    )

    system_name: Mapped[str] = mapped_column(String(128), nullable=False)
    system_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[str | None] = mapped_column(String(32))
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    request_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
