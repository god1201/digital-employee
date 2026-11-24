from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class JobTemplateOut(ORMModel):
    id: int
    tenant_id: int | None = None
    code: str
    name: str
    category: str
    description: str
    role_code: str
    skill_codes: list
    tool_codes: list
    knowledge_base_ids: list
    persona: dict
    contract: dict
    eval_suite_code: str | None = None
    is_builtin: bool
    enabled: bool
    created_at: datetime


class ApplyTemplateRequest(BaseModel):
    template_code: str = Field(min_length=1, max_length=64)
    install_skills: bool = True
    upsert_persona: bool = True
    create_contract_draft: bool = True
    bind_knowledge_bases: bool = True
    scope: Literal["personal", "team", "organization"] = "personal"


class ApplyTemplateResult(BaseModel):
    template: JobTemplateOut
    skills: dict
    persona: dict
    contract: dict
    knowledge_bases: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
