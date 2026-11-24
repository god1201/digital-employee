from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

ApprovalThreshold = Literal["low", "medium", "high", "dual"]
SandboxType = Literal["none", "readonly", "docker", "vm"]


class RolePresetCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    default_skills: list[str] = Field(default_factory=list)
    tool_groups: list[str] = Field(default_factory=list)
    approval_threshold: ApprovalThreshold = "medium"
    sandbox: SandboxType = "none"
    status: Literal["active", "disabled"] = "active"


class RolePresetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_skills: list[str] | None = None
    tool_groups: list[str] | None = None
    approval_threshold: ApprovalThreshold | None = None
    sandbox: SandboxType | None = None
    status: Literal["active", "disabled"] | None = None


class RolePresetOut(ORMModel):
    id: int
    tenant_id: int | None = None
    code: str
    name: str
    description: str
    default_skills: list
    tool_groups: list
    approval_threshold: str
    sandbox: str
    status: str
    is_builtin: bool
    created_at: datetime


class TeamTemplateCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    category: str = "通用"
    roles: list[dict] = Field(default_factory=list)
    topology: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class TeamTemplateOut(ORMModel):
    id: int
    tenant_id: int | None = None
    code: str
    name: str
    description: str
    category: str
    roles: list
    topology: dict
    tags: list
    is_builtin: bool
    enabled: bool
    created_at: datetime


class TeamMemberInput(BaseModel):
    role_code: str = Field(min_length=1, max_length=64)
    role_name: str | None = None
    employee_name: str | None = None
    model_name: str | None = None
    skills: list[str] | None = None
    tools: list[str] | None = None
    approval_threshold: ApprovalThreshold | None = None
    sandbox: SandboxType | None = None
    reports_to: str | None = None


class TeamCreate(BaseModel):
    template_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    code: str | None = Field(default=None, max_length=64)
    description: str = ""
    members: list[TeamMemberInput] | None = None
    topology: dict | None = None
    auto_activate: bool = False


class TeamMemberOut(ORMModel):
    id: int
    team_id: int
    employee_id: int | None = None
    role_code: str
    role_name: str
    skills: list
    tools: list
    approval_threshold: str
    sandbox: str
    reports_to: str | None = None
    status: str
    employee_name: str | None = None
    employee_code: str | None = None
    employee_status: str | None = None


class TeamOut(ORMModel):
    id: int
    tenant_id: int
    template_id: int | None = None
    name: str
    code: str
    description: str
    status: str
    topology: dict
    config: dict
    member_count: int = 0
    template_name: str | None = None
    created_at: datetime
    updated_at: datetime


class TeamDetail(TeamOut):
    template_name: str | None = None
    members: list[TeamMemberOut] = Field(default_factory=list)
