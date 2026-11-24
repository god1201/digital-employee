import json
import logging
import mimetypes

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import AppError, BadRequestError, NotFoundError
from app.core.response import success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.workforce.conversations.models import ChatAttachment
from app.domains.workforce.conversations.schemas import (
    ChatSendRequest,
    ChatTaskCreate,
    ConversationCreate,
    ConversationMemberAdd,
    ToolDecisionRequest,
)
from app.domains.workforce.conversations.service import (
    add_member,
    archive_conversation,
    conversation_detail,
    create_conversation,
    create_task_from_conversation,
    decide_pending_tools,
    get_conversation,
    list_conversations,
    remove_member,
    send_message,
    stream_message,
)
from app.domains.workforce.conversations.storage import (
    delete_attachment,
    extract_text,
    resolve_attachment,
    safe_extension,
    save_attachment,
)
from app.worker.enqueue import enqueue_task

logger = logging.getLogger(__name__)


def _attachment_out(item: ChatAttachment) -> dict:
    return {
        "id": item.id,
        "conversation_id": item.conversation_id,
        "message_id": item.message_id,
        "file_name": item.file_name,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "has_text": bool(item.text_excerpt),
        "created_at": item.created_at.isoformat(),
    }

router = APIRouter(prefix="/conversations", tags=["数字员工对话"])


@router.post("", summary="创建直接会话或群聊")
async def create_conversation_endpoint(
    payload: ConversationCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation, _members = await create_conversation(
        db, current_user.tenant_id, payload, user_id=current_user.id
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.create",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={
            "mode": conversation.mode,
            "title": conversation.title,
        },
        ip_address=client_ip(request),
    )
    return success(await conversation_detail(db, conversation))


@router.get("", summary="会话列表")
async def list_conversations_endpoint(
    db: DbSession,
    current_user: CurrentUser,
    employee_id: int | None = Query(None),
    mode: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
):
    return success(
        await list_conversations(
            db,
            current_user.tenant_id,
            employee_id=employee_id,
            mode=mode,
            limit=limit,
        )
    )


@router.get("/{conversation_id}", summary="会话详情与消息")
async def get_conversation_endpoint(
    conversation_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    return success(await conversation_detail(db, conversation))


@router.post("/{conversation_id}/messages", summary="发送消息")
async def send_message_endpoint(
    conversation_id: int,
    payload: ChatSendRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    result = await send_message(
        db,
        conversation,
        payload.content,
        target_employee_ids=payload.target_employee_ids,
        routing_mode=payload.routing_mode,
        context_document_ids=payload.context_document_ids,
        context_conversation_ids=payload.context_conversation_ids,
        attachment_ids=payload.attachment_ids,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.send",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={
            "routing_mode": payload.routing_mode,
            "replies": len(result["replies"]),
            "targets": payload.target_employee_ids,
            "context_documents": payload.context_document_ids,
            "context_conversations": payload.context_conversation_ids,
        },
        ip_address=client_ip(request),
    )
    return success(result)


@router.post("/{conversation_id}/messages/stream", summary="流式发送消息（SSE）")
async def stream_message_endpoint(
    conversation_id: int,
    payload: ChatSendRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )

    async def event_generator():
        try:
            async for event in stream_message(
                db,
                conversation,
                payload.content,
                target_employee_ids=payload.target_employee_ids,
                routing_mode=payload.routing_mode,
                context_document_ids=payload.context_document_ids,
                context_conversation_ids=payload.context_conversation_ids,
                attachment_ids=payload.attachment_ids,
                user_id=current_user.id,
            ):
                yield (
                    "data: "
                    + json.dumps(event, ensure_ascii=False, default=str)
                    + "\n\n"
                )
        except AppError as exc:
            yield (
                "data: "
                + json.dumps(
                    {"type": "error", "message": exc.message},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
        except Exception:  # noqa: BLE001
            logger.exception("流式对话失败")
            yield (
                "data: "
                + json.dumps(
                    {"type": "error", "message": "流式生成失败，请重试"},
                    ensure_ascii=False,
                )
                + "\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{conversation_id}/tasks", summary="把对话内容创建为任务")
async def create_task_endpoint(
    conversation_id: int,
    payload: ChatTaskCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    result = await create_task_from_conversation(
        db,
        conversation,
        payload.content,
        employee_id=payload.employee_id,
        context_document_ids=payload.context_document_ids,
        context_conversation_ids=payload.context_conversation_ids,
        attachment_ids=payload.attachment_ids,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=result["task"]["employee_id"],
        action="conversation.task.create",
        resource_type="task_instance",
        resource_id=result["task"]["id"],
        detail={
            "conversation_id": conversation.id,
            "title": result["task"]["title"],
        },
        ip_address=client_ip(request),
        trace_id=result["task"].get("trace_id"),
    )
    await db.commit()
    if settings.use_celery:
        enqueue_task(result["task"]["id"], 0)
    return success(result)


@router.post(
    "/{conversation_id}/tool-decisions", summary="逐条批准或拒绝待确认工具"
)
async def decide_tools_endpoint(
    conversation_id: int,
    payload: ToolDecisionRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    result = await decide_pending_tools(
        db,
        conversation,
        payload.message_id,
        [item.model_dump() for item in payload.decisions],
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.tool_decision",
        resource_type="chat_message",
        resource_id=payload.message_id,
        detail={
            "conversation_id": conversation.id,
            "decisions": [item.model_dump() for item in payload.decisions],
            "remaining": len(result["remaining"]),
        },
        ip_address=client_ip(request),
    )
    return success(result)


@router.post("/{conversation_id}/members", summary="添加群聊成员")
async def add_member_endpoint(
    conversation_id: int,
    payload: ConversationMemberAdd,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    await add_member(
        db,
        conversation,
        payload.employee_id,
        role=payload.role,
        user_id=current_user.id,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=payload.employee_id,
        action="conversation.member.add",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={"employee_id": payload.employee_id},
        ip_address=client_ip(request),
    )
    return success(await conversation_detail(db, conversation))


@router.delete(
    "/{conversation_id}/members/{employee_id}", summary="移除群聊成员"
)
async def remove_member_endpoint(
    conversation_id: int,
    employee_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    await remove_member(db, conversation, employee_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        employee_id=employee_id,
        action="conversation.member.remove",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={"employee_id": employee_id},
        ip_address=client_ip(request),
    )
    return success(await conversation_detail(db, conversation))


@router.post("/{conversation_id}/archive", summary="归档会话")
async def archive_conversation_endpoint(
    conversation_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    await archive_conversation(db, conversation)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.archive",
        resource_type="conversation",
        resource_id=conversation.id,
        ip_address=client_ip(request),
    )
    return success(None, "会话已归档")


@router.post("/{conversation_id}/attachments", summary="上传对话附件")
async def upload_attachment_endpoint(
    conversation_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    conversation = await get_conversation(
        db, current_user.tenant_id, conversation_id
    )
    if conversation.status != "active":
        raise BadRequestError("会话已归档，不能上传附件")

    file_name = (file.filename or "attachment").strip()[:255]
    extension = safe_extension(file_name)
    if not extension:
        raise BadRequestError(
            "不支持的附件类型；支持 txt/md/csv/json/log/yaml、pdf、docx、xlsx 与常见图片"
        )
    limit = settings.chat_attachment_max_bytes
    data = await file.read(limit + 1)
    if not data:
        raise BadRequestError("附件为空")
    if len(data) > limit:
        raise BadRequestError(
            f"附件超过大小限制（{limit // (1024 * 1024)}MB）"
        )

    mime_type = (
        file.content_type
        or mimetypes.guess_type(file_name)[0]
        or "application/octet-stream"
    )
    storage_path = save_attachment(
        current_user.tenant_id, conversation.id, data, extension
    )
    attachment = ChatAttachment(
        tenant_id=current_user.tenant_id,
        conversation_id=conversation.id,
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=len(data),
        storage_path=storage_path,
        text_excerpt=extract_text(data, extension),
        uploaded_by=current_user.id,
    )
    db.add(attachment)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.attachment.upload",
        resource_type="chat_attachment",
        resource_id=attachment.id,
        detail={
            "conversation_id": conversation.id,
            "file_name": attachment.file_name,
            "size_bytes": attachment.size_bytes,
        },
        ip_address=client_ip(request),
    )
    return success(_attachment_out(attachment))


@router.get(
    "/attachments/{attachment_id}/download", summary="下载对话附件"
)
async def download_attachment_endpoint(
    attachment_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    attachment = await db.scalar(
        select(ChatAttachment).where(
            ChatAttachment.id == attachment_id,
            ChatAttachment.tenant_id == current_user.tenant_id,
        )
    )
    if attachment is None:
        raise NotFoundError("附件不存在")
    path = resolve_attachment(attachment.storage_path)
    if path is None:
        raise NotFoundError("附件文件不存在")
    return FileResponse(
        path,
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.file_name,
    )


@router.delete(
    "/attachments/{attachment_id}", summary="删除尚未发送的对话附件"
)
async def delete_attachment_endpoint(
    attachment_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    attachment = await db.scalar(
        select(ChatAttachment).where(
            ChatAttachment.id == attachment_id,
            ChatAttachment.tenant_id == current_user.tenant_id,
        )
    )
    if attachment is None:
        raise NotFoundError("附件不存在")
    if attachment.message_id is not None:
        raise BadRequestError("已发送的附件不能删除")
    storage_path = attachment.storage_path
    await db.delete(attachment)
    await db.flush()
    delete_attachment(storage_path)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="conversation.attachment.delete",
        resource_type="chat_attachment",
        resource_id=attachment_id,
        detail={"conversation_id": attachment.conversation_id},
        ip_address=client_ip(request),
    )
    return success(None, "附件已删除")
