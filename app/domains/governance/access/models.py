from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class Authorization(IdMixin, TenantMixin, TimestampMixin, Base):
    """数字员工访问外部系统的授权记录。凭证只存密文。"""

    __tablename__ = "authorizations"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    system_name: Mapped[str] = mapped_column(String(128), nullable=False)
    system_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(512))
    access_type: Mapped[str] = mapped_column(
        String(32),
        default="api_key",
        nullable=False,
        comment="login/api_key/oauth2/token/cookie",
    )
    username: Mapped[str | None] = mapped_column(String(128))
    credential_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(Integer)

    @property
    def has_credential(self) -> bool:
        return bool(self.credential_encrypted)


class AccessRule(IdMixin, TenantMixin, TimestampMixin, Base):
    """路径级准入规则，默认拒绝；priority 越大优先级越高，同优先级 deny 胜出。"""

    __tablename__ = "access_rules"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    system_code: Mapped[str | None] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(16), default="*", nullable=False)
    path_pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    effect: Mapped[str] = mapped_column(String(16), default="deny", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(Integer)
