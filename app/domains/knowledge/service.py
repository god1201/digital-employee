import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.embedding import cosine, embed_texts
from app.domains.knowledge.models import (
    GraphEntity,
    GraphRelation,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.domains.knowledge.vector_store import (
    delete_vectors_for_base,
    search_vectors,
    upsert_chunk_vectors,
    vector_backend,
)

_CJK_RE = re.compile(r"[一-鿿]+")
_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def chunk_text(text: str, max_chars: int = 600, overlap: int = 80) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    step = max(1, max_chars - overlap)
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        for start in range(0, len(paragraph), step):
            chunk = paragraph[start : start + max_chars]
            if chunk.strip():
                chunks.append(chunk)
    return chunks


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = set(_WORD_RE.findall(lowered))
    for sequence in _CJK_RE.findall(lowered):
        if len(sequence) == 1:
            tokens.add(sequence)
        else:
            tokens.update(sequence[i : i + 2] for i in range(len(sequence) - 1))
    return [token for token in tokens if token]


async def _document_titles(db: AsyncSession, chunks: list[KnowledgeChunk]) -> dict[int, str]:
    document_ids = {chunk.document_id for chunk in chunks}
    if not document_ids:
        return {}
    rows = (
        await db.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.title).where(
                KnowledgeDocument.id.in_(document_ids)
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _pgvector_results(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    hits: list[tuple[int, float]],
    query_model: str,
) -> list[dict]:
    chunk_ids = [chunk_id for chunk_id, _score in hits]
    chunks = list(
        (
            await db.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.id.in_(chunk_ids),
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.base_id == base_id,
                )
            )
        ).all()
    )
    by_id = {chunk.id: chunk for chunk in chunks}
    titles = await _document_titles(db, chunks)
    results = []
    for chunk_id, score in hits:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": titles.get(chunk.document_id, ""),
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "score": round(float(score), 4),
                "vector_score": round(float(score), 4),
                "keyword_score": 0.0,
                "embedding_model": chunk.embedding_model or query_model or None,
            }
        )
    return results


async def search_knowledge(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    query: str,
    top_k: int = 5,
    mode: str = "auto",
) -> list[dict]:
    """auto=向量+关键词混合，vector=纯向量，keyword=纯关键词。"""
    tokens = tokenize(query)

    query_vector: list[float] = []
    query_model = ""
    if mode in {"auto", "vector"}:
        vectors, query_model = await embed_texts([query])
        query_vector = vectors[0] if vectors else []

    limit = max(1, min(int(top_k), 20))
    if mode == "vector" and query_vector:
        backend = await vector_backend(db)
        if backend == "pgvector":
            hits = await search_vectors(db, tenant_id, base_id, query_vector, limit)
            if hits:
                return await _pgvector_results(
                    db, tenant_id, base_id, hits, query_model
                )

    chunks = list(
        (
            await db.scalars(
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.base_id == base_id,
                )
                .limit(5000)
            )
        ).all()
    )
    if not chunks:
        return []

    titles = await _document_titles(db, chunks)

    scored: list[tuple[float, float, float, KnowledgeChunk]] = []
    for chunk in chunks:
        text = chunk.content.lower()
        keyword_score = float(sum(min(text.count(token), 5) for token in tokens))
        vector_score = 0.0
        if query_vector and chunk.embedding and len(query_vector) == len(chunk.embedding):
            vector_score = cosine(query_vector, chunk.embedding)

        keyword_normalized = min(keyword_score / 5.0, 1.0)
        if mode == "keyword":
            combined = keyword_normalized
        elif mode == "vector":
            combined = vector_score
        else:
            combined = 0.7 * vector_score + 0.3 * keyword_normalized

        if combined <= 0.001:
            continue
        scored.append((combined, keyword_score, vector_score, chunk))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": titles.get(chunk.document_id, ""),
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "score": round(combined, 4),
            "vector_score": round(vector_score, 4),
            "keyword_score": round(keyword_score, 2),
            "embedding_model": chunk.embedding_model or query_model or None,
        }
        for combined, keyword_score, vector_score, chunk in scored[:limit]
    ]


async def reindex_chunks(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
) -> dict:
    chunks = list(
        (
            await db.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.base_id == base_id,
                )
            )
        ).all()
    )
    if not chunks:
        return {"chunks": 0, "model": "none"}

    vectors, model = await embed_texts([chunk.content for chunk in chunks])
    for index, chunk in enumerate(chunks):
        chunk.embedding = vectors[index] if index < len(vectors) else []
        chunk.embedding_model = model
    await db.flush()
    synced = await upsert_chunk_vectors(db, chunks, vectors, model)
    backend = await vector_backend(db)
    return {
        "chunks": len(chunks),
        "model": model,
        "vector_backend": backend,
        "synced": synced,
    }


async def delete_base_cascade(db: AsyncSession, base_id: int, tenant_id: int) -> None:
    await delete_vectors_for_base(db, base_id)
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.base_id == base_id,
            KnowledgeChunk.tenant_id == tenant_id,
        )
    )
    await db.execute(
        delete(KnowledgeDocument).where(
            KnowledgeDocument.base_id == base_id,
            KnowledgeDocument.tenant_id == tenant_id,
        )
    )
    await db.execute(
        delete(GraphRelation).where(
            GraphRelation.base_id == base_id,
            GraphRelation.tenant_id == tenant_id,
        )
    )
    await db.execute(
        delete(GraphEntity).where(
            GraphEntity.base_id == base_id,
            GraphEntity.tenant_id == tenant_id,
        )
    )


async def get_or_create_entity(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    name: str,
    entity_type: str,
    properties: dict | None = None,
) -> tuple[GraphEntity, bool]:
    entity = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.tenant_id == tenant_id,
            GraphEntity.base_id == base_id,
            GraphEntity.name == name,
            GraphEntity.entity_type == entity_type,
        )
    )
    if entity is not None:
        return entity, False
    entity = GraphEntity(
        tenant_id=tenant_id,
        base_id=base_id,
        name=name,
        entity_type=entity_type,
        properties=properties or {},
    )
    db.add(entity)
    await db.flush()
    return entity, True


async def import_triples(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    triples: list,
) -> dict:
    created_entities = 0
    created_relations = 0

    for triple in triples:
        source, source_created = await get_or_create_entity(
            db,
            tenant_id,
            base_id,
            triple.source,
            triple.source_type,
        )
        target, target_created = await get_or_create_entity(
            db,
            tenant_id,
            base_id,
            triple.target,
            triple.target_type,
        )
        created_entities += int(source_created) + int(target_created)

        exists = await db.scalar(
            select(GraphRelation.id).where(
                GraphRelation.tenant_id == tenant_id,
                GraphRelation.base_id == base_id,
                GraphRelation.source_id == source.id,
                GraphRelation.target_id == target.id,
                GraphRelation.relation_type == triple.relation,
            )
        )
        if exists is None:
            db.add(
                GraphRelation(
                    tenant_id=tenant_id,
                    base_id=base_id,
                    source_id=source.id,
                    target_id=target.id,
                    relation_type=triple.relation,
                    properties=triple.properties or {},
                )
            )
            created_relations += 1

    await db.flush()
    return {
        "created_entities": created_entities,
        "created_relations": created_relations,
    }
