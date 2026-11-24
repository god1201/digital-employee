from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

ApprovalCategory = Literal["finance", "contract", "document", "custom"]


class FormCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    category: ApprovalCategory = "custom"
    description: str = ""
    fields: list[dict] = Field(default_factory=list)
    enabled: bool = True


class FormUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    category: ApprovalCategory | None = None
    description: str | None = None
    fields: list[dict] | None = None
    enabled: bool | None = None


class FormOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    category: str
    description: str
    fields: list
    field_count: int = 0
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class FlowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    category: ApprovalCategory = "custom"
    description: str = ""
    form_id: int | None = None
    nodes: list[dict] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class FlowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    category: ApprovalCategory | None = None
    description: str | None = None
    form_id: int | None = None
    nodes: list[dict] | None = None
    config: dict | None = None
    enabled: bool | None = None


class FlowOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    category: str
    description: str
    form_id: int | None = None
    form_name: str | None = None
    nodes: list
    node_count: int = 0
    config: dict
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class InstanceCreate(BaseModel):
    flow_id: int
    title: str = Field(min_length=1, max_length=255)
    form_data: dict = Field(default_factory=dict)
    employee_id: int | None = None
    task_instance_id: int | None = None
    business_ref: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=0, le=1000)


class TaskOut(ORMModel):
    id: int
    tenant_id: int
    instance_id: int
    node_key: str
    node_name: str
    approver_id: int
    mode: str
    sequence_order: int
    status: str
    comment: str
    acted_at: datetime | None = None
    acted_by: int | None = None
    action_source: str
    delegated_from: int | None = None
    added_by: int | None = None
    is_added: bool
    due_at: datetime | None = None
    reminded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ActionOut(ORMModel):
    id: int
    tenant_id: int
    instance_id: int
    node_key: str | None = None
    task_id: int | None = None
    action: str
    actor_id: int | None = None
    target_user_id: int | None = None
    comment: str
    detail: dict
    created_at: datetime


class NotificationOut(ORMModel):
    id: int
    tenant_id: int
    user_id: int
    instance_id: int | None = None
    task_id: int | None = None
    title: str
    content: str
    level: str
    status: str
    channel: str
    read_at: datetime | None = None
    created_at: datetime


class InstanceOut(ORMModel):
    id: int
    tenant_id: int
    flow_id: int | None = None
    flow_name: str | None = None
    form_id: int | None = None
    form_name: str | None = None
    title: str
    category: str
    status: str
    current_node_key: str | None = None
    current_node_name: str | None = None
    form_data: dict
    form_snapshot: dict
    flow_snapshot: dict
    node_states: dict
    initiator_id: int
    initiator_name: str | None = None
    employee_id: int | None = None
    task_instance_id: int | None = None
    business_ref: str | None = None
    priority: int
    due_at: datetime | None = None
    completed_at: datetime | None = None
    last_reminded_at: datetime | None = None
    error: str | None = None
    result: dict
    created_at: datetime
    updated_at: datetime
    progress: dict = Field(default_factory=dict)
    tasks: list[TaskOut] = Field(default_factory=list)
    actions: list[ActionOut] = Field(default_factory=list)
    my_tasks: list[TaskOut] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    comment: str = ""


class TransferRequest(BaseModel):
    target_user_id: int
    comment: str = ""


class AddSignRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    comment: str = ""


class LaunchTaskRequest(BaseModel):
    employee_id: int | None = None


class UserBrief(ORMModel):
    id: int
    username: str
    full_name: str | None = None
    is_superuser: bool


InstanceOut.model_rebuild()
