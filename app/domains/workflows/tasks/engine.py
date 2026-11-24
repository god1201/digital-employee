"""任务执行引擎：感知 -> 规划 -> 执行 -> 校验。

设计要点：
- 计划固化到 task_instances.plan，人工确认恢复时不会重新规划，避免步骤错位。
- 每个步骤落 task_steps，失败/等待人工都有明确状态。
- 数据库会话通过 ContextVar 传入节点，保证一次执行使用同一事务。
- 工具调用前强制走准入规则（默认拒绝）。
"""

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.context import trace_id_ctx
from app.core.database import SessionLocal
from app.core.llm import (
    LLMError,
    chat_text,
    is_configured,
    plan_free_task,
    verify_task,
)
from app.domains.governance.audit.service import record_audit
from app.domains.knowledge.graph_rag import graph_rag
from app.domains.knowledge.models import KnowledgeBase
from app.domains.knowledge.service import search_knowledge
from app.domains.learning.attribution import (
    attribute_instance_failure,
    classify_failure,
)
from app.domains.learning.reflection import build_reflection
from app.domains.skills.agents.models import Agent
from app.domains.skills.agents.runner import AgentError, invoke_agent
from app.domains.skills.tools.executor import (
    ToolExecutionError,
    execute_tool,
    render_templates,
)
from app.domains.skills.tools.models import Tool
from app.domains.workflows.tasks.budget import budget_exceeded, budget_limits
from app.domains.workflows.tasks.models import TaskDefinition, TaskInstance, TaskStep
from app.domains.workforce.contracts.service import (
    evaluate_tool_call,
    get_active_contract,
)
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.employees.service import bound_knowledge_base_ids
from app.domains.workforce.persona.service import get_persona, polish_text
from app.domains.workforce.prompting import build_employee_prompt

logger = logging.getLogger(__name__)

_db_session: ContextVar[AsyncSession | None] = ContextVar("task_db_session", default=None)


class TaskState(TypedDict, total=False):
    instance_id: int
    start_index: int
    intent: str
    plan: list[dict]
    results: list[dict]
    current_index: int
    need_human: bool
    human_reason: str
    verified: bool
    verify_reason: str
    error: str


def _db() -> AsyncSession:
    session = _db_session.get()
    if session is None:
        raise RuntimeError("任务执行上下文缺少数据库会话")
    return session


async def _get_instance(db: AsyncSession, instance_id: int) -> TaskInstance:
    instance = await db.get(TaskInstance, instance_id)
    if instance is None:
        raise RuntimeError(f"任务实例不存在: {instance_id}")
    return instance


async def _load_employee(db: AsyncSession, instance: TaskInstance) -> DigitalEmployee | None:
    if instance.employee_id is None:
        return None
    return await db.get(DigitalEmployee, instance.employee_id)


async def _resolve_employee_step_target(
    db: AsyncSession, instance: TaskInstance, step_def: dict
) -> DigitalEmployee | None:
    target_id = step_def.get("employee_id")
    target_code = step_def.get("employee_code")
    if target_id:
        target = await db.get(DigitalEmployee, int(target_id))
        if target is not None and target.tenant_id != instance.tenant_id:
            return None
        return target
    if target_code:
        return await db.scalar(
            select(DigitalEmployee).where(
                DigitalEmployee.tenant_id == instance.tenant_id,
                DigitalEmployee.code == str(target_code),
            )
        )
    return None


async def _fail_instance(db: AsyncSession, instance: TaskInstance, reason: str) -> None:
    first_failure = instance.error is None
    instance.status = "failed"
    instance.error = reason
    instance.finished_at = utcnow()
    await db.flush()
    await record_audit(
        db,
        tenant_id=instance.tenant_id,
        employee_id=instance.employee_id,
        action="task.failed",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={"error": reason[:500]},
        trace_id=instance.trace_id,
    )
    if first_failure:
        try:
            await attribute_instance_failure(db, instance, error=reason)
        except Exception:  # noqa: BLE001
            logger.exception("失败归因写入异常: instance=%s", instance.id)


def _normalize_step(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    step_type = str(raw.get("type") or "tool").lower()
    if step_type not in {
        "tool",
        "llm",
        "human",
        "agent",
        "employee",
        "parallel",
        "knowledge",
        "graph_rag",
    }:
        step_type = "tool"

    arguments = raw.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    tool_code = raw.get("tool_code")
    if tool_code in {"", "null", "None", "none"}:
        tool_code = None

    agent_code = raw.get("agent_code")
    if agent_code in {"", "null", "None", "none"}:
        agent_code = None

    employee_code = raw.get("employee_code")
    if employee_code in {"", "null", "None", "none"}:
        employee_code = None
    employee_id = raw.get("employee_id")
    if employee_id in {"", "null", "None", "none"}:
        employee_id = None
    elif employee_id is not None:
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            employee_id = None

    knowledge_base_id = raw.get("knowledge_base_id")
    if knowledge_base_id in {"", "null", "None", "none"}:
        knowledge_base_id = None

    answer = raw.get("answer", True)
    if isinstance(answer, str):
        answer = answer.strip().lower() not in {"false", "0", "no", "none", ""}
    elif answer is None:
        answer = True

    return {
        "index": index,
        "name": str(raw.get("name") or f"步骤 {index + 1}")[:255],
        "type": step_type,
        "tool_code": tool_code,
        "agent_code": agent_code,
        "employee_id": employee_id,
        "employee_code": employee_code,
        "child_steps": raw.get("child_steps")
        if isinstance(raw.get("child_steps"), list)
        else [],
        "sub_steps": raw.get("sub_steps")
        if isinstance(raw.get("sub_steps"), list)
        else [],
        "knowledge_base_id": knowledge_base_id,
        "query": raw.get("query"),
        "top_k": raw.get("top_k"),
        "max_hops": raw.get("max_hops"),
        "answer": bool(answer),
        "arguments": arguments if isinstance(arguments, dict) else {},
        "prompt": raw.get("prompt"),
        "description": raw.get("description") or "",
    }


async def perceive(state: TaskState) -> dict:
    db = _db()
    instance = await _get_instance(db, state["instance_id"])
    request_text = ""
    if isinstance(instance.input, dict):
        request_text = str(instance.input.get("request") or instance.input.get("prompt") or "")
    intent = f"{instance.title} {request_text}".strip()
    return {
        "intent": intent[:2000],
        "start_index": max(0, int(state.get("start_index") or 0)),
    }


async def plan_steps(state: TaskState) -> dict:
    db = _db()
    instance = await _get_instance(db, state["instance_id"])
    if instance.status == "cancelled":
        return {"error": "任务已取消"}

    # 已固化的计划优先复用，保证人工确认后恢复一致
    if instance.plan:
        return {"plan": instance.plan}

    definition = None
    if instance.definition_id:
        definition = await db.get(TaskDefinition, instance.definition_id)

    if definition is not None and definition.steps:
        plan = [_normalize_step(step, index) for index, step in enumerate(definition.steps)]
        instance.plan = plan
        await db.flush()
        await db.commit()
        return {"plan": plan}

    if instance.task_type == "fixed":
        reason = "固定任务未配置可执行步骤"
        await _fail_instance(db, instance, reason)
        return {"error": reason}

    employee = await _load_employee(db, instance)
    if employee is None:
        reason = "任务实例未绑定数字员工"
        await _fail_instance(db, instance, reason)
        return {"error": reason}

    if not is_configured():
        reason = "自由任务需要配置 LLM_API_KEY，当前未配置"
        await _fail_instance(db, instance, reason)
        return {"error": reason}

    tools = list(
        (
            await db.scalars(
                select(Tool).where(
                    Tool.tenant_id == instance.tenant_id,
                    Tool.enabled.is_(True),
                )
            )
        ).all()
    )
    agents = list(
        (
            await db.scalars(
                select(Agent).where(
                    Agent.tenant_id == instance.tenant_id,
                    Agent.status == "active",
                )
            )
        ).all()
    )
    knowledge_bases = list(
        (
            await db.scalars(
                select(KnowledgeBase).where(
                    KnowledgeBase.tenant_id == instance.tenant_id,
                    KnowledgeBase.status == "active",
                )
            )
        ).all()
    )
    bound_kb_ids = set(bound_knowledge_base_ids(employee))
    if bound_kb_ids:
        knowledge_bases = [
            base for base in knowledge_bases if base.id in bound_kb_ids
        ]
    reflection_hint = str(
        (instance.input or {}).get("_reflection_hint") or ""
    ).strip()
    employee_context = await build_employee_prompt(
        db,
        instance.tenant_id,
        employee,
        trace_id=instance.trace_id,
        extra=(
            f"【上次失败反思】\n{reflection_hint}" if reflection_hint else ""
        ),
    )
    try:
        raw_steps, _tokens = await plan_free_task(
            employee,
            instance.input or {},
            tools,
            agents,
            knowledge_bases,
            employee_context=employee_context,
        )
    except LLMError as exc:
        await _fail_instance(db, instance, str(exc))
        return {"error": str(exc)}

    plan = [_normalize_step(step, index) for index, step in enumerate(raw_steps)]
    if not plan:
        reason = "规划结果为空"
        await _fail_instance(db, instance, reason)
        return {"error": reason}

    instance.plan = plan
    await db.flush()
    await db.commit()
    return {"plan": plan}


async def execute_steps(state: TaskState) -> dict:
    db = _db()
    instance = await _get_instance(db, state["instance_id"])
    if instance.status == "cancelled":
        return {"error": "任务已取消"}

    plan = state.get("plan") or []
    if not plan:
        reason = "没有可执行的步骤"
        await _fail_instance(db, instance, reason)
        return {"error": reason}

    start_index = max(0, int(state.get("start_index") or 0))
    employee = await _load_employee(db, instance)
    bound_kb_ids = set(bound_knowledge_base_ids(employee))
    contract = await get_active_contract(db, instance.tenant_id, instance.employee_id)
    persona = None
    if instance.employee_id is not None:
        persona = await get_persona(db, instance.tenant_id, instance.employee_id)
    reflection_hint = str(
        (instance.input or {}).get("_reflection_hint") or ""
    ).strip()
    employee_context = (
        await build_employee_prompt(
            db,
            instance.tenant_id,
            employee,
            trace_id=instance.trace_id,
            extra=(
                f"【上次失败反思】\n{reflection_hint}" if reflection_hint else ""
            ),
        )
        if employee is not None
        else ""
    )

    # 恢复执行时，把此前已成功的步骤结果带回，供校验和模板引用。
    # 反思记录不是业务步骤，不能进入结果集或 Token 预算。
    existing_steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(
                    TaskStep.instance_id == instance.id,
                    TaskStep.status == "succeeded",
                    TaskStep.step_type != "reflection",
                )
                .order_by(TaskStep.step_index)
            )
        ).all()
    )
    results = [
        {"step_index": step.step_index, "name": step.name, "output": step.output}
        for step in existing_steps
        if step.step_index < start_index
    ]
    used_tokens = sum(step.tokens or 0 for step in existing_steps)
    used_cost = sum(step.cost or 0 for step in existing_steps)
    limits = budget_limits((employee.config or {}) if employee is not None else {})

    context: dict = {
        "input": instance.input or {},
        "task": {"id": instance.id, "title": instance.title},
        "employee": {},
        "last": results[-1]["output"] if results else {},
    }
    if employee is not None:
        context["employee"] = {
            "id": employee.id,
            "name": employee.name,
            "code": employee.code,
            "position": employee.position,
        }

    for index in range(start_index, len(plan)):
        # 每步开始前检查是否被取消（上一步提交后新事务能看到最新状态）
        current_status = await db.scalar(
            select(TaskInstance.status).where(TaskInstance.id == instance.id)
        )
        if current_status == "cancelled":
            instance.status = "cancelled"
            return {"error": "任务已取消"}

        step_def = plan[index]
        step = TaskStep(
            instance_id=instance.id,
            step_index=index,
            name=str(step_def.get("name") or f"步骤 {index + 1}")[:255],
            status="running",
            step_type=str(step_def.get("type") or "tool"),
            input={
                "arguments": step_def.get("arguments") or {},
                "prompt": step_def.get("prompt"),
            },
            output={},
            tool_code=step_def.get("tool_code"),
            started_at=utcnow(),
        )
        db.add(step)
        await db.flush()
        instance.current_step_index = index
        await db.commit()

        if step.step_type == "human":
            step.status = "waiting"
            instance.status = "waiting_human"
            await db.flush()
            await db.commit()
            return {
                "need_human": True,
                "human_reason": step_def.get("description") or "需要人工确认",
                "current_index": index,
                "results": results,
            }

        try:
            if step.step_type == "tool":
                tool_code = step_def.get("tool_code")
                if not tool_code:
                    raise ToolExecutionError("工具步骤缺少 tool_code")

                arguments = render_templates(step_def.get("arguments") or {}, context)
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                step.input = {"arguments": arguments, "tool_code": str(tool_code)}

                tool = await db.scalar(
                    select(Tool).where(
                        Tool.tenant_id == instance.tenant_id,
                        Tool.code == str(tool_code),
                        Tool.enabled.is_(True),
                    )
                )
                if tool is None:
                    raise ToolExecutionError(f"工具不存在或已停用: {tool_code}")

                if contract is not None and not step_def.get("approved_gate"):
                    decision = evaluate_tool_call(
                        contract,
                        tool=tool,
                        arguments=arguments,
                        step_name=step.name,
                        step_description=str(step_def.get("description") or ""),
                    )
                    if decision.action != "allow":
                        await record_audit(
                            db,
                            tenant_id=instance.tenant_id,
                            employee_id=instance.employee_id,
                            action=f"contract.{decision.action}",
                            resource_type="task_step",
                            resource_id=step.id,
                            detail={
                                "tool_code": str(tool_code),
                                "reason": decision.reason,
                                "rule": decision.rule,
                                "trace_id": instance.trace_id,
                            },
                            trace_id=instance.trace_id,
                        )
                    if decision.action == "deny":
                        step.status = "failed"
                        step.error = f"岗位契约拦截：{decision.reason}"
                        step.output = {"contract_decision": decision.as_dict()}
                        step.finished_at = utcnow()
                        await _fail_instance(db, instance, step.error)
                        await db.commit()
                        return {
                            "error": step.error,
                            "results": results,
                            "current_index": index,
                        }
                    if decision.action == "ask":
                        step.status = "waiting"
                        step.output = {
                            "contract_gate": decision.as_dict(),
                            "arguments": arguments,
                            "tool_code": str(tool_code),
                        }
                        instance.status = "waiting_human"
                        await db.flush()
                        await db.commit()
                        return {
                            "need_human": True,
                            "human_reason": decision.reason,
                            "current_index": index,
                            "results": results,
                        }

                result = await execute_tool(
                    db,
                    tenant_id=instance.tenant_id,
                    employee_id=instance.employee_id or 0,
                    tool_code=str(tool_code),
                    arguments=arguments,
                )
                step.output = result.output
                step.latency_ms = result.latency_ms
                if not result.success:
                    raise ToolExecutionError(result.error or "工具执行失败")

            elif step.step_type == "llm":
                if not is_configured():
                    raise LLMError("未配置 LLM_API_KEY")
                prompt = render_templates(step_def.get("prompt") or step_def.get("name"), context)
                step.input = {"prompt": prompt}
                system_prompt = employee_context or "你是一名数字员工。"
                content, tokens = await chat_text(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": str(prompt)},
                    ]
                )
                polished, persona_warnings = await polish_text(content, persona)
                step.output = {"text": polished}
                if persona_warnings:
                    step.output["persona_warnings"] = persona_warnings
                step.tokens = tokens
                step.cost = round(tokens / 1000 * settings.llm_cost_per_1k_tokens, 6)

            elif step.step_type == "agent":
                agent_code = step_def.get("agent_code")
                if not agent_code:
                    raise AgentError("Agent 步骤缺少 agent_code")

                agent = await db.scalar(
                    select(Agent).where(
                        Agent.tenant_id == instance.tenant_id,
                        Agent.code == str(agent_code),
                        Agent.status == "active",
                    )
                )
                if agent is None:
                    raise AgentError(f"Agent 不存在或已停用: {agent_code}")

                arguments = render_templates(step_def.get("arguments") or {}, context)
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                prompt = None
                if step_def.get("prompt"):
                    prompt = str(render_templates(step_def["prompt"], context))

                step.input = {
                    "agent_code": str(agent_code),
                    "arguments": arguments,
                    "prompt": prompt,
                }
                result = await invoke_agent(
                    db,
                    agent,
                    tenant_id=instance.tenant_id,
                    employee_id=instance.employee_id or 0,
                    input_data=arguments,
                    prompt=prompt,
                )
                step.output = result.output
                step.tokens = result.tokens
                step.cost = round(result.tokens / 1000 * settings.llm_cost_per_1k_tokens, 6)
                step.latency_ms = result.latency_ms

            elif step.step_type == "employee":
                target = await _resolve_employee_step_target(db, instance, step_def)
                if target is None:
                    raise ToolExecutionError("协作步骤未找到目标数字员工")

                depth = int((instance.input or {}).get("collaboration_depth") or 0)
                if depth >= 3:
                    raise ToolExecutionError("协作层级超过上限 3")
                prompt_text = render_templates(
                    step_def.get("prompt") or step_def.get("description") or "", context
                )
                arguments = render_templates(step_def.get("arguments") or {}, context)
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                step.input = {
                    "employee_id": target.id,
                    "employee_code": target.code,
                    "prompt": str(prompt_text),
                    "arguments": arguments,
                }

                child_plan = step_def.get("child_steps")
                child = TaskInstance(
                    tenant_id=instance.tenant_id,
                    employee_id=target.id,
                    title=f"协作：{step.name}"[:255],
                    task_type="free",
                    status="running",
                    plan=child_plan if isinstance(child_plan, list) else [],
                    input={
                        "request": str(prompt_text),
                        "parent_instance_id": instance.id,
                        "collaboration_depth": depth + 1,
                        "arguments": arguments,
                    },
                    output={},
                    trace_id=uuid.uuid4().hex,
                    created_by=instance.created_by,
                )
                db.add(child)
                await db.flush()
                child_id = child.id
                await db.commit()

                await run_task_graph(child_id, 0)
                await db.refresh(child)
                child_steps = list(
                    (
                        await db.scalars(
                            select(TaskStep).where(TaskStep.instance_id == child_id)
                        )
                    ).all()
                )
                step.tokens = sum(item.tokens or 0 for item in child_steps)
                step.cost = round(sum(item.cost or 0 for item in child_steps), 6)
                if child.status != "succeeded":
                    raise ToolExecutionError(
                        f"协作员工「{target.name}」执行失败: "
                        f"{child.error or child.status}"
                    )
                step.output = {
                    "child_instance_id": child_id,
                    "employee_id": target.id,
                    "employee_name": target.name,
                    "status": child.status,
                    "output": child.output,
                }

            elif step.step_type == "parallel":
                sub_steps = step_def.get("sub_steps")
                if not isinstance(sub_steps, list) or not sub_steps:
                    raise ToolExecutionError("并行步骤缺少 sub_steps")
                depth = int((instance.input or {}).get("collaboration_depth") or 0)
                if depth >= 3:
                    raise ToolExecutionError("协作层级超过上限 3")

                children: list[tuple[DigitalEmployee, TaskInstance]] = []
                for sub_index, sub in enumerate(sub_steps):
                    if not isinstance(sub, dict):
                        continue
                    target = await _resolve_employee_step_target(db, instance, sub)
                    if target is None:
                        raise ToolExecutionError(
                            f"并行子步骤 {sub_index + 1} 未找到目标员工"
                        )
                    prompt_text = render_templates(
                        sub.get("prompt") or sub.get("description") or "", context
                    )
                    arguments = render_templates(sub.get("arguments") or {}, context)
                    if not isinstance(arguments, dict):
                        arguments = {"value": arguments}
                    child_plan = sub.get("child_steps")
                    child = TaskInstance(
                        tenant_id=instance.tenant_id,
                        employee_id=target.id,
                        title=f"协作：{sub.get('name') or target.name}"[:255],
                        task_type="free",
                        status="running",
                        plan=child_plan if isinstance(child_plan, list) else [],
                        input={
                            "request": str(prompt_text),
                            "parent_instance_id": instance.id,
                            "collaboration_depth": depth + 1,
                            "parallel_index": sub_index,
                            "arguments": arguments,
                        },
                        output={},
                        trace_id=uuid.uuid4().hex,
                        created_by=instance.created_by,
                    )
                    db.add(child)
                    await db.flush()
                    children.append((target, child))

                if not children:
                    raise ToolExecutionError("并行步骤没有可执行的子任务")
                step.input = {
                    "mode": "parallel",
                    "children": [
                        {"employee_id": target.id, "employee_code": target.code}
                        for target, _child in children
                    ],
                }
                await db.commit()

                outcomes = await asyncio.gather(
                    *(run_task_graph(child.id, 0) for _target, child in children),
                    return_exceptions=True,
                )
                failed: list[str] = []
                for (target, child), outcome in zip(children, outcomes, strict=False):
                    await db.refresh(child)
                    if isinstance(outcome, Exception):
                        logger.error("并行协作子任务异常: %s", outcome)
                    if child.status != "succeeded":
                        failed.append(f"{target.name}: {child.error or child.status}")

                child_ids = [child.id for _target, child in children]
                child_step_rows = list(
                    (
                        await db.scalars(
                            select(TaskStep).where(TaskStep.instance_id.in_(child_ids))
                        )
                    ).all()
                )
                step.tokens = sum(item.tokens or 0 for item in child_step_rows)
                step.cost = round(sum(item.cost or 0 for item in child_step_rows), 6)
                step.output = {
                    "mode": "parallel",
                    "children": [
                        {
                            "child_instance_id": child.id,
                            "employee_id": target.id,
                            "employee_name": target.name,
                            "status": child.status,
                            "output": child.output,
                            "error": child.error,
                        }
                        for target, child in children
                    ],
                }
                if failed:
                    raise ToolExecutionError("并行协作存在失败: " + "; ".join(failed))

            elif step.step_type == "knowledge":
                base_id = step_def.get("knowledge_base_id")
                query = step_def.get("query") or step_def.get("prompt")
                if not base_id or not query:
                    raise ToolExecutionError("知识检索步骤缺少 knowledge_base_id / query")
                try:
                    base_id_int = int(base_id)
                except (TypeError, ValueError) as exc:
                    raise ToolExecutionError("knowledge_base_id 必须是整数") from exc
                if bound_kb_ids and base_id_int not in bound_kb_ids:
                    raise ToolExecutionError(
                        f"知识库 {base_id_int} 不在员工已绑定范围内"
                    )

                query_text = str(render_templates(query, context))
                try:
                    top_k = int(step_def.get("top_k") or 5)
                except (TypeError, ValueError):
                    top_k = 5

                step.input = {
                    "knowledge_base_id": base_id_int,
                    "query": query_text,
                    "top_k": top_k,
                }
                knowledge_results = await search_knowledge(
                    db,
                    instance.tenant_id,
                    base_id_int,
                    query_text,
                    top_k,
                )
                step.output = {"query": query_text, "results": knowledge_results}

            elif step.step_type == "graph_rag":
                base_id = step_def.get("knowledge_base_id")
                query = step_def.get("query") or step_def.get("prompt")
                if not base_id or not query:
                    raise ToolExecutionError("GraphRAG 步骤缺少 knowledge_base_id / query")
                try:
                    base_id_int = int(base_id)
                except (TypeError, ValueError) as exc:
                    raise ToolExecutionError("knowledge_base_id 必须是整数") from exc
                if bound_kb_ids and base_id_int not in bound_kb_ids:
                    raise ToolExecutionError(
                        f"知识库 {base_id_int} 不在员工已绑定范围内"
                    )

                query_text = str(render_templates(query, context))
                try:
                    top_k = int(step_def.get("top_k") or 5)
                except (TypeError, ValueError):
                    top_k = 5
                try:
                    max_hops = int(step_def.get("max_hops") or 1)
                except (TypeError, ValueError):
                    max_hops = 1

                step.input = {
                    "knowledge_base_id": base_id_int,
                    "query": query_text,
                    "top_k": top_k,
                    "max_hops": max_hops,
                    "answer": bool(step_def.get("answer", True)),
                }
                rag_result = await graph_rag(
                    db,
                    instance.tenant_id,
                    base_id_int,
                    query_text,
                    top_k,
                    max_hops,
                    bool(step_def.get("answer", True)),
                )
                step.output = rag_result
                step.tokens = int(rag_result.get("tokens") or 0)
                step.cost = round(step.tokens / 1000 * settings.llm_cost_per_1k_tokens, 6)

            else:
                raise ToolExecutionError(f"不支持的步骤类型: {step.step_type}")

        except (ToolExecutionError, LLMError, AgentError) as exc:
            step.status = "failed"
            step.error = str(exc)
            step.finished_at = utcnow()
            await _fail_instance(db, instance, str(exc))
            await db.commit()
            return {"error": str(exc), "results": results, "current_index": index}

        except Exception as exc:  # noqa: BLE001
            logger.exception("任务步骤执行异常: instance=%s step=%s", instance.id, index)
            step.status = "failed"
            step.error = f"执行异常: {exc}"
            step.finished_at = utcnow()
            await _fail_instance(db, instance, step.error)
            await db.commit()
            return {"error": step.error, "results": results, "current_index": index}

        step.status = "succeeded"
        step.finished_at = utcnow()
        await db.flush()
        await db.commit()

        used_tokens += step.tokens or 0
        used_cost += step.cost or 0
        violation = budget_exceeded(used_tokens, used_cost, limits)
        if violation:
            await _fail_instance(db, instance, violation)
            await db.commit()
            return {"error": violation, "results": results, "current_index": index}

        results.append({"step_index": index, "name": step.name, "output": step.output})
        context["last"] = step.output

    return {"results": results, "current_index": len(plan) - 1}


async def verify_steps(state: TaskState) -> dict:
    db = _db()
    instance = await _get_instance(db, state["instance_id"])
    if state.get("error"):
        return {"verified": False, "verify_reason": state["error"]}
    if state.get("need_human"):
        return {"verified": False, "verify_reason": state.get("human_reason", "")}

    plan = instance.plan or state.get("plan") or []
    results = state.get("results") or []
    succeeded = {item["step_index"] for item in results}
    missing = [index for index in range(len(plan)) if index not in succeeded]
    passed = not missing
    reason = "全部步骤执行成功" if passed else f"步骤未全部完成: {missing}"

    employee = await _load_employee(db, instance)
    config = (employee.config or {}) if employee is not None else {}
    if passed and employee is not None and config.get("auto_verify") and is_configured():
        try:
            verdict, _tokens = await verify_task(employee, instance.input or {}, results)
            verdict_value = verdict.get("passed")
            passed = verdict_value is True or str(verdict_value).lower() == "true"
            reason = str(verdict.get("reason") or reason)
        except LLMError as exc:
            passed = False
            reason = f"自动校验失败: {exc}"

    instance.status = "succeeded" if passed else "failed"
    instance.output = {"summary": reason, "results": results}
    instance.error = None if passed else reason
    instance.finished_at = utcnow()
    await db.flush()
    await record_audit(
        db,
        tenant_id=instance.tenant_id,
        employee_id=instance.employee_id,
        action="task.succeeded" if passed else "task.failed",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={"reason": reason[:500]},
        trace_id=instance.trace_id,
    )
    if not passed:
        try:
            await attribute_instance_failure(db, instance, error=reason)
        except Exception:  # noqa: BLE001
            logger.exception("失败归因写入异常: instance=%s", instance.id)
    await db.commit()
    return {"verified": passed, "verify_reason": reason}


def should_auto_retry(instance, reflection: dict, existing_reflections: int) -> bool:
    """只有自由任务、可重试类别且未超过反思次数/执行次数时才自动重试。"""
    return bool(
        settings.reflection_auto_retry
        and reflection.get("retryable")
        and instance.task_type == "free"
        and existing_reflections < max(0, int(settings.reflection_max_retries))
        and instance.attempt < instance.max_attempts
    )


async def reflect_on_failure(state: TaskState) -> dict:
    """记录失败反思；对可安全重试的自由任务注入修正提示并重新入队。"""
    db = _db()
    instance = await _get_instance(db, state["instance_id"])
    reason = str(
        state.get("error")
        or state.get("verify_reason")
        or instance.error
        or "任务失败"
    )
    if (
        instance.status == "cancelled"
        or state.get("need_human")
        or not settings.reflection_enabled
    ):
        return {"verified": False, "verify_reason": reason}

    steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(
                    TaskStep.instance_id == instance.id,
                    TaskStep.step_type != "reflection",
                )
                .order_by(TaskStep.step_index)
            )
        ).all()
    )
    classified = classify_failure(
        instance=instance, steps=steps, error=reason
    )
    category = classified["category"]
    reflection = await build_reflection(
        instance,
        steps,
        reason,
        category,
        suggestion=classified.get("suggestion", ""),
    )

    existing_reflections = int(
        await db.scalar(
            select(func.count(TaskStep.id)).where(
                TaskStep.instance_id == instance.id,
                TaskStep.step_type == "reflection",
            )
        )
        or 0
    )
    max_index = await db.scalar(
        select(func.max(TaskStep.step_index)).where(
            TaskStep.instance_id == instance.id
        )
    )
    step_index = int(max_index or -1) + 1
    auto_retry = should_auto_retry(
        instance, reflection, existing_reflections
    )
    hint = str(reflection.get("hint") or "")[:800]
    now = utcnow()
    db.add(
        TaskStep(
            instance_id=instance.id,
            step_index=step_index,
            name="反思与修正",
            status="succeeded",
            step_type="reflection",
            input={"reason": reason[:1000], "category": category},
            output={
                **reflection,
                "auto_retry": auto_retry,
                "reflection_index": existing_reflections + 1,
            },
            started_at=now,
            finished_at=now,
        )
    )
    output = dict(instance.output or {})
    output["reflection"] = {
        **reflection,
        "auto_retry": auto_retry,
        "at": now.isoformat(),
    }
    instance.output = output

    if auto_retry:
        task_input = dict(instance.input or {})
        task_input["_reflection_hint"] = hint
        instance.input = task_input
        # 自由任务清空计划以便带着反思提示重新规划；固定任务禁止自动重试，
        # 避免重复执行可能不可逆的外部工具动作。
        instance.plan = []
        instance.next_step_index = 0
        instance.current_step_index = 0
        instance.status = "pending"
        instance.next_run_at = now
        instance.finished_at = None

    await db.flush()
    await record_audit(
        db,
        tenant_id=instance.tenant_id,
        employee_id=instance.employee_id,
        action="task.reflection",
        resource_type="task_instance",
        resource_id=instance.id,
        detail={
            "category": category,
            "retryable": reflection.get("retryable"),
            "auto_retry": auto_retry,
            "reason": reason[:300],
        },
        trace_id=instance.trace_id,
    )
    await db.commit()
    return {"verified": False, "verify_reason": reason}


def route_after_plan(state: TaskState) -> str:
    return "reflect" if state.get("error") else "execute"


def route_after_execute(state: TaskState) -> str:
    if state.get("need_human"):
        return END
    if state.get("error"):
        return "reflect"
    return "verify"


def route_after_verify(state: TaskState) -> str:
    return END if state.get("verified") else "reflect"


def build_task_graph():
    graph = StateGraph(TaskState)
    graph.add_node("perceive", perceive)
    graph.add_node("plan", plan_steps)
    graph.add_node("execute", execute_steps)
    graph.add_node("verify", verify_steps)
    graph.add_node("reflect", reflect_on_failure)

    graph.add_edge(START, "perceive")
    graph.add_edge("perceive", "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"execute": "execute", "reflect": "reflect"},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {"verify": "verify", "reflect": "reflect", END: END},
    )
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"reflect": "reflect", END: END},
    )
    graph.add_edge("reflect", END)
    return graph.compile()


task_graph = build_task_graph()


async def run_task_graph(instance_id: int, start_index: int = 0) -> None:
    """后台执行入口：自行管理会话，异常时兜底标记失败。"""
    async with SessionLocal() as session:
        token = _db_session.set(session)
        trace_token = None
        try:
            instance = await session.get(TaskInstance, instance_id)
            if instance is None or instance.status in {"cancelled", "succeeded"}:
                return
            trace_token = trace_id_ctx.set(instance.trace_id or "-")

            instance.status = "running"
            instance.error = None
            if instance.started_at is None:
                instance.started_at = utcnow()
            await session.commit()

            state: TaskState = {
                "instance_id": instance_id,
                "start_index": max(0, start_index),
            }
            await asyncio.wait_for(task_graph.ainvoke(state), timeout=600)
            await session.commit()

        except TimeoutError:
            await session.rollback()
            await _mark_failed(instance_id, "任务执行超时")
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务执行异常: instance=%s", instance_id)
            await session.rollback()
            await _mark_failed(instance_id, f"任务执行异常: {exc}")
        finally:
            _db_session.reset(token)
            if trace_token is not None:
                trace_id_ctx.reset(trace_token)


async def _mark_failed(instance_id: int, error: str) -> None:
    async with SessionLocal() as session:
        instance = await session.get(TaskInstance, instance_id)
        if instance is None or instance.status in {"succeeded", "cancelled"}:
            return
        instance.status = "failed"
        instance.error = error
        instance.finished_at = utcnow()
        await session.commit()
