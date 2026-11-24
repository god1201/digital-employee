from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class Conversation(IdMixin, TenantMixin, TimestampMixin, Base):
    """员工对话 / 群聊会话。"""

    __tablename__ = "conversations"

    mode: Mapped[str] = mapped_column(
        String(16), default="direct", nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class ConversationMember(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "employee_id", name="uq_conversation_members"
        ),
    )

    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(16), default="member", nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class ChatAttachment(IdMixin, TenantMixin, TimestampMixin, Base):
    """对话附件：私有存储，发送消息时引用并提取文本上下文。"""

    __tablename__ = "chat_attachments"

    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chat_messages.id"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(128), default="application/octet-stream", nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    text_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(Integer)


class ChatMessage(IdMixin, TenantMixin, TimestampMixin, Base):
    """对话消息，包含员工回复、工具调用与 Token 计量。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_chat_messages_employee_created", "employee_id", "created_at"),
    )

    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="sent", nullable=False
    )
    message_metadata: Mapped[dict] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer)
