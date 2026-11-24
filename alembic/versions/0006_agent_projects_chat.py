"""agent assignment, projects, conversations and chat messages

Revision ID: a1b2c3d4e5f6
Revises: 7273f304149c
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7273f304149c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "digital_employees",
        sa.Column("agent_id", sa.Integer(), nullable=True, comment="绑定的可复用 Agent"),
    )
    op.create_foreign_key(
        "fk_digital_employees_agent_id",
        "digital_employees",
        "agents",
        ["agent_id"],
        ["id"],
    )
    op.create_index(
        "ix_digital_employees_agent_id", "digital_employees", ["agent_id"]
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column("owner_employee_id", sa.Integer(), nullable=True),
        sa.Column("token_budget", sa.Float(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["owner_employee_id"], ["digital_employees.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_projects_tenant_code"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_index("ix_projects_code", "projects", ["code"])
    op.create_index(
        "ix_projects_owner_employee_id", "projects", ["owner_employee_id"]
    )

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="member"
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["digital_employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "employee_id", name="uq_project_members"
        ),
    )
    op.create_index(
        "ix_project_members_tenant_id", "project_members", ["tenant_id"]
    )
    op.create_index(
        "ix_project_members_project_id", "project_members", ["project_id"]
    )
    op.create_index(
        "ix_project_members_employee_id", "project_members", ["employee_id"]
    )

    op.add_column("task_instances", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_task_instances_project_id",
        "task_instances",
        "projects",
        ["project_id"],
        ["id"],
    )
    op.create_index("ix_task_instances_project_id", "task_instances", ["project_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="direct"),
        sa.Column("title", sa.String(length=128), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])

    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="member"
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["digital_employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "employee_id", name="uq_conversation_members"
        ),
    )
    op.create_index(
        "ix_conversation_members_tenant_id", "conversation_members", ["tenant_id"]
    )
    op.create_index(
        "ix_conversation_members_conversation_id",
        "conversation_members",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_members_employee_id",
        "conversation_members",
        ["employee_id"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="sent"
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["digital_employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    op.create_index(
        "ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"]
    )
    op.create_index("ix_chat_messages_employee_id", "chat_messages", ["employee_id"])
    op.create_index("ix_chat_messages_trace_id", "chat_messages", ["trace_id"])
    op.create_index(
        "ix_chat_messages_conversation_created",
        "chat_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_chat_messages_employee_created",
        "chat_messages",
        ["employee_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_employee_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_trace_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_employee_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index(
        "ix_conversation_members_employee_id", table_name="conversation_members"
    )
    op.drop_index(
        "ix_conversation_members_conversation_id",
        table_name="conversation_members",
    )
    op.drop_index(
        "ix_conversation_members_tenant_id", table_name="conversation_members"
    )
    op.drop_table("conversation_members")

    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_index("ix_conversations_tenant_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_task_instances_project_id", table_name="task_instances")
    op.drop_constraint(
        "fk_task_instances_project_id", "task_instances", type_="foreignkey"
    )
    op.drop_column("task_instances", "project_id")

    op.drop_index("ix_project_members_employee_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_index("ix_project_members_tenant_id", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_projects_owner_employee_id", table_name="projects")
    op.drop_index("ix_projects_code", table_name="projects")
    op.drop_index("ix_projects_tenant_id", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_digital_employees_agent_id", table_name="digital_employees")
    op.drop_constraint(
        "fk_digital_employees_agent_id", "digital_employees", type_="foreignkey"
    )
    op.drop_column("digital_employees", "agent_id")
