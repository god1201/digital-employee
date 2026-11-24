from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

JobType = Literal["text_to_image", "text_to_video", "image_to_video"]
ProviderType = Literal["mock", "openai_image", "comfyui", "http_generic"]


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider_type: ProviderType = "mock"
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = None
    model: str | None = Field(default=None, max_length=128)
    config: dict = Field(default_factory=dict)
    supported_types: list[JobType] | None = None
    enabled: bool = True
    is_default: bool = False
    priority: int = Field(default=100, ge=0, le=1000)
    cost_per_unit: float = Field(default=0.0, ge=0)
    cost_unit: Literal["image", "video", "second", "request"] = "image"
    timeout_seconds: int = Field(default=180, ge=5, le=1800)
    description: str | None = Field(default=None, max_length=512)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = None
    model: str | None = Field(default=None, max_length=128)
    config: dict | None = None
    supported_types: list[JobType] | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    cost_per_unit: float | None = Field(default=None, ge=0)
    cost_unit: Literal["image", "video", "second", "request"] | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=1800)
    description: str | None = Field(default=None, max_length=512)


class ProviderOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    provider_type: str
    base_url: str | None = None
    model: str | None = None
    config: dict
    supported_types: list
    enabled: bool
    is_default: bool
    priority: int
    cost_per_unit: float
    cost_unit: str
    timeout_seconds: int
    description: str | None = None
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    category: JobType = "text_to_image"
    body: str = Field(min_length=1)
    negative_prompt: str = ""
    variables: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    description: str | None = Field(default=None, max_length=512)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    category: JobType | None = None
    body: str | None = Field(default=None, min_length=1)
    negative_prompt: str | None = None
    variables: dict | None = None
    params: dict | None = None
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=512)


class TemplateOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    category: str
    body: str
    negative_prompt: str
    variables: dict
    params: dict
    enabled: bool
    usage_count: int
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class TemplateRenderRequest(BaseModel):
    values: dict = Field(default_factory=dict)


class GenerationCreate(BaseModel):
    job_type: JobType
    prompt: str | None = None
    negative_prompt: str = ""
    provider_id: int | None = None
    template_id: int | None = None
    template_values: dict = Field(default_factory=dict)
    employee_id: int | None = None
    input_asset_id: int | None = None
    params: dict = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)


class GenerationOut(ORMModel):
    id: int
    tenant_id: int
    provider_id: int | None = None
    provider_name: str | None = None
    template_id: int | None = None
    template_name: str | None = None
    employee_id: int | None = None
    job_type: str
    prompt: str
    negative_prompt: str
    params: dict
    input_asset_id: int | None = None
    status: str
    priority: int
    attempt: int
    max_attempts: int
    error: str | None = None
    risk: dict
    estimated_cost: float
    cost: float
    latency_ms: int
    result: dict
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    assets: list["AssetOut"] = Field(default_factory=list)


class AssetOut(ORMModel):
    id: int
    tenant_id: int
    job_id: int | None = None
    asset_type: str
    source: str
    public_url: str | None = None
    thumbnail_url: str | None = None
    file_name: str | None = None
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    prompt: str
    negative_prompt: str
    provider_name: str | None = None
    model: str | None = None
    review_status: str
    review_note: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    tags: list
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class AssetReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    score: float = Field(default=0.0, ge=0, le=10)
    note: str = ""


class ReviewOut(ORMModel):
    id: int
    asset_id: int
    decision: str
    score: float
    note: str
    reviewer_id: int | None = None
    created_at: datetime


GenerationOut.model_rebuild()
