from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.knowledge.models import MultimodalExtraction
from app.domains.knowledge.multimodal import extract
from app.domains.knowledge.schemas import MultimodalExtractionOut
from app.domains.learning.onboarding import import_knowledge_document

router = APIRouter(prefix="/multimodal", tags=["多模态解析"])


@router.post("/extract", summary="解析文本/表格/图片/音频/PDF")
async def extract_file(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    knowledge_base_id: int | None = Form(default=None),
    title: str | None = Form(default=None),
):
    data = await file.read()
    result = await extract(file.filename or "", file.content_type, data)
    record = MultimodalExtraction(
        tenant_id=current_user.tenant_id,
        filename=(file.filename or "")[:255],
        content_type=file.content_type,
        kind=result["kind"],
        status="succeeded",
        text=result["text"],
        tables=result["tables"],
        provider=result["provider"],
        meta=result["meta"],
        created_by=current_user.id,
    )
    db.add(record)
    await db.flush()

    document_id = None
    if knowledge_base_id is not None and result["text"].strip():
        document = await import_knowledge_document(
            db,
            current_user.tenant_id,
            knowledge_base_id,
            title or record.filename or "多模态解析结果",
            result["text"],
            user_id=current_user.id,
            source="multimodal",
        )
        document_id = document.id

    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="multimodal.extract",
        resource_type="multimodal_extraction",
        resource_id=record.id,
        detail={
            "kind": record.kind,
            "provider": record.provider,
            "knowledge_document_id": document_id,
        },
        ip_address=client_ip(request),
    )
    payload = MultimodalExtractionOut.model_validate(record).model_dump(mode="json")
    payload["knowledge_document_id"] = document_id
    return success(payload)


@router.get("/extractions", summary="多模态解析记录")
async def list_extractions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    kind: str | None = None,
):
    conditions = [MultimodalExtraction.tenant_id == current_user.tenant_id]
    if kind:
        conditions.append(MultimodalExtraction.kind == kind)
    stmt = select(MultimodalExtraction).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(MultimodalExtraction.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [
            MultimodalExtractionOut.model_validate(item).model_dump(mode="json")
            for item in items
        ],
        total,
        page,
        page_size,
    )
