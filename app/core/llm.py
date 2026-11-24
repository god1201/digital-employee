import json
import re
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.tokenizer import count_tokens


class LLMError(Exception):
    """大模型调用失败。"""


def _api_key() -> str:
    return settings.llm_api_key or settings.deepseek_api_key


def is_configured() -> bool:
    return bool(_api_key())


def _default_model() -> str:
    if settings.llm_model and settings.llm_model != "gpt-4o-mini":
        return settings.llm_model
    if settings.llm_provider.lower() == "deepseek":
        return "deepseek-chat"
    return settings.llm_model


def _endpoint() -> str:
    default_base = (
        "https://api.deepseek.com/v1"
        if settings.llm_provider.lower() == "deepseek"
        else "https://api.openai.com/v1"
    )
    base = (settings.llm_base_url or default_base).rstrip("/")
    return f"{base}/chat/completions"


async def _request(
    messages: list[dict],
    *,
    model: str | None = None,
    json_mode: bool = False,
    tools: list[dict] | None = None,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> tuple[dict, int]:
    if not is_configured():
        raise LLMError("未配置 LLM_API_KEY")

    payload: dict = {
        "model": model or _default_model(),
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(_endpoint(), headers=headers, json=payload)
        if response.status_code >= 400 and json_mode:
            # 部分兼容接口不支持 response_format，去掉后重试一次
            payload.pop("response_format", None)
            response = await client.post(_endpoint(), headers=headers, json=payload)
        if response.status_code >= 400:
            raise LLMError(f"LLM 调用失败（{response.status_code}）: {response.text[:300]}")
        data = response.json()

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM 返回结构异常") from exc
    if not isinstance(message, dict):
        raise LLMError("LLM 返回结构异常")

    usage = data.get("usage") or {}
    try:
        tokens = int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        tokens = 0
    return message, tokens


async def _chat(
    messages: list[dict],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> tuple[str, int]:
    message, tokens = await _request(
        messages,
        model=model,
        json_mode=json_mode,
        temperature=temperature,
        timeout=timeout,
    )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM 返回内容为空")
    return content, tokens


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("LLM 未返回合法 JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("LLM 未返回合法 JSON") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM 返回的 JSON 不是对象")
    return data


async def chat_text(messages: list[dict], **kwargs) -> tuple[str, int]:
    return await _chat(messages, json_mode=False, **kwargs)


async def chat_json(messages: list[dict], **kwargs) -> tuple[dict, int]:
    content, tokens = await _chat(messages, json_mode=True, **kwargs)
    return _parse_json(content), tokens


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> tuple[dict, int]:
    """返回原始 message（可能包含 tool_calls）与 token 数。"""
    return await _request(
        messages,
        model=model,
        tools=tools or None,
        temperature=temperature,
        timeout=timeout,
    )


async def chat_with_tools_stream(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 180.0,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[dict, int]:
    """流式调用：逐段回调 content，并累积 tool_calls 返回完整 message。"""
    if not is_configured():
        raise LLMError("未配置 LLM_API_KEY")

    payload: dict = {
        "model": model or _default_model(),
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    tokens = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.send(
            client.build_request("POST", _endpoint(), headers=headers, json=payload),
            stream=True,
        )
        if response.status_code >= 400 and "stream_options" in payload:
            # 兼容不支持 include_usage 的服务：去掉后重试
            await response.aread()
            await response.aclose()
            payload.pop("stream_options", None)
            response = await client.send(
                client.build_request(
                    "POST", _endpoint(), headers=headers, json=payload
                ),
                stream=True,
            )
        try:
            if response.status_code >= 400:
                body = await response.aread()
                raise LLMError(
                    f"LLM 调用失败（{response.status_code}）: "
                    f"{body.decode('utf-8', errors='replace')[:300]}"
                )

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage") or {}
                try:
                    tokens = int(usage.get("total_tokens") or tokens)
                except (TypeError, ValueError):
                    pass
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if isinstance(text, str) and text:
                    content_parts.append(text)
                    if on_delta is not None:
                        await on_delta(text)
                for item in delta.get("tool_calls") or []:
                    try:
                        index = int(item.get("index") or 0)
                    except (TypeError, ValueError):
                        index = 0
                    slot = tool_calls.setdefault(
                        index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if item.get("id"):
                        slot["id"] = item["id"]
                    function = item.get("function") or {}
                    name = function.get("name")
                    if name and not slot["function"]["name"]:
                        slot["function"]["name"] = name
                    arguments = function.get("arguments")
                    if arguments:
                        slot["function"]["arguments"] += arguments
        finally:
            await response.aclose()

    content = "".join(content_parts)
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    if not tokens:
        tokens = count_tokens(content, model=model)
    return message, tokens


async def plan_free_task(
    employee,
    task_input: dict,
    tools: list,
    agents: list | None = None,
    knowledge_bases: list | None = None,
    employee_context: str = "",
) -> tuple[list[dict], int]:
    tool_lines = (
        "\n".join(f"- {tool.code}: {tool.name} — {tool.description}" for tool in tools)
        or "（暂无可用工具）"
    )
    agent_lines = (
        "\n".join(
            f"- {agent.code}: {agent.name} — {agent.description}"
            f"（能力: {', '.join(agent.capabilities) or '未声明'}）"
            for agent in (agents or [])
        )
        or "（暂无可用 Agent）"
    )
    knowledge_lines = (
        "\n".join(
            f"- {base.id}: {base.name} — {base.description or '无描述'}"
            for base in (knowledge_bases or [])
        )
        or "（暂无可用知识库）"
    )
    messages = [
        {
            "role": "system",
            "content": "你是数字员工的任务规划器，只输出 JSON，不要输出解释。",
        },
        {
            "role": "user",
            "content": (
                f"岗位：{employee.position or employee.name}\n"
                f"职责：{employee.description or ''}\n"
                f"【员工配置】\n{employee_context or '（未配置）'}\n"
                f"任务输入：{json.dumps(task_input, ensure_ascii=False)}\n"
                f"可用工具：\n{tool_lines}\n\n"
                f"可用 Agent：\n{agent_lines}\n\n"
                f"可用知识库：\n{knowledge_lines}\n\n"
                "请把任务拆解为可执行步骤，输出 JSON：\n"
                '{"steps":[{"name":"步骤名",'
                '"type":"tool|llm|human|agent|employee|knowledge|graph_rag",'
                '"tool_code":"工具编码或null","agent_code":"Agent 编码或null",'
                '"employee_code":"协作员工编码或null",'
                '"knowledge_base_id":"知识库 id 或 null","query":"知识检索词或 null",'
                '"max_hops":1,"answer":true,'
                '"arguments":{},"prompt":"llm 步骤提示词或 null","description":"说明"}]}\n'
                "要求：最多 8 步；涉及高风险、不可逆操作或 must_ask 清单时插入 human 步骤；"
                "不得规划 cannot_do 中的事项；工具和 Agent 只能从上面的列表中选择；"
                "agent 步骤必须填写 agent_code；employee 步骤必须填写 employee_code，"
                "表示把子任务委派给另一个数字员工；"
                "knowledge 步骤必须填写 knowledge_base_id 和 query；"
                "需要多跳关系推理时使用 graph_rag，填写 knowledge_base_id、query、max_hops。"
            ),
        },
    ]
    data, tokens = await chat_json(messages)
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise LLMError("规划结果为空")
    return steps, tokens


async def verify_task(employee, task_input: dict, results: list) -> tuple[dict, int]:
    messages = [
        {
            "role": "system",
            "content": "你是任务校验器，只输出 JSON，不要输出解释。",
        },
        {
            "role": "user",
            "content": (
                f"岗位：{employee.position or employee.name}\n"
                f"任务输入：{json.dumps(task_input, ensure_ascii=False)}\n"
                f"执行结果：{json.dumps(results, ensure_ascii=False)}\n"
                "请判断任务是否达成，输出 JSON："
                '{"passed": true/false, "reason": "原因", "suggestions": ["建议"]}'
            ),
        },
    ]
    data, tokens = await chat_json(messages)
    return data, tokens
