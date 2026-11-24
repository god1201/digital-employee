from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.knowledge.embedding import embed_texts
from app.domains.knowledge.graph_rag import graph_rag
from app.domains.knowledge.models import (
    GraphEntity,
    GraphRelation,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.domains.knowledge.schemas import (
    DocumentCreate,
    DocumentOut,
    EntityCreate,
    EntityOut,
    GraphOut,
    GraphSearchRequest,
    GraphSearchResult,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    ReindexResult,
    RelationCreate,
    RelationOut,
    SearchRequest,
    TripleImportRequest,
    TripleImportResult,
)
from app.domains.knowledge.service import (
    chunk_text,
    delete_base_cascade,
    import_triples,
    reindex_chunks,
    search_knowledge,
)
from app.domains.knowledge.vector_store import (
    delete_vectors_for_document,
    upsert_chunk_vectors,
    vector_backend,
)

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


async def _get_base(db: DbSession, tenant_id: int, base_id: int) -> KnowledgeBase:
    base = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == base_id,
            KnowledgeBase.tenant_id == tenant_id,
        )
    )
    if base is None:
        raise NotFoundError("知识库不存在")
    return base


@router.get("", summary="知识库列表")
async def list_bases(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
):
    conditions = [KnowledgeBase.tenant_id == current_user.tenant_id]
    if keyword:
        conditions.append(
            or_(
                KnowledgeBase.name.ilike(f"%{keyword}%"),
                KnowledgeBase.code.ilike(f"%{keyword}%"),
            )
        )
    stmt = select(KnowledgeBase).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(KnowledgeBase.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [KnowledgeBaseOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="创建知识库")
async def create_base(
    payload: KnowledgeBaseCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    exists = await db.scalar(
        select(KnowledgeBase.id).where(
            KnowledgeBase.tenant_id == current_user.tenant_id,
            KnowledgeBase.code == payload.code,
        )
    )
    if exists:
        raise ConflictError("知识库编码已存在")
    base = KnowledgeBase(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(base)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_base.create",
        resource_type="knowledge_base",
        resource_id=base.id,
        detail={"code": base.code, "domain": base.domain},
        ip_address=client_ip(request),
    )
    return success(KnowledgeBaseOut.model_validate(base).model_dump(mode="json"))


@router.get("/{base_id}", summary="知识库详情")
async def get_base(base_id: int, db: DbSession, current_user: CurrentUser):
    base = await _get_base(db, current_user.tenant_id, base_id)
    return success(KnowledgeBaseOut.model_validate(base).model_dump(mode="json"))


@router.patch("/{base_id}", summary="更新知识库")
async def update_base(
    base_id: int,
    payload: KnowledgeBaseUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(base, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_base.update",
        resource_type="knowledge_base",
        resource_id=base.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(KnowledgeBaseOut.model_validate(base).model_dump(mode="json"))


@router.delete("/{base_id}", summary="删除知识库（级联）")
async def delete_base(
    base_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    await delete_base_cascade(db, base.id, current_user.tenant_id)
    await db.delete(base)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_base.delete",
        resource_type="knowledge_base",
        resource_id=base_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.get("/{base_id}/documents", summary="文档列表")
async def list_documents(
    base_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.tenant_id == current_user.tenant_id,
        KnowledgeDocument.base_id == base.id,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(KnowledgeDocument.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [DocumentOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/{base_id}/documents", summary="新增文档并自动分块")
async def create_document(
    base_id: int,
    payload: DocumentCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    chunks = chunk_text(payload.content)
    if not chunks:
        raise BadRequestError("文档内容为空")

    vectors, embedding_model = await embed_texts(chunks)

    document = KnowledgeDocument(
        tenant_id=current_user.tenant_id,
        base_id=base.id,
        title=payload.title,
        content=payload.content,
        source=payload.source,
        chunk_count=len(chunks),
        created_by=current_user.id,
    )
    db.add(document)
    await db.flush()

    chunk_rows = []
    for index, chunk in enumerate(chunks):
        row = KnowledgeChunk(
            tenant_id=current_user.tenant_id,
            base_id=base.id,
            document_id=document.id,
            chunk_index=index,
            content=chunk,
            embedding=vectors[index] if index < len(vectors) else [],
            embedding_model=embedding_model,
        )
        db.add(row)
        chunk_rows.append(row)
    await db.flush()
    await upsert_chunk_vectors(db, chunk_rows, vectors, embedding_model)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_document.create",
        resource_type="knowledge_document",
        resource_id=document.id,
        detail={"base_id": base.id, "chunk_count": len(chunks)},
        ip_address=client_ip(request),
    )
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.delete("/{base_id}/documents/{document_id}", summary="删除文档")
async def delete_document(
    base_id: int,
    document_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    document = await db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.base_id == base.id,
            KnowledgeDocument.tenant_id == current_user.tenant_id,
        )
    )
    if document is None:
        raise NotFoundError("文档不存在")

    chunks = list(
        (
            await db.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id,
                    KnowledgeChunk.tenant_id == current_user.tenant_id,
                )
            )
        ).all()
    )
    await delete_vectors_for_document(db, document.id)
    for chunk in chunks:
        await db.delete(chunk)
    await db.delete(document)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_document.delete",
        resource_type="knowledge_document",
        resource_id=document_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/{base_id}/search", summary="知识检索")
async def search(
    base_id: int,
    payload: SearchRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    results = await search_knowledge(
        db,
        current_user.tenant_id,
        base.id,
        payload.query,
        payload.top_k,
        payload.mode,
    )
    return success({"query": payload.query, "mode": payload.mode, "results": results})


@router.post("/{base_id}/graph-search", summary="GraphRAG 图谱问答")
async def graph_search(
    base_id: int,
    payload: GraphSearchRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    result = await graph_rag(
        db,
        current_user.tenant_id,
        base.id,
        payload.query,
        payload.top_k,
        payload.max_hops,
        payload.answer,
    )
    return success(GraphSearchResult(**result).model_dump(mode="json"))


@router.post("/{base_id}/reindex", summary="重建知识分块向量")
async def reindex(
    base_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    result = await reindex_chunks(db, current_user.tenant_id, base.id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="knowledge_base.reindex",
        resource_type="knowledge_base",
        resource_id=base.id,
        detail=result,
        ip_address=client_ip(request),
    )
    return success(ReindexResult(**result).model_dump(mode="json"))


@router.get("/{base_id}/vector-status", summary="向量后端状态")
async def vector_status(
    base_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    return success(
        {
            "base_id": base.id,
            "backend": await vector_backend(db),
            "configured": "auto"
            if not settings.vector_backend
            else settings.vector_backend,
        }
    )


@router.get("/{base_id}/graph", summary="知识图谱数据")
async def graph(base_id: int, db: DbSession, current_user: CurrentUser):
    base = await _get_base(db, current_user.tenant_id, base_id)
    entities = list(
        (
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.tenant_id == current_user.tenant_id,
                    GraphEntity.base_id == base.id,
                )
            )
        ).all()
    )
    relations = list(
        (
            await db.scalars(
                select(GraphRelation).where(
                    GraphRelation.tenant_id == current_user.tenant_id,
                    GraphRelation.base_id == base.id,
                )
            )
        ).all()
    )
    data = GraphOut(
        nodes=[
            {
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "properties": entity.properties,
            }
            for entity in entities
        ],
        edges=[
            {
                "id": relation.id,
                "source": relation.source_id,
                "target": relation.target_id,
                "type": relation.relation_type,
                "properties": relation.properties,
            }
            for relation in relations
        ],
    )
    return success(data.model_dump(mode="json"))


@router.get("/{base_id}/entities", summary="实体列表")
async def list_entities(base_id: int, db: DbSession, current_user: CurrentUser):
    base = await _get_base(db, current_user.tenant_id, base_id)
    items = list(
        (
            await db.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.tenant_id == current_user.tenant_id,
                    GraphEntity.base_id == base.id,
                )
                .order_by(GraphEntity.id.desc())
                .limit(1000)
            )
        ).all()
    )
    return paged(
        [EntityOut.model_validate(item).model_dump(mode="json") for item in items],
        len(items),
        1,
        len(items) or 1,
    )


@router.post("/{base_id}/entities", summary="创建实体")
async def create_entity(
    base_id: int,
    payload: EntityCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    entity = GraphEntity(
        tenant_id=current_user.tenant_id,
        base_id=base.id,
        name=payload.name,
        entity_type=payload.entity_type,
        properties=payload.properties,
    )
    db.add(entity)
    await db.flush()
    return success(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.get("/{base_id}/relations", summary="关系列表")
async def list_relations(base_id: int, db: DbSession, current_user: CurrentUser):
    base = await _get_base(db, current_user.tenant_id, base_id)
    items = list(
        (
            await db.scalars(
                select(GraphRelation)
                .where(
                    GraphRelation.tenant_id == current_user.tenant_id,
                    GraphRelation.base_id == base.id,
                )
                .order_by(GraphRelation.id.desc())
                .limit(1000)
            )
        ).all()
    )
    return paged(
        [RelationOut.model_validate(item).model_dump(mode="json") for item in items],
        len(items),
        1,
        len(items) or 1,
    )


@router.post("/{base_id}/relations", summary="创建关系")
async def create_relation(
    base_id: int,
    payload: RelationCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    source = await db.scalar(
        select(GraphEntity.id).where(
            GraphEntity.id == payload.source_id,
            GraphEntity.tenant_id == current_user.tenant_id,
            GraphEntity.base_id == base.id,
        )
    )
    target = await db.scalar(
        select(GraphEntity.id).where(
            GraphEntity.id == payload.target_id,
            GraphEntity.tenant_id == current_user.tenant_id,
            GraphEntity.base_id == base.id,
        )
    )
    if source is None or target is None:
        raise BadRequestError("source_id / target_id 不属于当前知识库")

    relation = GraphRelation(
        tenant_id=current_user.tenant_id,
        base_id=base.id,
        source_id=payload.source_id,
        target_id=payload.target_id,
        relation_type=payload.relation_type,
        properties=payload.properties,
    )
    db.add(relation)
    await db.flush()
    return success(RelationOut.model_validate(relation).model_dump(mode="json"))


@router.post("/{base_id}/import-triples", summary="批量导入三元组")
async def import_triples_endpoint(
    base_id: int,
    payload: TripleImportRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    base = await _get_base(db, current_user.tenant_id, base_id)
    result = await import_triples(
        db,
        current_user.tenant_id,
        base.id,
        payload.triples,
    )
    return success(TripleImportResult(**result).model_dump(mode="json"))
