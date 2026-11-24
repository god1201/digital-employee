from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.schema_common import ORMModel

AutonomyLevel = Literal["L0", "L1", "L2", "L3"]


class RedLinePolicy(BaseModel):
    """权限红线。未声明的字段按默认值处理，允许扩展自定义规则。"""

    model_config = ConfigDict(extra="allow")

    read_only: bool = False
    forbidden_tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    amount_threshold: float | None = None
    amount_field: str = "amount"
    count_threshold: int | None = None
    count_field: str = "count"
    sandbox_required: bool = False


class JobContractUpsert(BaseModel):
    role: str = Field(default="", max_length=128)
    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    must_ask: list[str] = Field(default_factory=list)
    kpi: dict = Field(default_factory=dict)
    report_to: str | None = Field(default=None, max_length=128)
    report_freq: str | None = Field(default=None, max_length=128)
    work_hours: str | None = Field(default=None, max_length=128)
    escalation_path: list[str] = Field(default_factory=list)
    autonomy_level: AutonomyLevel = "L2"
    autonomy_overrides: dict[str, AutonomyLevel] = Field(default_factory=dict)
    red_lines: RedLinePolicy = Field(default_factory=RedLinePolicy)
    status: Literal["draft", "active", "archived"] = "active"


class JobContractOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    role: str
    can_do: list
    cannot_do: list
    must_ask: list
    kpi: dict
    report_to: str | None = None
    report_freq: str | None = None
    work_hours: str | None = None
    escalation_path: list
    autonomy_level: str
    autonomy_overrides: dict
    red_lines: dict
    version: int
    status: str
    created_at: datetime
    updated_at: datetime


class ContractCheckRequest(BaseModel):
    tool_code: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
    step_name: str = ""
    step_description: str = ""


class ContractDecisionOut(BaseModel):
    action: Literal["allow", "ask", "deny"]
    reason: str
    rule: str
    autonomy_level: str
    matched: list[str] = Field(default_factory=list)
