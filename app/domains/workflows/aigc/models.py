from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin

JOB_TYPES = ("text_to_image", "text_to_video", "image_to_video")
JOB_TYPE_LABELS = {
    "text_to_image": "文生图",
    "text_to_video": "文生视频",
    "image_to_video": "图生视频",
}


class AigcProvider(IdMixin, TenantMixin, TimestampMixin, Base):
    """AIGC 生成服务配置：内置 Mock、OpenAI 兼容、ComfyUI、通用 HTTP 适配器。"""

    __tablename__ = "aigc_providers"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32),
        default="mock",
        nullable=False,
        comment="mock/openai_image/comfyui/http_generic",
    )
    base_url: Mapped[str | None] = mapped_column(String(512))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    supported_types: Mapped[list] = mapped_column(
        JSON, default=lambda: list(JOB_TYPES), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    cost_per_unit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_unit: Mapped[str] = mapped_column(
        String(16), default="image", nullable=False, comment="image/video/second/request"
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(Integer)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_encrypted)


class AigcPromptTemplate(IdMixin, TenantMixin, TimestampMixin, Base):
    """可复用的提示词模板，按生成类型分类，支持 {{变量}} 占位符。"""

    __tablename__ = "aigc_prompt_templates"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(32),
        default="text_to_image",
        nullable=False,
        comment="text_to_image/text_to_video/image_to_video",
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    variables: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(Integer)


class AigcJob(IdMixin, TenantMixin, TimestampMixin, Base):
    """AIGC 生成任务，同时作为持久化队列表。"""

    __tablename__ = "aigc_jobs"

    provider_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("aigc_providers.id"), index=True
    )
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("aigc_prompt_templates.id"), index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    input_asset_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        comment="pending/running/succeeded/failed/cancelled",
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, comment="失败退避后的可执行时间"
    )
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class AigcAsset(IdMixin, TenantMixin, TimestampMixin, Base):
    """素材库：生成结果与用户上传的源图。文件落在本地存储目录，也支持远程 URL。"""

    __tablename__ = "aigc_assets"

    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("aigc_jobs.id"), index=True
    )
    asset_type: Mapped[str] = mapped_column(
        String(16), default="image", nullable=False, comment="image/video"
    )
    source: Mapped[str] = mapped_column(
        String(16), default="generated", nullable=False, comment="generated/uploaded"
    )
    storage_path: Mapped[str | None] = mapped_column(String(512))
    public_url: Mapped[str | None] = mapped_column(String(1024))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(
        String(128), default="application/octet-stream", nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, comment="pending/approved/rejected"
    )
    review_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class AigcReview(IdMixin, TenantMixin, TimestampMixin, Base):
    """素材审核记录，保留每次通过/驳回的历史。"""

    __tablename__ = "aigc_reviews"

    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("aigc_assets.id"), index=True, nullable=False
    )
    decision: Mapped[str] = mapped_column(
        String(16), default="approve", nullable=False, comment="approve/reject"
    )
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(Integer)
