from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class ConversationCreate(BaseModel):
    mode: Literal["direct", "group"] = "direct"
    employee_id: int | None = None
    employee_ids: list[int] = Field(default_factory=list)
    title: str = Field(default="", max_length=128)
    project_id: int | None = None


class ConversationMemberAdd(BaseModel):
    employee_id: int
    role: Literal["owner", "member"] = "member"


class ChatSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    target_employee_ids: list[int] = Field(default_factory=list)
    routing_mode: Literal["auto", "all", "explicit"] = "auto"
    context_document_ids: list[int] = Field(default_factory=list)
    context_conversation_ids: list[int] = Field(default_factory=list)
    attachment_ids: list[int] = Field(default_factory=list)


class ChatTaskCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    employee_id: int | None = None
    context_document_ids: list[int] = Field(default_factory=list)
    context_conversation_ids: list[int] = Field(default_factory=list)
    attachment_ids: list[int] = Field(default_factory=list)


class ToolDecisionItem(BaseModel):
    index: int = Field(ge=0)
    approved: bool


class ToolDecisionRequest(BaseModel):
    message_id: int
    decisions: list[ToolDecisionItem] = Field(min_length=1)


class ChatMessageOut(ORMModel):
    id: int
    conversation_id: int
    employee_id: int | None = None
    role: str
    content: str
    tool_calls: list
    tokens: int
    cost: float
    trace_id: str | None = None
    status: str
    message_metadata: dict
    created_at: datetime


class ConversationOut(ORMModel):
    id: int
    tenant_id: int
    mode: str
    title: str
    status: str
    project_id: int | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    members: list[dict] = Field(default_factory=list)
    messages: list[ChatMessageOut] = Field(default_factory=list)
