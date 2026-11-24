from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class AuthorizationCreate(BaseModel):
    employee_id: int | None = None
    system_name: str = Field(min_length=1, max_length=128)
    system_code: str = Field(min_length=1, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    access_type: Literal["login", "api_key", "oauth2", "token", "cookie"] = "api_key"
    username: str | None = Field(default=None, max_length=128)
    credential: str | None = Field(default=None, description="明文仅用于写入，服务端加密存储")
    expires_at: datetime | None = None
    description: str | None = None


class AuthorizationUpdate(BaseModel):
    employee_id: int | None = None
    system_name: str | None = None
    base_url: str | None = None
    access_type: Literal["login", "api_key", "oauth2", "token", "cookie"] | None = None
    username: str | None = None
    credential: str | None = None
    expires_at: datetime | None = None
    status: Literal["active", "disabled"] | None = None
    description: str | None = None


class AuthorizationOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    system_name: str
    system_code: str
    base_url: str | None = None
    access_type: str
    username: str | None = None
    has_credential: bool = False
    expires_at: datetime | None = None
    status: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class AccessRuleCreate(BaseModel):
    employee_id: int | None = None
    system_code: str | None = Field(default=None, max_length=64)
    method: str = Field(default="*", max_length=16)
    path_pattern: str = Field(min_length=1, max_length=512)
    effect: Literal["allow", "deny"] = "deny"
    priority: int = Field(default=100, ge=0, le=100000)
    enabled: bool = True
    description: str | None = None


class AccessRuleUpdate(BaseModel):
    employee_id: int | None = None
    system_code: str | None = None
    method: str | None = None
    path_pattern: str | None = None
    effect: Literal["allow", "deny"] | None = None
    priority: int | None = Field(default=None, ge=0, le=100000)
    enabled: bool | None = None
    description: str | None = None


class AccessRuleOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    system_code: str | None = None
    method: str
    path_pattern: str
    effect: str
    priority: int
    enabled: bool
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class AccessCheckRequest(BaseModel):
    employee_id: int
    method: str = Field(default="GET", max_length=16)
    path: str = Field(min_length=1, max_length=2048)
    system_code: str | None = None


class AccessCheckResult(BaseModel):
    allowed: bool
    effect: str
    rule_id: int | None = None
    reason: str
