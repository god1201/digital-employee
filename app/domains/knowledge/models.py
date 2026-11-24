from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class KnowledgeBase(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_knowledge_bases_tenant_code"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(
        String(32), default="custom", nullable=False, comment="platform/system/custom"
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class KnowledgeDocument(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(512))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class KnowledgeChunk(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"

    base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id"), index=True, nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_documents.id"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="向量，本地哈希或外部 Embedding"
    )
    embedding_model: Mapped[str | None] = mapped_column(
        String(128), comment="local-hash / 外部模型名"
    )


class GraphEntity(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "graph_entities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "base_id", "name", "entity_type", name="uq_graph_entity"),
    )

    base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), default="concept", nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GraphRelation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "graph_relations"

    base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id"), index=True, nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.id"), index=True, nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.id"), index=True, nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(64), default="related", nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MultimodalExtraction(IdMixin, TenantMixin, TimestampMixin, Base):
    """多模态解析记录：OCR / ASR / 表格 / 文本抽取结果。"""

    __tablename__ = "multimodal_extractions"

    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(
        String(32), default="text", nullable=False, comment="text/table/image/audio/pdf"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="succeeded", nullable=False, comment="succeeded/failed"
    )
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tables: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), default="local", nullable=False, comment="local/http"
    )
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
