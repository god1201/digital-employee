from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    domain: Literal["platform", "system", "custom"] = "custom"
    description: str = ""
    status: Literal["active", "disabled"] = "active"


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    domain: Literal["platform", "system", "custom"] | None = None
    description: str | None = None
    status: Literal["active", "disabled"] | None = None


class KnowledgeBaseOut(ORMModel):
    id: int
    tenant_id: int
    name: str
    code: str
    domain: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source: str | None = Field(default=None, max_length=512)


class DocumentOut(ORMModel):
    id: int
    tenant_id: int
    base_id: int
    title: str
    source: str | None = None
    chunk_count: int
    status: str
    created_at: datetime


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["auto", "keyword", "vector"] = "auto"


class SearchResult(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    chunk_index: int
    content: str
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    embedding_model: str | None = None


class ReindexResult(BaseModel):
    chunks: int
    model: str
    vector_backend: str = "json"
    synced: int = 0


class GraphSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    max_hops: int = Field(default=1, ge=1, le=3)
    answer: bool = True


class GraphSearchResult(BaseModel):
    query: str
    max_hops: int
    seed_entities: list[dict] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)
    chunks: list[dict] = Field(default_factory=list)
    context: str = ""
    answer: str | None = None
    answer_error: str | None = None
    tokens: int = 0


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(default="concept", max_length=64)
    properties: dict = Field(default_factory=dict)


class EntityOut(ORMModel):
    id: int
    tenant_id: int
    base_id: int
    name: str
    entity_type: str
    properties: dict
    created_at: datetime


class RelationCreate(BaseModel):
    source_id: int
    target_id: int
    relation_type: str = Field(default="related", max_length=64)
    properties: dict = Field(default_factory=dict)


class RelationOut(ORMModel):
    id: int
    tenant_id: int
    base_id: int
    source_id: int
    target_id: int
    relation_type: str
    properties: dict
    created_at: datetime


class TripleCreate(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    source_type: str = Field(default="concept", max_length=64)
    relation: str = Field(default="related", max_length=64)
    target: str = Field(min_length=1, max_length=255)
    target_type: str = Field(default="concept", max_length=64)
    properties: dict = Field(default_factory=dict)


class TripleImportRequest(BaseModel):
    triples: list[TripleCreate] = Field(min_length=1)


class TripleImportResult(BaseModel):
    created_entities: int
    created_relations: int


class GraphOut(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class MultimodalExtractionOut(ORMModel):
    id: int
    tenant_id: int
    filename: str
    content_type: str | None = None
    kind: str
    status: str
    text: str
    tables: list
    provider: str
    meta: dict
    error: str | None = None
    created_at: datetime
