from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

AgentType = Literal["internal", "third_party"]
AgentProtocol = Literal["builtin", "openai", "http"]


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    agent_type: AgentType = "internal"
    protocol: AgentProtocol = "builtin"
    description: str = ""
    endpoint_url: str | None = Field(default=None, max_length=1024)
    headers: dict[str, str] = Field(default_factory=dict)
    model_provider: str = Field(default="openai", max_length=64)
    model_name: str = Field(default="", max_length=128)
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    status: Literal["active", "disabled"] = "active"


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = None
    agent_type: AgentType | None = None
    protocol: AgentProtocol | None = None
    description: str | None = None
    endpoint_url: str | None = None
    headers: dict[str, str] | None = None
    model_provider: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    capabilities: list[str] | None = None
    config: dict | None = None
    status: Literal["active", "disabled"] | None = None


class AgentOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    agent_type: str
    protocol: str
    description: str
    endpoint_url: str | None = None
    headers: dict
    model_provider: str
    model_name: str
    system_prompt: str
    tools: list
    capabilities: list
    config: dict
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class AgentInvokeRequest(BaseModel):
    input: dict = Field(default_factory=dict)
    prompt: str | None = None
    employee_id: int | None = None


class AgentInvokeResult(BaseModel):
    agent_id: int
    agent_code: str
    output: dict
    tokens: int
    latency_ms: int
    tool_calls: list[dict] = Field(default_factory=list)
