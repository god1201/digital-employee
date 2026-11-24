from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin

APPROVAL_CATEGORIES = ("finance", "contract", "document", "custom")
APPROVAL_CATEGORY_LABELS = {
    "finance": "财务",
    "contract": "合同",
    "document": "文书",
    "custom": "自定义",
}


class ApprovalForm(IdMixin, TenantMixin, TimestampMixin, Base):
    """通用审批表单模板：字段定义存 JSON，发起时按 schema 校验。"""

    __tablename__ = "approval_forms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_approval_forms_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(32), default="custom", nullable=False, comment="finance/contract/document/custom"
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)

    @property
    def field_count(self) -> int:
        return len(self.fields or [])


class ApprovalFlow(IdMixin, TenantMixin, TimestampMixin, Base):
    """审批流程定义：节点按顺序执行，condition 节点按字段条件跳转。"""

    __tablename__ = "approval_flows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_approval_flows_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(32), default="custom", nullable=False, comment="finance/contract/document/custom"
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    form_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("approval_forms.id"), index=True
    )
    nodes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)

    @property
    def node_count(self) -> int:
        return len(self.nodes or [])


class ApprovalInstance(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次审批：流程与表单在发起时快照，后续修改模板不影响在途审批。"""

    __tablename__ = "approval_instances"

    flow_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("approval_flows.id"), index=True
    )
    form_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("approval_forms.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="custom", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="running",
        nullable=False,
        comment="running/approved/rejected/cancelled",
    )
    current_node_key: Mapped[str | None] = mapped_column(String(64))
    current_node_name: Mapped[str | None] = mapped_column(String(128))
    form_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    form_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    flow_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    node_states: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    initiator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    task_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    business_ref: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ApprovalTask(IdMixin, TenantMixin, TimestampMixin, Base):
    """节点上的审批人任务；any/all/sequence 三种会签模式。"""

    __tablename__ = "approval_tasks"

    instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("approval_instances.id"), index=True, nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    approver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="any", nullable=False, comment="any/all/sequence"
    )
    sequence_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        comment="waiting/pending/approved/rejected/cancelled",
    )
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acted_by: Mapped[int | None] = mapped_column(Integer)
    action_source: Mapped[str] = mapped_column(
        String(16), default="user", nullable=False, comment="user/system/timeout"
    )
    delegated_from: Mapped[int | None] = mapped_column(Integer)
    added_by: Mapped[int | None] = mapped_column(Integer)
    is_added: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalAction(IdMixin, TenantMixin, TimestampMixin, Base):
    """审批时间线：提交、通过、驳回、转办、加签、催办、超时、完成等。"""

    __tablename__ = "approval_actions"

    instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("approval_instances.id"), index=True, nullable=False
    )
    node_key: Mapped[str | None] = mapped_column(String(64))
    task_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    target_user_id: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ApprovalNotification(IdMixin, TenantMixin, TimestampMixin, Base):
    """站内通知：待审批、审批结果、转办、加签、催办与超时提醒。"""

    __tablename__ = "approval_notifications"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("approval_instances.id"), index=True
    )
    task_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    level: Mapped[str] = mapped_column(
        String(16), default="info", nullable=False, comment="info/warning/success"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="unread", nullable=False, comment="unread/read"
    )
    channel: Mapped[str] = mapped_column(String(16), default="inapp", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
