"""chat attachments

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column(
            "mime_type",
            sa.String(length=128),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("text_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_attachments_tenant_id", "chat_attachments", ["tenant_id"]
    )
    op.create_index(
        "ix_chat_attachments_conversation_id",
        "chat_attachments",
        ["conversation_id"],
    )
    op.create_index(
        "ix_chat_attachments_message_id", "chat_attachments", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_attachments_message_id", table_name="chat_attachments"
    )
    op.drop_index(
        "ix_chat_attachments_conversation_id", table_name="chat_attachments"
    )
    op.drop_index("ix_chat_attachments_tenant_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")
