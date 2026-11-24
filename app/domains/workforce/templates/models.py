from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TimestampMixin


class JobTemplate(IdMixin, TimestampMixin, Base):
    """岗位模板；tenant_id 为空表示平台内置。"""

    __tablename__ = "job_templates"

    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="通用", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    skill_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tool_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    knowledge_base_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    persona: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    contract: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    eval_suite_code: Mapped[str | None] = mapped_column(String(64))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
