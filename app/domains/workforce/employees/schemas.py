from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class EmployeeBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    avatar: str | None = Field(default=None, max_length=512)
    position: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    agent_id: int | None = Field(default=None, ge=1)
    model_provider: str = Field(default="openai", max_length=64)
    model_name: str = Field(default="", max_length=128)
    system_prompt: str = ""
    config: dict = Field(default_factory=dict)


class EmployeeCreate(EmployeeBase):
    status: Literal["draft", "active", "disabled"] = "draft"


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    avatar: str | None = None
    position: str | None = None
    description: str | None = None
    status: Literal["draft", "active", "disabled"] | None = None
    agent_id: int | None = Field(default=None, ge=1)
    model_provider: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    config: dict | None = None


class EmployeeKnowledgeBasesUpdate(BaseModel):
    knowledge_base_ids: list[int] = Field(default_factory=list)


class EmployeeOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    avatar: str | None = None
    position: str | None = None
    description: str | None = None
    status: str
    agent_id: int | None = None
    agent_name: str | None = None
    agent_code: str | None = None
    model_provider: str
    model_name: str
    system_prompt: str
    config: dict
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
