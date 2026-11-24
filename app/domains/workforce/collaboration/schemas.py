from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class CollaborationParticipant(BaseModel):
    employee_id: int | None = None
    employee_code: str | None = Field(default=None, max_length=64)
    instruction: str = Field(min_length=1, max_length=2000)
    steps: list[dict] = Field(
        default_factory=list,
        description="可选：固定子任务步骤；为空时由目标员工自由规划（需要 LLM）",
    )


class CollaborationCreate(BaseModel):
    owner_employee_id: int
    goal: str = Field(min_length=1, max_length=2000)
    mode: Literal["sequential", "parallel"] = "sequential"
    participants: list[CollaborationParticipant] = Field(min_length=1, max_length=10)
    summarize: bool = True


class CollaborationOut(ORMModel):
    id: int
    tenant_id: int
    owner_employee_id: int
    goal: str
    mode: str
    participants: list
    parent_instance_id: int | None = None
    status: str
    result: dict
    created_at: datetime
    updated_at: datetime
