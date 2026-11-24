"""员工工作台与 Token 明细：把任务步骤与对话消息统一成可解释的消耗事件。"""

import csv
import io
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.domains.workflows.tasks.models import TaskInstance, TaskStep
from app.domains.workforce.conversations.models import (
    ChatMessage,
    Conversation,
    ConversationMember,
)
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.service import get_agent, serialize_employee
from app.domains.workforce.projects.models import Project
from app.domains.workforce.projects.service import employee_projects


async def _task_sums(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    since,
) -> tuple[int, float]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(TaskStep.tokens), 0),
                func.coalesce(func.sum(TaskStep.cost), 0),
            )
            .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
            .where(
                TaskInstance.tenant_id == tenant_id,
                TaskInstance.employee_id == employee_id,
                TaskStep.created_at >= since,
            )
        )
    ).one()
    return int(row[0] or 0), float(row[1] or 0)


async def _chat_sums(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    since,
) -> tuple[int, float]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(ChatMessage.tokens), 0),
                func.coalesce(func.sum(ChatMessage.cost), 0),
            ).where(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.employee_id == employee_id,
                ChatMessage.created_at >= since,
            )
        )
    ).one()
    return int(row[0] or 0), float(row[1] or 0)


async def _collect_token_events(
    db: AsyncSession,
    employee: DigitalEmployee,
    start,
    *,
    task_limit: int,
    chat_limit: int,
) -> list[dict]:
    agent = await get_agent(db, employee.tenant_id, employee.agent_id)
    default_model = (
        (agent.model_name if agent else "") or employee.model_name or ""
    )
    events: list[dict] = []

    task_rows = await db.execute(
        select(TaskStep, TaskInstance, Project)
        .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
        .outerjoin(Project, TaskInstance.project_id == Project.id)
        .where(
            TaskInstance.tenant_id == employee.tenant_id,
            TaskInstance.employee_id == employee.id,
            TaskStep.created_at >= start,
        )
        .order_by(TaskStep.created_at.desc())
        .limit(task_limit)
    )
    for step, instance, project in task_rows:
        events.append(
            {
                "source": "task",
                "occurred_at": step.created_at.isoformat(),
                "employee_id": employee.id,
                "context_id": instance.id,
                "context_title": instance.title,
                "project_id": project.id if project else None,
                "project_name": project.name if project else None,
                "action": step.name,
                "action_type": step.step_type,
                "tool_code": step.tool_code,
                "model": default_model,
                "tokens": int(step.tokens or 0),
                "cost": round(float(step.cost or 0), 6),
                "trace_id": instance.trace_id,
            }
        )

    chat_rows = await db.execute(
        select(ChatMessage, Conversation, Project)
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .outerjoin(Project, Conversation.project_id == Project.id)
        .where(
            ChatMessage.tenant_id == employee.tenant_id,
            ChatMessage.employee_id == employee.id,
            ChatMessage.created_at >= start,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(chat_limit)
    )
    for message, conversation, project in chat_rows:
        tool_calls = message.tool_calls or []
        tool_code = None
        if tool_calls and isinstance(tool_calls[0], dict):
            tool_code = tool_calls[0].get("tool")
        metadata = message.message_metadata or {}
        events.append(
            {
                "source": "chat",
                "occurred_at": message.created_at.isoformat(),
                "employee_id": employee.id,
                "context_id": conversation.id,
                "context_title": conversation.title,
                "project_id": project.id if project else None,
                "project_name": project.name if project else None,
                "action": "对话回复",
                "action_type": "chat",
                "tool_code": tool_code,
                "model": metadata.get("model") or default_model,
                "tokens": int(message.tokens or 0),
                "cost": round(float(message.cost or 0), 6),
                "trace_id": message.trace_id,
            }
        )

    events.sort(key=lambda item: item["occurred_at"], reverse=True)
    return events


def _filter_events(
    events: list[dict],
    *,
    source: str | None = None,
    project_id: int | None = None,
    tool_code: str | None = None,
) -> list[dict]:
    filtered = events
    if source in {"task", "chat"}:
        filtered = [item for item in filtered if item["source"] == source]
    if project_id is not None:
        filtered = [
            item for item in filtered if item["project_id"] == project_id
        ]
    if tool_code:
        filtered = [
            item for item in filtered if item["tool_code"] == tool_code
        ]
    return filtered


def _aggregate_events(events: list[dict]) -> dict:
    by_day: dict[str, dict] = {}
    by_source: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    by_project: dict[str, int] = {}
    total_tokens = 0
    total_cost = 0.0
    for event in events:
        day = event["occurred_at"][:10]
        bucket = by_day.setdefault(day, {"date": day, "tokens": 0, "cost": 0.0})
        bucket["tokens"] += event["tokens"]
        bucket["cost"] = round(bucket["cost"] + event["cost"], 6)
        by_source[event["source"]] = (
            by_source.get(event["source"], 0) + event["tokens"]
        )
        if event["tool_code"]:
            by_tool[event["tool_code"]] = (
                by_tool.get(event["tool_code"], 0) + event["tokens"]
            )
        if event["project_name"]:
            by_project[event["project_name"]] = (
                by_project.get(event["project_name"], 0) + event["tokens"]
            )
        total_tokens += event["tokens"]
        total_cost += event["cost"]
    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "by_day": sorted(by_day.values(), key=lambda item: item["date"]),
        "by_source": by_source,
        "by_tool": dict(
            sorted(by_tool.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
        "by_project": by_project,
    }


async def token_usage(
    db: AsyncSession,
    employee: DigitalEmployee,
    *,
    days: int = 30,
    source: str | None = None,
    project_id: int | None = None,
    tool_code: str | None = None,
) -> dict:
    window = max(1, min(90, days))
    start = utcnow() - timedelta(days=window)
    all_events = await _collect_token_events(
        db, employee, start, task_limit=500, chat_limit=500
    )

    projects: dict[int, str] = {}
    for event in all_events:
        if event["project_id"] is not None:
            projects.setdefault(event["project_id"], event["project_name"] or "")
    project_options = sorted(
        ({"id": key, "name": value} for key, value in projects.items()),
        key=lambda item: item["name"],
    )
    tool_options = sorted(
        {event["tool_code"] for event in all_events if event["tool_code"]}
    )

    events = _filter_events(
        all_events,
        source=source,
        project_id=project_id,
        tool_code=tool_code,
    )
    aggregates = _aggregate_events(events)
    return {
        "employee_id": employee.id,
        "days": window,
        "filters": {
            "source": source or "all",
            "project_id": project_id,
            "tool_code": tool_code,
        },
        **aggregates,
        "project_options": project_options,
        "tool_options": tool_options,
        "filtered_total": len(events),
        "events": events[:300],
    }


def _csv_cell(value) -> str:
    """避免任务标题/员工名以 = + - @ 开头时被表格软件当作公式执行。"""
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


async def token_usage_csv(
    db: AsyncSession,
    employee: DigitalEmployee,
    *,
    days: int = 30,
    source: str | None = None,
    project_id: int | None = None,
    tool_code: str | None = None,
) -> str:
    window = max(1, min(90, days))
    start = utcnow() - timedelta(days=window)
    all_events = await _collect_token_events(
        db, employee, start, task_limit=5000, chat_limit=5000
    )
    events = _filter_events(
        all_events,
        source=source,
        project_id=project_id,
        tool_code=tool_code,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "时间",
            "员工编码",
            "员工",
            "来源",
            "场景ID",
            "场景",
            "项目ID",
            "项目",
            "动作",
            "动作类型",
            "工具",
            "模型",
            "Token",
            "成本",
            "Trace ID",
        ]
    )
    for event in events:
        writer.writerow(
            [
                event["occurred_at"],
                _csv_cell(employee.code),
                _csv_cell(employee.name),
                event["source"],
                event["context_id"],
                _csv_cell(event["context_title"]),
                event["project_id"] if event["project_id"] is not None else "",
                _csv_cell(event["project_name"]),
                _csv_cell(event["action"]),
                event["action_type"],
                _csv_cell(event["tool_code"]),
                _csv_cell(event["model"]),
                event["tokens"],
                event["cost"],
                _csv_cell(event["trace_id"]),
            ]
        )
    return "﻿" + buffer.getvalue()


async def workbench(db: AsyncSession, employee: DigitalEmployee) -> dict:
    agent = await get_agent(db, employee.tenant_id, employee.agent_id)
    current_task = await db.scalar(
        select(TaskInstance)
        .where(
            TaskInstance.tenant_id == employee.tenant_id,
            TaskInstance.employee_id == employee.id,
            TaskInstance.status.in_(["running", "waiting_human"]),
        )
        .order_by(TaskInstance.id.desc())
        .limit(1)
    )
    tasks = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(
                    TaskInstance.tenant_id == employee.tenant_id,
                    TaskInstance.employee_id == employee.id,
                )
                .order_by(TaskInstance.id.desc())
                .limit(10)
            )
        ).all()
    )
    task_tokens: dict[int, int] = {}
    if tasks:
        rows = await db.execute(
            select(
                TaskStep.instance_id,
                func.coalesce(func.sum(TaskStep.tokens), 0),
            )
            .where(TaskStep.instance_id.in_([task.id for task in tasks]))
            .group_by(TaskStep.instance_id)
        )
        task_tokens = {row[0]: int(row[1] or 0) for row in rows}

    projects = await employee_projects(
        db, employee.tenant_id, employee.id
    )
    conversations = list(
        (
            await db.scalars(
                select(Conversation)
                .join(
                    ConversationMember,
                    ConversationMember.conversation_id == Conversation.id,
                )
                .where(
                    Conversation.tenant_id == employee.tenant_id,
                    ConversationMember.employee_id == employee.id,
                    Conversation.status == "active",
                )
                .order_by(
                    func.coalesce(
                        Conversation.last_message_at, Conversation.created_at
                    ).desc()
                )
                .limit(5)
            )
        ).all()
    )

    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    task_today, _ = await _task_sums(
        db, employee.tenant_id, employee.id, today
    )
    chat_today, _ = await _chat_sums(
        db, employee.tenant_id, employee.id, today
    )
    task_week, week_cost = await _task_sums(
        db, employee.tenant_id, employee.id, today - timedelta(days=7)
    )
    chat_week, chat_week_cost = await _chat_sums(
        db, employee.tenant_id, employee.id, today - timedelta(days=7)
    )
    task_month, month_cost = await _task_sums(
        db, employee.tenant_id, employee.id, today - timedelta(days=30)
    )
    chat_month, chat_month_cost = await _chat_sums(
        db, employee.tenant_id, employee.id, today - timedelta(days=30)
    )

    if employee.status == "disabled":
        status = "offline"
    elif current_task is not None and current_task.status == "running":
        status = "working"
    elif current_task is not None and current_task.status == "waiting_human":
        status = "waiting"
    else:
        status = "idle"

    last_task_at = max(
        (task.created_at for task in tasks), default=None
    )
    last_chat_at = await db.scalar(
        select(func.max(ChatMessage.created_at)).where(
            ChatMessage.tenant_id == employee.tenant_id,
            ChatMessage.employee_id == employee.id,
        )
    )
    candidates = [
        item for item in (last_task_at, last_chat_at, employee.updated_at) if item
    ]
    last_active_at = max(candidates) if candidates else None

    return {
        "employee": serialize_employee(employee, agent),
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "code": agent.code,
            "model_name": agent.model_name,
            "model_provider": agent.model_provider,
            "tools": agent.tools or [],
            "capabilities": agent.capabilities or [],
        }
        if agent is not None
        else None,
        "status": status,
        "current_task": {
            "id": current_task.id,
            "title": current_task.title,
            "status": current_task.status,
            "task_type": current_task.task_type,
            "project_id": current_task.project_id,
            "started_at": current_task.started_at.isoformat()
            if current_task.started_at
            else None,
        }
        if current_task is not None
        else None,
        "last_active_at": last_active_at.isoformat() if last_active_at else None,
        "recent_tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "task_type": task.task_type,
                "project_id": task.project_id,
                "tokens": task_tokens.get(task.id, 0),
                "created_at": task.created_at.isoformat(),
            }
            for task in tasks
        ],
        "projects": projects,
        "conversations": [
            {
                "id": item.id,
                "title": item.title,
                "mode": item.mode,
                "last_message_at": item.last_message_at.isoformat()
                if item.last_message_at
                else None,
            }
            for item in conversations
        ],
        "token_summary": {
            "today": task_today + chat_today,
            "7d": task_week + chat_week,
            "30d": task_month + chat_month,
            "cost_7d": round(week_cost + chat_week_cost, 6),
            "cost_30d": round(month_cost + chat_month_cost, 6),
        },
    }
