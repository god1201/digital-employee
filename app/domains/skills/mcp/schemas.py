from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

MCPTransport = Literal["stdio", "sse", "streamable_http"]


class MCPServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    transport: MCPTransport = "stdio"
    command: str | None = Field(default=None, max_length=512)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=1024)
    headers: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    status: Literal["active", "disabled"] = "active"


class MCPServerCreate(MCPServerBase):
    pass


class MCPServerUpdate(BaseModel):
    name: str | None = None
    transport: MCPTransport | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    description: str | None = None
    status: Literal["active", "disabled"] | None = None


class MCPServerOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    transport: str
    command: str | None = None
    args: list
    env: dict
    cwd: str | None = None
    url: str | None = None
    headers: dict
    description: str
    status: str
    tool_count: int
    last_connected_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class MCPSyncResult(BaseModel):
    server_id: int
    tool_count: int
    created: int
    updated: int
    tools: list[dict] = Field(default_factory=list)
