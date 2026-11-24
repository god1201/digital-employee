from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

RuleType = Literal["keyword", "regex", "min_length", "max_length"]
InspectionDecision = Literal["pass", "review", "reject"]


class InspectionRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    category: Literal["content", "service", "text"] = "content"
    rule_type: RuleType = "keyword"
    config: dict = Field(default_factory=dict)
    penalty: int = Field(default=10, ge=0, le=100)
    blocking: bool = False
    enabled: bool = True
    description: str = ""


class InspectionRuleUpdate(BaseModel):
    name: str | None = None
    category: Literal["content", "service", "text"] | None = None
    rule_type: RuleType | None = None
    config: dict | None = None
    penalty: int | None = Field(default=None, ge=0, le=100)
    blocking: bool | None = None
    enabled: bool | None = None
    description: str | None = None


class InspectionRuleOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    category: str
    rule_type: str
    config: dict
    penalty: int
    blocking: bool
    enabled: bool
    description: str
    created_at: datetime
    updated_at: datetime


class InspectionCheckRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    category: str | None = None


class InspectionRecordOut(ORMModel):
    id: int
    tenant_id: int
    title: str
    content: str
    category: str
    score: float
    grade: str
    decision: str
    rule_results: list
    status: str
    review_comment: str | None = None
    reviewed_by: int | None = None
    created_at: datetime
    updated_at: datetime


class InspectionReviewRequest(BaseModel):
    decision: Literal["pass", "reject"]
    comment: str | None = Field(default=None, max_length=1024)


class HallucinationCheckRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)
    sources: list[str] = Field(min_length=1, max_length=20)
    question: str | None = Field(default=None, max_length=2000)
    employee_id: int | None = None
    instance_id: int | None = None


class HallucinationCheckOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    instance_id: int | None = None
    question: str | None = None
    answer: str
    sources: list
    score: float
    grounded: bool
    details: list
    created_at: datetime
