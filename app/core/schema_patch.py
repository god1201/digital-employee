"""PostgreSQL 开发库的轻量字段补齐。

生产环境请使用 Alembic；这里只解决“已有开发库不想重建”的过渡场景。
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

POSTGRES_COLUMN_PATCHES: dict[str, dict[str, str]] = {
    "knowledge_chunks": {
        "embedding": "JSON NOT NULL DEFAULT '[]'::json",
        "embedding_model": "VARCHAR(128)",
    },
}


async def apply_postgres_schema_patches(conn: AsyncConnection) -> list[str]:
    applied: list[str] = []
    for table, columns in POSTGRES_COLUMN_PATCHES.items():
        for name, ddl in columns.items():
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"))
            applied.append(f"{table}.{name}")

    if applied:
        logger.warning("已检查 PostgreSQL 开发库字段: %s", ", ".join(applied))
    return applied
