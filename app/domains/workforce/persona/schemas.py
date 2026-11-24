from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class PersonaUpsert(BaseModel):
    tone: Literal["professional", "friendly", "concise", "formal"] = "professional"
    address_style: str | None = Field(default=None, max_length=128)
    output_format: Literal[
        "conclusion_first", "bullets", "table", "detailed"
    ] = "conclusion_first"
    report_style: Literal[
        "conclusion_first", "detailed", "bullets"
    ] = "conclusion_first"
    taboo_words: list[str] = Field(default_factory=list)
    signature: str | None = Field(default=None, max_length=255)
    polish_enabled: bool = False
    extra_instructions: str = ""


class PersonaOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    tone: str
    address_style: str | None = None
    output_format: str
    report_style: str
    taboo_words: list
    signature: str | None = None
    polish_enabled: bool
    extra_instructions: str
    version: int
    created_at: datetime
    updated_at: datetime
