from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class RiskRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: Literal["content", "business"] = "content"
    keywords: list[str] = Field(default_factory=list, max_length=200)
    action: Literal["block", "review", "allow"] = "review"
    severity: Literal["low", "medium", "high"] = "medium"
    enabled: bool = True
    description: str = ""


class RiskRuleUpdate(BaseModel):
    name: str | None = None
    category: Literal["content", "business"] | None = None
    keywords: list[str] | None = None
    action: Literal["block", "review", "allow"] | None = None
    severity: Literal["low", "medium", "high"] | None = None
    enabled: bool | None = None
    description: str | None = None


class RiskRuleOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    category: str
    keywords: list
    action: str
    severity: str
    enabled: bool
    description: str
    created_at: datetime
    updated_at: datetime


class RiskCheckRequest(BaseModel):
    content: str = Field(min_length=1)
    category: Literal["content", "business"] = "content"


class RiskCheckOut(ORMModel):
    id: int
    tenant_id: int
    content: str
    category: str
    decision: str
    score: float
    matched_rules: list
    created_at: datetime
