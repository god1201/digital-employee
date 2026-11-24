from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.schema_common import ORMModel

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "*"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class ApiRegistryBase(BaseModel):
    system_name: str = Field(min_length=1, max_length=128)
    system_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    method: HttpMethod
    path: str = Field(min_length=1, max_length=512)
    summary: str | None = Field(default=None, max_length=512)
    description: str | None = None
    auth_type: str | None = Field(default=None, max_length=32)
    risk_level: RiskLevel = "low"
    request_schema: dict = Field(default_factory=dict)
    response_schema: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", max_length=32)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value


class ApiRegistryCreate(ApiRegistryBase):
    source: Literal["manual", "openapi"] = "manual"


class ApiRegistryUpdate(BaseModel):
    system_name: str | None = None
    name: str | None = None
    method: str | None = None
    path: str | None = None
    summary: str | None = None
    description: str | None = None
    auth_type: str | None = None
    risk_level: RiskLevel | None = None
    request_schema: dict | None = None
    response_schema: dict | None = None
    tags: list[str] | None = None
    status: Literal["active", "disabled"] | None = None
    version: str | None = None


class ApiRegistryOut(ORMModel):
    id: int
    tenant_id: int
    system_name: str
    system_code: str
    name: str
    method: str
    path: str
    summary: str | None = None
    description: str | None = None
    auth_type: str | None = None
    risk_level: str
    request_schema: dict
    response_schema: dict
    tags: list
    status: str
    version: str
    source: str
    created_at: datetime
    updated_at: datetime


class OpenAPIImportRequest(BaseModel):
    system_name: str = Field(min_length=1, max_length=128)
    system_code: str = Field(min_length=1, max_length=64)
    spec: dict = Field(description="OpenAPI 3.x / Swagger 2.0 JSON")
    overwrite: bool = False


class OpenAPIImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
