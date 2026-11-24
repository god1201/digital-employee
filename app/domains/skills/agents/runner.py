"""Agent 执行器：内置 ReAct Agent 与第三方 Agent。"""

import json
import re
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import LLMError, chat_with_tools, is_configured
from app.domains.skills.agents.models import Agent
from app.domains.skills.tools.executor import execute_tool
from app.domains.skills.tools.models import Tool


class AgentError(Exception):
    """Agent 调用失败。"""


@dataclass
class AgentResult:
    output: dict
    tokens: int = 0
    latency_ms: int = 0
    tool_calls: list[dict] = field(default_factory=list)


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
                    "parameters": tool.parameters_schema or {"type": "object", "properties": {}},
                },
            }
        )
    return specs, mapping


async def _load_bound_tools(db: AsyncSession, tenant_id: int, codes: list) -> list[Tool]:
    if not codes:
        return []
    return list(
        (
            await db.scalars(
                select(Tool).where(
                    Tool.tenant_id == tenant_id,
                    Tool.code.in_([str(code) for code in codes]),
                    Tool.enabled.is_(True),
                )
            )
        ).all()
    )


async def _run_internal(
    db: AsyncSession,
    agent: Agent,
    *,
    tenant_id: int,
    employee_id: int,
    input_data: dict,
    prompt: str | None,
) -> tuple[dict, int, list[dict]]:
    if not is_configured():
        raise AgentError("内置 Agent 需要配置 LLM_API_KEY")

    tools = await _load_bound_tools(db, tenant_id, list(agent.tools or []))
    specs, mapping = _tool_specs(tools)

    messages: list[dict] = [
        {
            "role": "system",
            "content": agent.system_prompt or f"你是 {agent.name}，请完成用户交给你的任务。",
        },
        {
            "role": "user",
            "content": prompt or json.dumps(input_data, ensure_ascii=False),
        },
    ]

    config = agent.config or {}
    try:
        max_steps = int(config.get("max_steps") or 6)
    except (TypeError, ValueError):
        max_steps = 6
    max_steps = max(1, min(max_steps, 12))

    total_tokens = 0
    trace: list[dict] = []

    for _ in range(max_steps):
        message, tokens = await chat_with_tools(
            messages,
            specs,
            model=agent.model_name or None,
        )
        total_tokens += tokens

        content = message.get("content")
        content_text = content if isinstance(content, str) else ""
        tool_calls = message.get("tool_calls") or []

        assistant_message: dict = {"role": "assistant", "content": content_text}
        if isinstance(tool_calls, list) and tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        if not isinstance(tool_calls, list) or not tool_calls:
            return (
                {
                    "text": content_text,
                    "agent": agent.code,
                    "tool_calls": trace,
                },
                total_tokens,
                trace,
            )

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or f"call_{len(trace) + 1}")
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
                trace.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": False,
                        "error": "unknown tool",
                    }
                )
            else:
                result = await execute_tool(
                    db,
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    tool=tool,
                    arguments=arguments,
                )
                payload = (
                    result.output if result.success else {"error": result.error or "工具执行失败"}
                )
                trace.append(
                    {
                        "tool": tool.code,
                        "arguments": arguments,
                        "success": result.success,
                        "output": result.output if result.success else None,
                        "error": result.error if not result.success else None,
                        "latency_ms": result.latency_ms,
                    }
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )

    raise AgentError(f"超过最大推理步数（{max_steps}）")


async def _run_third_party(
    agent: Agent,
    *,
    input_data: dict,
    prompt: str | None,
) -> tuple[dict, int]:
    if not agent.endpoint_url:
        raise AgentError("第三方 Agent 缺少 endpoint_url")

    config = agent.config or {}
    try:
        timeout = float(config.get("timeout") or 30)
    except (TypeError, ValueError):
        timeout = 30.0
    timeout = max(1.0, min(timeout, 300.0))

    headers = {str(key): str(value) for key, value in (agent.headers or {}).items()}
    headers.setdefault("Content-Type", "application/json")

    if agent.protocol == "openai":
        payload = {
            "model": agent.model_name or settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": agent.system_prompt or f"你是 {agent.name}。",
                },
                {
                    "role": "user",
                    "content": prompt or json.dumps(input_data, ensure_ascii=False),
                },
            ],
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(agent.endpoint_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AgentError(f"第三方 Agent 请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise AgentError(f"第三方 Agent 返回 {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentError("第三方 Agent 返回结构异常") from exc
        usage = data.get("usage") or {}
        try:
            tokens = int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        return {"text": content, "agent": agent.code}, tokens

    payload = {
        "agent": agent.code,
        "input": input_data,
        "prompt": prompt,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(agent.endpoint_url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise AgentError(f"第三方 Agent 请求失败: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(f"第三方 Agent 返回 {response.status_code}: {response.text[:300]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise AgentError("第三方 Agent 返回的不是 JSON") from exc

    if isinstance(data, dict):
        output = data.get("output", data)
        try:
            tokens = int(data.get("tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
    else:
        output = {"result": data}
        tokens = 0

    if not isinstance(output, dict):
        output = {"result": output}
    return output, tokens


async def invoke_agent(
    db: AsyncSession,
    agent: Agent,
    *,
    tenant_id: int,
    employee_id: int,
    input_data: dict,
    prompt: str | None = None,
) -> AgentResult:
    started = time.perf_counter()
    if agent.status != "active":
        raise AgentError("Agent 已停用")

    try:
        if agent.agent_type == "internal":
            output, tokens, tool_calls = await _run_internal(
                db,
                agent,
                tenant_id=tenant_id,
                employee_id=employee_id,
                input_data=input_data,
                prompt=prompt,
            )
        else:
            output, tokens = await _run_third_party(agent, input_data=input_data, prompt=prompt)
            tool_calls = []
    except AgentError:
        raise
    except LLMError as exc:
        raise AgentError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise AgentError(f"Agent 调用失败: {exc}") from exc

    return AgentResult(
        output=output,
        tokens=tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
        tool_calls=tool_calls,
    )
