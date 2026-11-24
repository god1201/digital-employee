from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

AlertMetric = Literal[
    "failure_rate",
    "queue_backlog",
    "avg_duration_ms",
    "token_usage",
    "token_cost",
    "human_intervention_rate",
    "sensitive_actions",
]
AlertOperator = Literal["gt", "gte", "lt", "lte"]


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: AlertMetric
    operator: AlertOperator = "gt"
    threshold: float = 0.0
    window_minutes: int = Field(default=60, ge=1, le=10080)
    cooldown_minutes: int = Field(default=30, ge=0, le=10080)
    webhook_url: str | None = Field(default=None, max_length=1024)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    metric: AlertMetric | None = None
    operator: AlertOperator | None = None
    threshold: float | None = None
    window_minutes: int | None = Field(default=None, ge=1, le=10080)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)
    webhook_url: str | None = None
    enabled: bool | None = None


class AlertRuleOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    metric: str
    operator: str
    threshold: float
    window_minutes: int
    cooldown_minutes: int
    webhook_url: str | None = None
    enabled: bool
    last_triggered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AlertEventOut(ORMModel):
    id: int
    tenant_id: int
    rule_id: int
    rule_name: str
    metric: str
    value: float
    threshold: float
    operator: str
    message: str
    status: str
    webhook_status: str | None = None
    created_at: datetime


class AlertEvaluationResult(BaseModel):
    triggered: bool
    value: float
    event_id: int | None = None
    message: str | None = None
