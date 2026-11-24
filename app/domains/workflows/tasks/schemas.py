from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.schema_common import ORMModel


class TaskDefinitionCreate(BaseModel):
    employee_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    task_type: Literal["fixed", "free"] = "fixed"
    description: str | None = None
    steps: list[dict] = Field(default_factory=list)
    enabled: bool = True


class TaskDefinitionUpdate(BaseModel):
    employee_id: int | None = None
    name: str | None = None
    description: str | None = None
    steps: list[dict] | None = None
    enabled: bool | None = None


class TaskDefinitionOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    name: str
    code: str
    task_type: str
    description: str | None = None
    steps: list
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class TaskRunRequest(BaseModel):
    employee_id: int
    definition_id: int | None = None
    title: str | None = Field(default=None, max_length=255)
    input: dict = Field(default_factory=dict)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    priority: int = Field(default=100, ge=0, le=100000)


class TaskStepOut(ORMModel):
    id: int
    instance_id: int
    step_index: int
    name: str
    status: str
    step_type: str
    input: dict
    output: dict
    tool_code: str | None = None
    tokens: int
    cost: float
    latency_ms: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskInstanceOut(ORMModel):
    id: int
    tenant_id: int
    definition_id: int | None = None
    employee_id: int | None = None
    project_id: int | None = None
    title: str
    task_type: str
    status: str
    input: dict
    output: dict
    plan: list
    current_step_index: int
    next_step_index: int
    attempt: int
    max_attempts: int
    priority: int
    next_run_at: datetime | None = None
    locked_by: str | None = None
    error: str | None = None
    trace_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TaskResumeRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=1024)
    final_output: dict | None = Field(
        default=None,
        description="人工终稿。与原输出不同时自动记录接管增量，进入学习流水线",
    )


class TaskInstanceDetail(TaskInstanceOut):
    steps: list[TaskStepOut] = Field(default_factory=list)


class TaskTriggerCreate(BaseModel):
    employee_id: int
    definition_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    trigger_type: Literal["interval", "daily", "event"] = "interval"
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    daily_at: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    event_name: str | None = Field(default=None, max_length=64)
    input: dict = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_schedule(self):
        if self.trigger_type == "interval" and not self.interval_seconds:
            raise ValueError("interval 触发器必须填写 interval_seconds")
        if self.trigger_type == "daily" and not self.daily_at:
            raise ValueError("daily 触发器必须填写 daily_at（HH:MM）")
        if self.trigger_type == "event" and not self.event_name:
            raise ValueError("event 触发器必须填写 event_name")
        return self


class TaskTriggerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    definition_id: int | None = None
    trigger_type: Literal["interval", "daily", "event"] | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    daily_at: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    event_name: str | None = Field(default=None, max_length=64)
    input: dict | None = None
    enabled: bool | None = None


class TaskTriggerOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    definition_id: int | None = None
    name: str
    trigger_type: str
    interval_seconds: int | None = None
    daily_at: str | None = None
    event_name: str | None = None
    input: dict
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime


class FeedbackCreate(BaseModel):
    instance_id: int | None = None
    employee_id: int | None = None
    rating: int = Field(default=0, ge=0, le=5)
    verdict: Literal["accepted", "rejected", "corrected", "unknown"] = "unknown"
    comment: str | None = None
    corrected_output: dict = Field(default_factory=dict)


class FeedbackOut(ORMModel):
    id: int
    tenant_id: int
    instance_id: int | None = None
    employee_id: int | None = None
    rating: int
    verdict: str
    comment: str | None = None
    corrected_output: dict
    status: str
    created_at: datetime
