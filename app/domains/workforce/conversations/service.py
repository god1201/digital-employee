"""数字员工对话：直接对话、群聊、工具调用、契约门禁与 Token 计量。"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.llm import (
    LLMError,
    chat_with_tools,
    chat_with_tools_stream,
    is_configured,
)
from app.domains.governance.audit.service import record_audit
from app.domains.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.domains.skills.agents.models import Agent
from app.domains.skills.agents.runner import AgentError, invoke_agent
from app.domains.skills.marketplace.service import installed_rows
from app.domains.skills.tools.executor import execute_tool
from app.domains.skills.tools.models import Tool
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workflows.tasks.schemas import TaskInstanceOut
from app.domains.workforce.contracts.service import (
    evaluate_tool_call,
    get_active_contract,
)
from app.domains.workforce.conversations.models import (
    ChatAttachment,
    ChatMessage,
    Conversation,
    ConversationMember,
)
from app.domains.workforce.conversations.schemas import (
    ChatMessageOut,
    ConversationCreate,
)
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.service import get_agent
from app.domains.workforce.projects.service import get_project
from app.domains.workforce.prompting import build_employee_prompt
from app.domains.workforce.routing import score_contact

CONFIRM_WORDS = ("确认", "批准", "同意", "执行", "可以", "好的")
CHAT_RULES = (
    "你正在与管理员对话。你可以调用工具完成任务；调用工具前必须遵守岗位契约，"
    "触碰红线的请求要拒绝并说明原因，需要请示的事项要明确要求人工确认。"
    "回答简洁、可执行，不要编造工具结果。"
)
GROUP_RULES = "你正在多员工群聊中，只以你自己的身份回复，不要替其他员工发言。"


def _tool_specs(tools: list[Tool]) -> tuple[list[dict], dict[str, Tool]]:
    specs: list[dict] = []
    mapping: dict[str, Tool] = {}
    used: set[str] = set()
    for tool in tools:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.code) or f"tool_{tool.id}"
        if name in used:
            name = f"{name}_{tool.id}"
        used.add(name)
        mapping[name] = tool
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description or tool.name,
                    "parameters": tool.parameters_schema
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return specs, mapping


def _virtual_agent(employee: DigitalEmployee) -> SimpleNamespace:
    return SimpleNamespace(
        id=0,
        tenant_id=employee.tenant_id,
        name=employee.name,
        code=f"employee_{employee.id}",
        agent_type="internal",
        protocol="builtin",
        model_provider=employee.model_provider,
        model_name=employee.model_name,
        system_prompt=employee.system_prompt,
        tools=[],
        capabilities=[],
        config={},
        status="active",
        endpoint_url=None,
        headers={},
    )


async def effective_agent(
    db: AsyncSession, employee: DigitalEmployee
) -> Agent | SimpleNamespace:
    agent = await get_agent(db, employee.tenant_id, employee.agent_id)
    if agent is not None and agent.status == "active":
        return agent
    return _virtual_agent(employee)


async def get_conversation(
    db: AsyncSession, tenant_id: int, conversation_id: int
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conversation is None:
        raise NotFoundError("会话不存在")
    return conversation


async def conversation_members(
    db: AsyncSession, conversation: Conversation
) -> list[DigitalEmployee]:
    rows = await db.scalars(
        select(DigitalEmployee)
        .join(
            ConversationMember,
            ConversationMember.employee_id == DigitalEmployee.id,
        )
        .where(ConversationMember.conversation_id == conversation.id)
        .order_by(ConversationMember.id)
    )
    return list(rows.all())


async def _require_member(
    db: AsyncSession, conversation: Conversation, employee_id: int
) -> DigitalEmployee:
    employee = await db.scalar(
        select(DigitalEmployee)
        .join(
            ConversationMember,
            ConversationMember.employee_id == DigitalEmployee.id,
        )
        .where(
            ConversationMember.conversation_id == conversation.id,
            ConversationMember.employee_id == employee_id,
        )
    )
    if employee is None:
        raise ForbiddenError("该员工不在会话中")
    return employee


async def create_conversation(
    db: AsyncSession,
    tenant_id: int,
    payload: ConversationCreate,
    *,
    user_id: int | None = None,
) -> tuple[Conversation, list[DigitalEmployee]]:
    if payload.project_id is not None:
        await get_project(db, tenant_id, payload.project_id)

    if payload.mode == "direct":
        if payload.employee_id is None:
            raise BadRequestError("直接对话需要 employee_id")
        employee = await _require_employee(db, tenant_id, payload.employee_id)
        existing = await db.scalar(
            select(Conversation)
            .join(
                ConversationMember,
                ConversationMember.conversation_id == Conversation.id,
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.mode == "direct",
                Conversation.status == "active",
                ConversationMember.employee_id == employee.id,
            )
            .order_by(Conversation.id.desc())
            .limit(1)
        )
        if existing is not None:
            return existing, [employee]
        conversation = Conversation(
            tenant_id=tenant_id,
            mode="direct",
            title=f"与 {employee.name} 对话",
            status="active",
            project_id=payload.project_id,
            created_by=user_id,
        )
        db.add(conversation)
        await db.flush()
        db.add(
            ConversationMember(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                employee_id=employee.id,
                role="owner",
                created_by=user_id,
            )
        )
        await db.flush()
        return conversation, [employee]

    employee_ids = []
    for item in payload.employee_ids:
        if item not in employee_ids:
            employee_ids.append(item)
    if len(employee_ids) < 2:
        raise BadRequestError("群聊至少需要 2 个数字员工")
    employees = [
        await _require_employee(db, tenant_id, employee_id)
        for employee_id in employee_ids
    ]
    title = payload.title.strip() or "群聊 · " + "、".join(
        employee.name for employee in employees[:4]
    )
    conversation = Conversation(
        tenant_id=tenant_id,
        mode="group",
        title=title[:128],
        status="active",
        project_id=payload.project_id,
        created_by=user_id,
    )
    db.add(conversation)
    await db.flush()
    for index, employee in enumerate(employees):
        db.add(
            ConversationMember(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                employee_id=employee.id,
                role="owner" if index == 0 else "member",
                created_by=user_id,
            )
        )
    await db.flush()
    return conversation, employees


async def list_conversations(
    db: AsyncSession,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    mode: str | None = None,
    limit: int = 100,
) -> list[dict]:
    conditions = [
        Conversation.tenant_id == tenant_id,
        Conversation.status == "active",
    ]
    if mode:
        conditions.append(Conversation.mode == mode)
    stmt = select(Conversation).where(*conditions)
    if employee_id is not None:
        stmt = stmt.join(
            ConversationMember,
            ConversationMember.conversation_id == Conversation.id,
        ).where(ConversationMember.employee_id == employee_id)
    conversations = list(
        (
            await db.scalars(
                stmt.order_by(
                    func.coalesce(
                        Conversation.last_message_at, Conversation.created_at
                    ).desc()
                ).limit(limit)
            )
        ).all()
    )
    result = []
    for conversation in conversations:
        members = await conversation_members(db, conversation)
        last = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        result.append(
            {
                "id": conversation.id,
                "mode": conversation.mode,
                "title": conversation.title,
                "status": conversation.status,
                "project_id": conversation.project_id,
                "last_message_at": conversation.last_message_at.isoformat()
                if conversation.last_message_at
                else None,
                "member_names": [employee.name for employee in members],
                "last_message": (last.content or "")[:160] if last else "",
            }
        )
    return result


async def conversation_detail(
    db: AsyncSession, conversation: Conversation
) -> dict:
    members = await conversation_members(db, conversation)
    agents = {}
    for employee in members:
        agents[employee.id] = await effective_agent(db, employee)
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.id.desc())
                .limit(100)
            )
        ).all()
    )
    messages.reverse()
    return {
        "conversation": {
            "id": conversation.id,
            "mode": conversation.mode,
            "title": conversation.title,
            "status": conversation.status,
            "project_id": conversation.project_id,
            "last_message_at": conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else None,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        },
        "members": [
            {
                "employee_id": employee.id,
                "name": employee.name,
                "position": employee.position,
                "agent_id": employee.agent_id,
                "agent_name": agents[employee.id].name,
                "agent_code": agents[employee.id].code,
                "status": employee.status,
            }
            for employee in members
        ],
        "messages": [
            ChatMessageOut.model_validate(message).model_dump(mode="json")
            for message in messages
        ],
    }


async def archive_conversation(
    db: AsyncSession, conversation: Conversation
) -> None:
    conversation.status = "archived"
    await db.flush()


async def add_member(
    db: AsyncSession,
    conversation: Conversation,
    employee_id: int,
    *,
    role: str = "member",
    user_id: int | None = None,
) -> None:
    if conversation.mode == "direct":
        raise BadRequestError("直接对话不能添加成员")
    await _require_employee(db, conversation.tenant_id, employee_id)
    exists = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation.id,
            ConversationMember.employee_id == employee_id,
        )
    )
    if exists is not None:
        exists.role = role
    else:
        db.add(
            ConversationMember(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                employee_id=employee_id,
                role=role,
                created_by=user_id,
            )
        )
    await db.flush()


async def remove_member(
    db: AsyncSession, conversation: Conversation, employee_id: int
) -> None:
    member = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation.id,
            ConversationMember.employee_id == employee_id,
        )
    )
    if member is None:
        raise NotFoundError("会话成员不存在")
    await db.delete(member)
    await db.flush()


async def _require_employee(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> DigitalEmployee:
    employee = await db.scalar(
        select(DigitalEmployee).where(
            DigitalEmployee.id == employee_id,
            DigitalEmployee.tenant_id == tenant_id,
        )
    )
    if employee is None:
        raise BadRequestError("数字员工不存在")
    return employee


async def _load_tools(
    db: AsyncSession,
    tenant_id: int,
    employee: DigitalEmployee,
    agent: Agent | SimpleNamespace,
) -> list[Tool]:
    codes = {str(item) for item in (agent.tools or []) if item}
    rows = await installed_rows(db, tenant_id, employee.id)
    for skill, package in rows:
        if skill.status != "active":
            continue
        codes.update(str(item) for item in (package.tool_codes or []) if item)
    if not codes:
        return []
    return list(
        (
            await db.scalars(
                select(Tool).where(
                    Tool.tenant_id == tenant_id,
                    Tool.code.in_(codes),
                    Tool.enabled.is_(True),
                )
            )
        ).all()
    )


async def _history(
    db: AsyncSession,
    conversation: Conversation,
    employee: DigitalEmployee,
    member_names: dict[int, str],
    *,
    limit: int = 20,
) -> list[dict]:
    rows = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.role.in_(["user", "assistant"]),
                )
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            )
        ).all()
    )
    rows.reverse()
    messages: list[dict] = []
    for row in rows:
        content = row.content or ""
        if row.role == "assistant" and conversation.mode == "group":
            name = member_names.get(row.employee_id or 0, "员工")
            content = f"[{name}] {content}"
        messages.append({"role": row.role, "content": content})
    return messages


async def _route_members(
    db: AsyncSession,
    tenant_id: int,
    members: list[DigitalEmployee],
    content: str,
) -> list[DigitalEmployee]:
    if len(members) <= 1:
        return members
    scored: list[tuple[int, DigitalEmployee]] = []
    for employee in members:
        agent = await effective_agent(db, employee)
        skill_names = [
            package.name
            for skill, package in await installed_rows(db, tenant_id, employee.id)
            if skill.status == "active"
        ]
        text = " ".join(
            [
                employee.name or "",
                employee.position or "",
                employee.description or "",
                agent.name or "",
                *[str(item) for item in (agent.capabilities or [])],
                *skill_names,
            ]
        )
        scored.append((score_contact(content, text), employee))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    if not scored or scored[0][0] <= 0:
        return members
    return [scored[0][1]]


async def _execute_pending(
    db: AsyncSession,
    tenant_id: int,
    employee: DigitalEmployee,
    pending: list[dict],
) -> list[dict]:
    contract = await get_active_contract(db, tenant_id, employee.id)
    results: list[dict] = []
    for item in pending:
        tool_code = str(item.get("tool") or "")
        arguments = item.get("arguments") or {}
        tool = await db.scalar(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.code == tool_code,
                Tool.enabled.is_(True),
            )
        )
        if tool is None:
            results.append(
                {"tool": tool_code, "success": False, "error": "工具不存在或已停用"}
            )
            continue
        decision = evaluate_tool_call(
            contract,
            tool=tool,
            arguments=arguments,
            step_name="聊天确认执行",
        )
        if decision.action == "deny":
            results.append(
                {
                    "tool": tool_code,
                    "success": False,
                    "decision": "deny",
                    "error": decision.reason,
                }
            )
            continue
        # allow 直接执行；ask 已经获得用户下一条消息的明确确认，可以执行。
        result = await execute_tool(
            db,
            tenant_id=tenant_id,
            employee_id=employee.id,
            tool=tool,
            arguments=arguments,
        )
        results.append(
            {
                "tool": tool_code,
                "success": result.success,
                "output": result.output if result.success else None,
                "error": result.error if not result.success else None,
                "latency_ms": result.latency_ms,
                "decision": "allow",
            }
        )
    return results


async def decide_pending_tools(
    db: AsyncSession,
    conversation: Conversation,
    message_id: int,
    decisions: list[dict],
    *,
    user_id: int | None = None,
) -> dict:
    """对某条员工回复中的待确认工具逐一批准或拒绝。

    decisions: [{"index": int, "approved": bool}]；未出现在 decisions 中的
    待确认工具会保留，等待后续审批。
    """
    message = await db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.tenant_id == conversation.tenant_id,
            ChatMessage.role == "assistant",
        )
    )
    if message is None:
        raise NotFoundError("待审批消息不存在")

    metadata = dict(message.message_metadata or {})
    pending = list(metadata.get("pending_tools") or [])
    if not pending:
        raise BadRequestError("该消息没有待确认工具")

    employee = (
        await db.get(DigitalEmployee, message.employee_id)
        if message.employee_id
        else None
    )
    if employee is None:
        raise BadRequestError("无法确定待审批员工")

    contract = await get_active_contract(
        db, conversation.tenant_id, employee.id
    )
    # 先整体校验，避免部分工具已执行后才因越界索引报错。
    normalized: list[tuple[int, bool]] = []
    decided: set[int] = set()
    for decision in decisions:
        index = int(decision.get("index", -1))
        if index < 0 or index >= len(pending):
            raise BadRequestError(f"待确认工具索引越界: {index}")
        if index in decided:
            continue
        decided.add(index)
        normalized.append((index, bool(decision.get("approved"))))
    if not normalized:
        raise BadRequestError("没有有效的审批决定")

    results: list[dict] = []
    for index, approved in normalized:
        item = pending[index]
        tool_code = str(item.get("tool") or "")
        arguments = item.get("arguments") or {}
        if not approved:
            results.append(
                {
                    "tool": tool_code,
                    "arguments": arguments,
                    "success": False,
                    "decision": "rejected",
                    "error": "用户拒绝执行",
                }
            )
            continue

        tool = await db.scalar(
            select(Tool).where(
                Tool.tenant_id == conversation.tenant_id,
                Tool.code == tool_code,
                Tool.enabled.is_(True),
            )
        )
        if tool is None:
            results.append(
                {
                    "tool": tool_code,
                    "arguments": arguments,
                    "success": False,
                    "decision": "error",
                    "error": "工具不存在或已停用",
                }
            )
            continue

        verdict = evaluate_tool_call(
            contract,
            tool=tool,
            arguments=arguments,
            step_name="聊天审批执行",
        )
        if verdict.action == "deny":
            results.append(
                {
                    "tool": tool_code,
                    "arguments": arguments,
                    "success": False,
                    "decision": "deny",
                    "error": verdict.reason,
                }
            )
            continue

        executed = await execute_tool(
            db,
            tenant_id=conversation.tenant_id,
            employee_id=employee.id,
            tool=tool,
            arguments=arguments,
        )
        results.append(
            {
                "tool": tool_code,
                "arguments": arguments,
                "success": executed.success,
                "output": executed.output if executed.success else None,
                "error": None if executed.success else (executed.error or "工具执行失败"),
                "latency_ms": executed.latency_ms,
                "decision": "confirmed",
            }
        )

    remaining = [
        item for index, item in enumerate(pending) if index not in decided
    ]
    message.message_metadata = {**metadata, "pending_tools": remaining}

    labels = {
        "confirmed": "已执行",
        "rejected": "已拒绝",
        "deny": "红线拦截",
        "error": "执行失败",
    }
    lines = [
        f"- {result['tool']}：{labels.get(result['decision'], '已处理')}"
        + (f"（{result['error']}）" if result.get("error") else "")
        for result in results
    ]
    reply = ChatMessage(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        employee_id=employee.id,
        role="assistant",
        content="工具审批结果：\n" + "\n".join(lines),
        tool_calls=results,
        tokens=0,
        cost=0.0,
        status="sent",
        message_metadata={
            "kind": "tool_decision",
            "source_message_id": message.id,
            "results": results,
        },
        created_by=user_id,
    )
    db.add(reply)
    conversation.last_message_at = utcnow()
    await db.flush()
    return {
        "message": ChatMessageOut.model_validate(reply).model_dump(mode="json"),
        "remaining": remaining,
        "results": results,
    }


async def _persist_message(
    db: AsyncSession,
    conversation: Conversation,
    employee: DigitalEmployee,
    agent: Agent | SimpleNamespace,
    content: str,
    tool_trace: list[dict],
    tokens: int,
    pending_tools: list[dict],
    confirmed_tools: list[dict],
    trace_id: str,
    *,
    user_id: int | None = None,
    model: str | None = None,
    status: str = "sent",
) -> ChatMessage:
    cost = round(tokens / 1000 * settings.llm_cost_per_1k_tokens, 6)
    message = ChatMessage(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        employee_id=employee.id,
        role="assistant",
        content=content,
        tool_calls=tool_trace,
        tokens=tokens,
        cost=cost,
        trace_id=trace_id,
        status=status,
        message_metadata={
            "model": model or agent.model_name or employee.model_name,
            "agent_id": agent.id,
            "agent_code": agent.code,
            "agent_type": getattr(agent, "agent_type", "internal"),
            "pending_tools": pending_tools,
            "confirmed_tools": confirmed_tools,
            "tool_count": len(tool_trace),
        },
        created_by=user_id,
    )
    db.add(message)
    await db.flush()
    await record_audit(
        db,
        tenant_id=conversation.tenant_id,
        user_id=user_id,
        employee_id=employee.id,
        action="conversation.message",
        resource_type="chat_message",
        resource_id=message.id,
        detail={
            "conversation_id": conversation.id,
            "tokens": tokens,
            "tool_calls": len(tool_trace),
            "trace_id": trace_id,
        },
        trace_id=trace_id,
    )
    return message


async def _build_context(
    db: AsyncSession,
    conversation: Conversation,
    document_ids: list[int] | None,
    conversation_ids: list[int] | None,
) -> tuple[str | None, dict]:
    """把 @文件 / @会话 转成附加系统上下文与可回显的元数据。"""
    doc_ids = list(dict.fromkeys(int(item) for item in (document_ids or []) if item))[
        :10
    ]
    conv_ids = [
        int(item)
        for item in dict.fromkeys(conversation_ids or [])
        if item and int(item) != conversation.id
    ][:5]

    parts: list[str] = []
    document_meta: list[dict] = []
    if doc_ids:
        rows = await db.execute(
            select(KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeBase, KnowledgeDocument.base_id == KnowledgeBase.id)
            .where(
                KnowledgeDocument.tenant_id == conversation.tenant_id,
                KnowledgeDocument.id.in_(doc_ids),
                KnowledgeDocument.status == "active",
            )
            .order_by(KnowledgeDocument.id)
        )
        for document, base in rows.all():
            document_meta.append(
                {
                    "id": document.id,
                    "title": document.title,
                    "base_id": base.id,
                    "base_name": base.name,
                }
            )
            content = (document.content or "").strip()
            if len(content) > 4000:
                content = content[:4000] + "…"
            parts.append(
                f"【文件：{document.title}（知识库：{base.name}）】\n{content}"
            )

    conversation_meta: list[dict] = []
    if conv_ids:
        conversations = list(
            (
                await db.scalars(
                    select(Conversation)
                    .where(
                        Conversation.tenant_id == conversation.tenant_id,
                        Conversation.id.in_(conv_ids),
                    )
                    .order_by(Conversation.id)
                )
            ).all()
        )
        for item in conversations:
            conversation_meta.append({"id": item.id, "title": item.title})
            messages = list(
                (
                    await db.scalars(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == item.id,
                            ChatMessage.role.in_(["user", "assistant"]),
                        )
                        .order_by(ChatMessage.id.desc())
                        .limit(12)
                    )
                ).all()
            )
            messages.reverse()
            lines = []
            for message in messages:
                who = "用户" if message.role == "user" else "员工"
                text = (message.content or "").strip()
                if len(text) > 500:
                    text = text[:500] + "…"
                lines.append(f"[{who}] {text}")
            parts.append(
                f"【会话：{item.title or f'#{item.id}'}】\n" + "\n".join(lines)
            )

    metadata = {
        "context_documents": document_meta,
        "context_conversations": conversation_meta,
    }
    if not parts:
        return None, metadata
    context = (
        "用户为本轮消息引用了以下上下文，请优先基于这些内容回答；"
        "不确定时明确说明：\n\n" + "\n\n".join(parts)
    )
    if len(context) > 20000:
        context = context[:20000] + "\n…（上下文已截断）"
    return context, metadata


async def _run_turn(
    db: AsyncSession,
    conversation: Conversation,
    employee: DigitalEmployee,
    agent: Agent | SimpleNamespace,
    content: str,
    member_names: dict[int, str],
    *,
    user_id: int | None = None,
    context_block: str | None = None,
    delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> ChatMessage:
    trace_id = uuid.uuid4().hex

    # 第三方 Agent 直接走它的 endpoint；本地只负责持久化与上下文拼接。
    if str(getattr(agent, "agent_type", "internal")) != "internal":
        history = await _history(db, conversation, employee, member_names)
        prompt_lines = [
            "用户" if item["role"] == "user" else "助手"
            for item in history
        ]
        prompt = "\n".join(
            f"{label}: {item['content']}"
            for label, item in zip(prompt_lines, history, strict=False)
        )
        if context_block:
            prompt = f"{context_block}\n\n{prompt}"
        try:
            result = await invoke_agent(
                db,
                agent,
                tenant_id=conversation.tenant_id,
                employee_id=employee.id,
                input_data={
                    "message": content,
                    "history": history,
                    "employee": {
                        "id": employee.id,
                        "name": employee.name,
                        "position": employee.position,
                    },
                },
                prompt=prompt or content,
            )
        except AgentError as exc:
            raise BadRequestError(str(exc)) from exc
        text = str(
            result.output.get("text")
            or json.dumps(result.output, ensure_ascii=False, default=str)
        )
        return await _persist_message(
            db,
            conversation,
            employee,
            agent,
            text,
            list(result.tool_calls or []),
            result.tokens,
            [],
            [],
            trace_id,
            user_id=user_id,
        )

    if not is_configured():
        raise BadRequestError("对话需要配置 LLM_API_KEY")

    tools = await _load_tools(db, conversation.tenant_id, employee, agent)
    specs, mapping = _tool_specs(tools)
    contract = await get_active_contract(db, conversation.tenant_id, employee.id)
    employee_prompt = await build_employee_prompt(
        db,
        conversation.tenant_id,
        employee,
        trace_id=trace_id,
    )
    system_parts = [agent.system_prompt or "", employee_prompt, CHAT_RULES]
    if conversation.mode == "group":
        system_parts.append(GROUP_RULES)
    messages: list[dict] = [
        {"role": "system", "content": "\n\n".join(part for part in system_parts if part)}
    ]
    if context_block:
        messages.append({"role": "system", "content": context_block})
    messages.extend(
        await _history(db, conversation, employee, member_names)
    )

    last_assistant = await db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.role == "assistant",
            ChatMessage.employee_id == employee.id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    pending_tools: list[dict] = []
    confirmed_tools: list[dict] = []
    if last_assistant is not None:
        previous_pending = (last_assistant.message_metadata or {}).get(
            "pending_tools"
        ) or []
        if previous_pending and any(word in content for word in CONFIRM_WORDS):
            pending_results = await _execute_pending(
                db, conversation.tenant_id, employee, previous_pending
            )
            confirmed_tools = pending_results
            messages.append(
                {
                    "role": "system",
                    "content": "用户已确认执行以下工具，结果如下：\n"
                    + json.dumps(pending_results, ensure_ascii=False, default=str),
                }
            )
            last_assistant.message_metadata = {
                **(last_assistant.message_metadata or {}),
                "pending_tools": [],
            }
            trace_id = uuid.uuid4().hex
        elif previous_pending:
            pending_tools = previous_pending

    config = agent.config or {}
    try:
        max_steps = int(config.get("max_steps") or 6)
    except (TypeError, ValueError):
        max_steps = 6
    max_steps = max(1, min(max_steps, 12))
    model = agent.model_name or employee.model_name or None
    total_tokens = 0
    tool_trace: list[dict] = [
        {**item, "decision": "confirmed"} for item in confirmed_tools
    ]
    final_content = ""

    for _ in range(max_steps):
        try:
            if delta_callback is not None:
                message, tokens = await chat_with_tools_stream(
                    messages,
                    specs,
                    model=model,
                    on_delta=delta_callback,
                )
            else:
                message, tokens = await chat_with_tools(
                    messages,
                    specs,
                    model=model,
                )
        except LLMError as exc:
            raise BadRequestError(str(exc)) from exc
        total_tokens += tokens
        content_text = message.get("content")
        final_content = content_text if isinstance(content_text, str) else ""
        tool_calls = message.get("tool_calls") or []
        assistant_message: dict = {
            "role": "assistant",
            "content": final_content,
        }
        if isinstance(tool_calls, list) and tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)
        if not isinstance(tool_calls, list) or not tool_calls:
            break

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or f"call_{len(tool_trace) + 1}")
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_arguments = function.get("arguments") or "{}"
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}

            tool = mapping.get(name)
            if tool is None:
                payload = {"error": f"未知工具: {name}"}
                tool_trace.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": False,
                        "error": "unknown tool",
                        "decision": "error",
                    }
                )
            else:
                decision = evaluate_tool_call(
                    contract,
                    tool=tool,
                    arguments=arguments,
                    step_name=f"聊天工具 {tool.name}",
                )
                if decision.action == "deny":
                    payload = {
                        "error": f"岗位契约拦截：{decision.reason}",
                        "decision": "deny",
                    }
                    tool_trace.append(
                        {
                            "tool": tool.code,
                            "arguments": arguments,
                            "success": False,
                            "error": decision.reason,
                            "decision": "deny",
                            "requires_confirmation": False,
                        }
                    )
                elif decision.action == "ask":
                    payload = {
                        "error": f"需要人工确认：{decision.reason}",
                        "decision": "ask",
                    }
                    tool_trace.append(
                        {
                            "tool": tool.code,
                            "arguments": arguments,
                            "success": False,
                            "error": decision.reason,
                            "decision": "ask",
                            "requires_confirmation": True,
                        }
                    )
                    pending_tools.append(
                        {
                            "tool": tool.code,
                            "arguments": arguments,
                            "reason": decision.reason,
                        }
                    )
                else:
                    result = await execute_tool(
                        db,
                        tenant_id=conversation.tenant_id,
                        employee_id=employee.id,
                        tool=tool,
                        arguments=arguments,
                    )
                    payload = (
                        result.output
                        if result.success
                        else {"error": result.error or "工具执行失败"}
                    )
                    tool_trace.append(
                        {
                            "tool": tool.code,
                            "arguments": arguments,
                            "success": result.success,
                            "output": result.output if result.success else None,
                            "error": result.error if not result.success else None,
                            "latency_ms": result.latency_ms,
                            "decision": "allow",
                            "requires_confirmation": False,
                        }
                    )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )
    if not final_content and tool_trace:
        final_content = "（已达到最大工具调用步数，请缩小任务范围后重试）"
    if not final_content and pending_tools:
        final_content = "该操作需要你确认后才能执行，请回复“确认”继续。"

    return await _persist_message(
        db,
        conversation,
        employee,
        agent,
        final_content,
        tool_trace,
        total_tokens,
        pending_tools,
        confirmed_tools,
        trace_id,
        user_id=user_id,
        model=model,
    )


async def _load_attachments(
    db: AsyncSession,
    conversation: Conversation,
    attachment_ids: list[int] | None,
) -> list[ChatAttachment]:
    ids = [
        int(item) for item in dict.fromkeys(attachment_ids or []) if item
    ][:10]
    if not ids:
        return []
    rows = await db.scalars(
        select(ChatAttachment)
        .where(
            ChatAttachment.tenant_id == conversation.tenant_id,
            ChatAttachment.conversation_id == conversation.id,
            ChatAttachment.id.in_(ids),
        )
        .order_by(ChatAttachment.id)
    )
    return list(rows.all())


def _attachment_context(attachments: list[ChatAttachment]) -> str | None:
    parts = [
        f"【附件：{item.file_name}】\n{item.text_excerpt}"
        for item in attachments
        if item.text_excerpt
    ]
    return "\n\n".join(parts) if parts else None


def _attachment_meta(attachments: list[ChatAttachment]) -> list[dict]:
    return [
        {
            "id": item.id,
            "file_name": item.file_name,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "has_text": bool(item.text_excerpt),
        }
        for item in attachments
    ]


async def send_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    target_employee_ids: list[int] | None = None,
    routing_mode: str = "auto",
    context_document_ids: list[int] | None = None,
    context_conversation_ids: list[int] | None = None,
    attachment_ids: list[int] | None = None,
    user_id: int | None = None,
) -> dict:
    if conversation.status != "active":
        raise BadRequestError("会话已归档")
    members = await conversation_members(db, conversation)
    if not members:
        raise BadRequestError("会话没有数字员工成员")
    member_names = {employee.id: employee.name for employee in members}
    context_block, context_meta = await _build_context(
        db, conversation, context_document_ids, context_conversation_ids
    )
    attachments = await _load_attachments(db, conversation, attachment_ids)
    attachment_block = _attachment_context(attachments)
    if attachment_block:
        context_block = (
            f"{context_block}\n\n{attachment_block}"
            if context_block
            else attachment_block
        )
    context_meta["attachments"] = _attachment_meta(attachments)

    user_message = ChatMessage(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        employee_id=None,
        role="user",
        content=content,
        tool_calls=[],
        tokens=0,
        cost=0.0,
        status="sent",
        message_metadata=context_meta,
        created_by=user_id,
    )
    db.add(user_message)
    await db.flush()
    for attachment in attachments:
        attachment.message_id = user_message.id
    await db.flush()

    if conversation.mode == "direct":
        responders = members[:1]
    elif routing_mode == "explicit":
        requested = set(target_employee_ids or [])
        responders = [employee for employee in members if employee.id in requested]
        if not responders:
            raise BadRequestError("指定回复员工不在会话中")
    elif routing_mode == "all":
        responders = members
    else:
        responders = await _route_members(
            db, conversation.tenant_id, members, content
        )

    replies: list[ChatMessage] = []
    for employee in responders:
        agent = await effective_agent(db, employee)
        reply = await _run_turn(
            db,
            conversation,
            employee,
            agent,
            content,
            member_names,
            user_id=user_id,
            context_block=context_block,
        )
        replies.append(reply)

    conversation.last_message_at = utcnow()
    await db.flush()
    return {
        "conversation_id": conversation.id,
        "user_message": ChatMessageOut.model_validate(user_message).model_dump(
            mode="json"
        ),
        "replies": [
            ChatMessageOut.model_validate(reply).model_dump(mode="json")
            for reply in replies
        ],
    }


async def stream_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    target_employee_ids: list[int] | None = None,
    routing_mode: str = "auto",
    context_document_ids: list[int] | None = None,
    context_conversation_ids: list[int] | None = None,
    attachment_ids: list[int] | None = None,
    user_id: int | None = None,
    commit: bool = True,
) -> AsyncIterator[dict]:
    """SSE 流式对话：先落库用户消息，再逐员工推送 content 增量。"""
    if conversation.status != "active":
        raise BadRequestError("会话已归档")

    async def persist() -> None:
        if commit:
            await db.commit()
        else:
            await db.flush()

    members = await conversation_members(db, conversation)
    if not members:
        raise BadRequestError("会话没有数字员工成员")
    member_names = {employee.id: employee.name for employee in members}

    if conversation.mode == "direct":
        responders = members[:1]
    elif routing_mode == "explicit":
        requested = set(target_employee_ids or [])
        responders = [employee for employee in members if employee.id in requested]
        if not responders:
            raise BadRequestError("指定回复员工不在会话中")
    elif routing_mode == "all":
        responders = members
    else:
        responders = await _route_members(
            db, conversation.tenant_id, members, content
        )

    context_block, context_meta = await _build_context(
        db, conversation, context_document_ids, context_conversation_ids
    )
    attachments = await _load_attachments(db, conversation, attachment_ids)
    attachment_block = _attachment_context(attachments)
    if attachment_block:
        context_block = (
            f"{context_block}\n\n{attachment_block}"
            if context_block
            else attachment_block
        )
    context_meta["attachments"] = _attachment_meta(attachments)

    user_message = ChatMessage(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        employee_id=None,
        role="user",
        content=content,
        tool_calls=[],
        tokens=0,
        cost=0.0,
        status="sent",
        message_metadata=context_meta,
        created_by=user_id,
    )
    db.add(user_message)
    await db.flush()
    for attachment in attachments:
        attachment.message_id = user_message.id
    conversation.last_message_at = utcnow()
    await record_audit(
        db,
        tenant_id=conversation.tenant_id,
        user_id=user_id,
        action="conversation.send_stream",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={
            "routing_mode": routing_mode,
            "targets": target_employee_ids or [],
            "context_documents": context_document_ids or [],
            "context_conversations": context_conversation_ids or [],
            "attachments": [item.id for item in attachments],
        },
    )
    await persist()
    yield {
        "type": "user_message",
        "message": ChatMessageOut.model_validate(user_message).model_dump(
            mode="json"
        ),
    }

    for employee in responders:
        agent = await effective_agent(db, employee)
        yield {
            "type": "reply_start",
            "employee_id": employee.id,
            "employee_name": employee.name,
        }
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        partial: list[str] = []
        completed = False

        async def on_delta(
            text: str,
            _partial: list[str] = partial,
            _queue: asyncio.Queue[str | None] = queue,
        ) -> None:
            _partial.append(text)
            await _queue.put(text)

        async def runner(
            _employee: DigitalEmployee = employee,
            _agent: Agent | SimpleNamespace = agent,
            _queue: asyncio.Queue[str | None] = queue,
        ) -> ChatMessage:
            try:
                return await _run_turn(
                    db,
                    conversation,
                    _employee,
                    _agent,
                    content,
                    member_names,
                    user_id=user_id,
                    context_block=context_block,
                    delta_callback=on_delta,
                )
            finally:
                await _queue.put(None)

        task = asyncio.create_task(runner())

        async def save_partial(
            _partial: list[str] = partial,
            _employee: DigitalEmployee = employee,
            _agent: Agent | SimpleNamespace = agent,
        ) -> None:
            text = "".join(_partial).strip()
            if not text:
                return
            message = ChatMessage(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                employee_id=_employee.id,
                role="assistant",
                content=text,
                tool_calls=[],
                tokens=0,
                cost=0.0,
                status="cancelled",
                message_metadata={
                    "model": _agent.model_name or _employee.model_name,
                    "cancelled": True,
                },
                created_by=user_id,
            )
            db.add(message)
            conversation.last_message_at = utcnow()
            await db.flush()
            await persist()

        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield {
                    "type": "delta",
                    "employee_id": employee.id,
                    "content": chunk,
                }
            reply = await task
            completed = True
            conversation.last_message_at = utcnow()
            await persist()
        except asyncio.CancelledError:
            task.cancel()
            if not completed:
                try:
                    await asyncio.shield(save_partial())
                except Exception:  # noqa: BLE001 - 客户端已断开，尽力保存
                    pass
            raise
        except Exception as exc:  # noqa: BLE001 - 单个员工失败不中断其他人
            if not completed:
                try:
                    await asyncio.shield(save_partial())
                except Exception:  # noqa: BLE001
                    pass
            yield {
                "type": "error",
                "employee_id": employee.id,
                "message": str(exc),
            }
            continue

        yield {
            "type": "reply_done",
            "message": ChatMessageOut.model_validate(reply).model_dump(mode="json"),
        }

    yield {"type": "done", "conversation_id": conversation.id}


async def create_task_from_conversation(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    employee_id: int | None = None,
    context_document_ids: list[int] | None = None,
    context_conversation_ids: list[int] | None = None,
    attachment_ids: list[int] | None = None,
    user_id: int | None = None,
) -> dict:
    """把对话中的一条指令直接创建为任务，并留下可回看的消息记录。"""
    if conversation.status != "active":
        raise BadRequestError("会话已归档")
    members = await conversation_members(db, conversation)
    if not members:
        raise BadRequestError("会话没有数字员工成员")

    if employee_id is None:
        if len(members) > 1:
            raise BadRequestError("群聊创建任务需要指定执行员工")
        employee = members[0]
    else:
        employee = next(
            (member for member in members if member.id == employee_id), None
        )
        if employee is None:
            raise BadRequestError("指定员工不在会话中")

    title = next(
        (line.strip() for line in content.splitlines() if line.strip()),
        "对话任务",
    )[:255]
    context_block, context_meta = await _build_context(
        db, conversation, context_document_ids, context_conversation_ids
    )
    attachments = await _load_attachments(db, conversation, attachment_ids)
    attachment_block = _attachment_context(attachments)
    if attachment_block:
        context_block = (
            f"{context_block}\n\n{attachment_block}"
            if context_block
            else attachment_block
        )
    context_meta["attachments"] = _attachment_meta(attachments)
    task_input = {
        "instruction": content,
        "conversation_id": conversation.id,
    }
    if context_block:
        task_input["context"] = context_block
    trace_id = uuid.uuid4().hex
    instance = TaskInstance(
        tenant_id=conversation.tenant_id,
        employee_id=employee.id,
        project_id=conversation.project_id,
        title=title,
        task_type="free",
        status="pending",
        input=task_input,
        output={},
        plan=[],
        next_step_index=0,
        attempt=0,
        max_attempts=settings.task_max_attempts,
        priority=100,
        trace_id=trace_id,
        created_by=user_id,
    )
    db.add(instance)
    await db.flush()

    message = ChatMessage(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        employee_id=None,
        role="user",
        content=content,
        tool_calls=[],
        tokens=0,
        cost=0.0,
        status="sent",
        message_metadata={
            "kind": "task_created",
            "task_id": instance.id,
            "title": instance.title,
            "employee_id": employee.id,
            "employee_name": employee.name,
            **context_meta,
        },
        created_by=user_id,
    )
    db.add(message)
    await db.flush()
    for attachment in attachments:
        attachment.message_id = message.id
    conversation.last_message_at = utcnow()
    await db.flush()
    return {
        "task": TaskInstanceOut.model_validate(instance).model_dump(mode="json"),
        "message": ChatMessageOut.model_validate(message).model_dump(mode="json"),
    }
