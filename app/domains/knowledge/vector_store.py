"""可选 pgvector 向量索引；扩展不可用时自动回退 JSON 内积。"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.knowledge.models import KnowledgeChunk

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_chunk_vectors (
    chunk_id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    base_id INTEGER NOT NULL,
    embedding vector NOT NULL,
    model VARCHAR(128),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_vectors_tenant_base
ON knowledge_chunk_vectors (tenant_id, base_id)
"""

_ready: bool | None = None


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.6f}" for value in vector) + "]"


async def _extension_installed(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    )


async def ensure_vector_schema(db: AsyncSession) -> None:
    # 使用 SAVEPOINT，DDL 失败不会污染外层事务
    async with db.begin_nested():
        await db.execute(text(_TABLE_DDL))
        await db.execute(text(_INDEX_DDL))


async def vector_backend(db: AsyncSession) -> str:
    """返回 json 或 pgvector。auto 模式下扩展不存在则回退。"""
    global _ready
    configured = settings.vector_backend.lower()
    if configured == "json":
        return "json"
    if _ready is False and configured == "auto":
        return "json"

    try:
        installed = await _extension_installed(db)
        if not installed:
            if configured == "json":
                return "json"
            try:
                async with db.begin_nested():
                    await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                installed = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "pgvector 扩展不可用，回退 JSON 向量：%s", str(exc)[:200]
                )
                _ready = False
                return "json"
        if installed:
            await ensure_vector_schema(db)
            _ready = True
            return "pgvector"
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector 检测失败，回退 JSON 向量：%s", str(exc)[:200])
        _ready = False
        return "json"
    _ready = False
    return "json"


async def upsert_chunk_vectors(
    db: AsyncSession,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
    model: str,
) -> int:
    if await vector_backend(db) != "pgvector":
        return 0
    synced = 0
    try:
        async with db.begin_nested():
            for chunk, vector in zip(chunks, vectors, strict=False):
                if not vector:
                    continue
                await db.execute(
                    text(
                        """
                        INSERT INTO knowledge_chunk_vectors
                            (chunk_id, tenant_id, base_id, embedding, model, updated_at)
                        VALUES
                            (:chunk_id, :tenant_id, :base_id,
                             CAST(:embedding AS vector), :model, now())
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            model = EXCLUDED.model,
                            updated_at = now()
                        """
                    ),
                    {
                        "chunk_id": chunk.id,
                        "tenant_id": chunk.tenant_id,
                        "base_id": chunk.base_id,
                        "embedding": vector_literal(vector),
                        "model": model,
                    },
                )
                synced += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector 写入失败，保留 JSON 向量：%s", str(exc)[:200])
        return 0
    return synced


async def search_vectors(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    query_vector: list[float],
    limit: int,
) -> list[tuple[int, float]]:
    if await vector_backend(db) != "pgvector" or not query_vector:
        return []
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT chunk_id, 1 - (embedding <=> CAST(:query AS vector)) AS score
                        FROM knowledge_chunk_vectors
                        WHERE tenant_id = :tenant_id AND base_id = :base_id
                        ORDER BY embedding <=> CAST(:query AS vector)
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "base_id": base_id,
                        "query": vector_literal(query_vector),
                        "limit": max(1, int(limit)),
                    },
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector 检索失败，回退 JSON 向量：%s", str(exc)[:200])
        return []
    return [(int(row[0]), float(row[1])) for row in rows]


async def delete_vectors_for_base(db: AsyncSession, base_id: int) -> None:
    if await vector_backend(db) != "pgvector":
        return
    try:
        async with db.begin_nested():
            await db.execute(
                text("DELETE FROM knowledge_chunk_vectors WHERE base_id = :base_id"),
                {"base_id": base_id},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector 清理失败：%s", str(exc)[:200])


async def delete_vectors_for_document(db: AsyncSession, document_id: int) -> None:
    if await vector_backend(db) != "pgvector":
        return
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    """
                    DELETE FROM knowledge_chunk_vectors
                    WHERE chunk_id IN (
                        SELECT id FROM knowledge_chunks WHERE document_id = :document_id
                    )
                    """
                ),
                {"document_id": document_id},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector 清理失败：%s", str(exc)[:200])
