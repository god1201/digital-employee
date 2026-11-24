"""跨知识库文档检索：供对话 @文件 选择器使用。"""

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.response import paged
from app.domains.knowledge.models import KnowledgeBase, KnowledgeDocument

router = APIRouter(prefix="/knowledge-documents", tags=["知识库"])


@router.get("", summary="跨知识库文档列表")
async def list_all_documents(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(None),
    base_id: int | None = Query(None),
):
    conditions = [
        KnowledgeDocument.tenant_id == current_user.tenant_id,
        KnowledgeDocument.status == "active",
    ]
    if base_id is not None:
        conditions.append(KnowledgeDocument.base_id == base_id)
    if keyword:
        conditions.append(
            or_(
                KnowledgeDocument.title.ilike(f"%{keyword}%"),
                KnowledgeDocument.source.ilike(f"%{keyword}%"),
            )
        )

    stmt = (
        select(KnowledgeDocument, KnowledgeBase)
        .join(KnowledgeBase, KnowledgeDocument.base_id == KnowledgeBase.id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.execute(
        stmt.order_by(KnowledgeDocument.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        {
            "id": document.id,
            "base_id": document.base_id,
            "base_name": base.name,
            "title": document.title,
            "source": document.source,
            "chunk_count": document.chunk_count,
            "updated_at": document.updated_at.isoformat(),
        }
        for document, base in rows.all()
    ]
    return paged(items, total, page, page_size)
