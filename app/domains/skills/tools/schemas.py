from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

ToolType = Literal["http", "python", "mcp"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class ToolBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    tool_type: ToolType = "http"
    description: str = ""
    parameters_schema: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    risk_level: RiskLevel = "low"
    enabled: bool = True
    source: Literal["custom", "third_party", "mcp"] = "custom"
    api_registry_id: int | None = None
    mcp_server: str | None = Field(default=None, max_length=255)


class ToolCreate(ToolBase):
    pass


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters_schema: dict | None = None
    config: dict | None = None
    risk_level: RiskLevel | None = None
    enabled: bool | None = None
    api_registry_id: int | None = None
    mcp_server: str | None = None


class ToolOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    tool_type: str
    description: str
    parameters_schema: dict
    config: dict
    risk_level: str
    enabled: bool
    source: str
    api_registry_id: int | None = None
    mcp_server: str | None = None
    created_at: datetime
    updated_at: datetime
