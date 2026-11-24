from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = ""
    status: Literal["active", "paused", "archived"] = "active"
    owner_employee_id: int | None = None
    token_budget: float | None = Field(default=None, ge=0)
    config: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    status: Literal["active", "paused", "archived"] | None = None
    owner_employee_id: int | None = None
    token_budget: float | None = Field(default=None, ge=0)
    config: dict | None = None


class ProjectOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    description: str
    status: str
    owner_employee_id: int | None = None
    token_budget: float | None = None
    config: dict
    created_at: datetime
    updated_at: datetime


class ProjectMemberAdd(BaseModel):
    employee_id: int
    role: Literal["owner", "member", "reviewer"] = "member"


class ProjectTaskLink(BaseModel):
    instance_id: int


class ProjectConversationLink(BaseModel):
    conversation_id: int
