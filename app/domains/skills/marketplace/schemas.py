from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

SkillCategory = Literal["language", "data", "process", "audit", "learning"]
SkillStatus = Literal["draft", "published", "deprecated"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class SkillDependency(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    min_version: int = Field(default=1, ge=1)


class SkillPermissions(BaseModel):
    read_only: bool = False
    amount_threshold: float | None = None
    risk_level: RiskLevel = "low"
    data_scopes: list[str] = Field(default_factory=list)


class SkillPackageCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=128)
    category: SkillCategory = "language"
    description: str = ""
    algorithm: str = Field(default="", max_length=256)
    tool_codes: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[int] = Field(default_factory=list)
    prompt_template: str = ""
    eval_case_ids: list[int] = Field(default_factory=list)
    dependencies: list[SkillDependency] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    common_combos: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


class SkillPackageVersionCreate(BaseModel):
    name: str | None = None
    category: SkillCategory | None = None
    description: str | None = None
    algorithm: str | None = None
    tool_codes: list[str] | None = None
    knowledge_base_ids: list[int] | None = None
    prompt_template: str | None = None
    eval_case_ids: list[int] | None = None
    dependencies: list[SkillDependency] | None = None
    conflicts_with: list[str] | None = None
    permissions: SkillPermissions | None = None
    common_combos: list[str] | None = None
    tags: list[str] | None = None
    extra: dict | None = None


class SkillPackageOut(ORMModel):
    id: int
    tenant_id: int | None = None
    code: str
    name: str
    category: str
    description: str
    version: int
    status: str
    is_builtin: bool
    algorithm: str
    tool_codes: list
    knowledge_base_ids: list
    prompt_template: str
    eval_case_ids: list
    dependencies: list
    conflicts_with: list
    permissions: dict
    common_combos: list
    tags: list
    extra: dict
    created_at: datetime
    updated_at: datetime


class EmployeeSkillOut(BaseModel):
    id: int
    employee_id: int
    skill_code: str
    version: int
    status: str
    source: str
    config: dict
    installed_at: datetime
    package_name: str = ""
    category: str = ""
    description: str = ""
    tool_codes: list = Field(default_factory=list)
    prompt_template: str = ""


class SkillInstallRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)
    source: Literal["marketplace", "copy", "ai_suggest", "role_preset"] = "marketplace"


class SkillInstallResult(BaseModel):
    installed: list[EmployeeSkillOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    permissions: dict = Field(default_factory=dict)


class SkillUpgradeResult(BaseModel):
    skill: EmployeeSkillOut
    runs: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SkillCopyRequest(BaseModel):
    source_employee_id: int
    skill_code: str = Field(min_length=1, max_length=64)


class SkillToggleRequest(BaseModel):
    enabled: bool


class SkillRecommendationOut(BaseModel):
    code: str
    name: str
    category: str
    version: int
    score: float
    reason: str
    source: str = "rule"
