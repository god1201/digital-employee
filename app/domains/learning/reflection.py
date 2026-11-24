"""任务失败反思与自我修正。

设计：
- 规则先给出根因、修正提示与是否可自动重试；
- 可选 LLM 在规则基础上补充更具体的诊断，但只能收紧、不能放宽重试安全边界；
- 反思结果落 task_steps（step_type=reflection）并写入任务 output，供回放与归因使用。
"""

import logging

from app.core.config import settings
from app.core.llm import LLMError, chat_json, is_configured
from app.domains.learning.attribution import digest_value, steps_digest

logger = logging.getLogger(__name__)

REFLECTION_RULES: dict[str, dict] = {
    "knowledge_missing": {
        "diagnosis": "知识库缺少答案或文档缺失",
        "hint": "先补齐知识文档或改用已知口径，不要重复空检索",
        "retryable": False,
    },
    "retrieval_miss": {
        "diagnosis": "知识存在但未被召回",
        "hint": "换用更短更具体的检索词或同义词，必要时改用 graph_rag，不要重复同一查询",
        "retryable": True,
    },
    "tool_misuse": {
        "diagnosis": "工具调用失败、参数不符或连接异常",
        "hint": "检查工具参数与 Schema、服务可用性与连接；基础设施错误交给 Worker 重试",
        "retryable": False,
    },
    "planning_error": {
        "diagnosis": "计划缺失、步骤顺序错误或校验未通过",
        "hint": "重新规划并补齐缺失步骤，避免重复上次失败的步骤与参数",
        "retryable": True,
    },
    "style_mismatch": {
        "diagnosis": "内容正确但表达不符合人格风格",
        "hint": "技能层只输出结构化结果，由人格层统一润色，不要改动业务结构",
        "retryable": False,
    },
    "permission_violation": {
        "diagnosis": "触碰岗位契约或权限红线",
        "hint": "禁止自动重试，收紧契约与工具权限并转人工处理",
        "retryable": False,
    },
    "intent_misunderstanding": {
        "diagnosis": "需求意图不明确或存在歧义",
        "hint": "先澄清关键约束再规划；必要时插入 human 步骤",
        "retryable": True,
    },
    "unknown": {
        "diagnosis": "未知失败，现有信号不足以定位",
        "hint": "复盘错误与步骤输出，缩小范围后再试；仍失败则转人工",
        "retryable": True,
    },
}

NON_RETRYABLE_REFLECTION_MARKERS = (
    "未配置 llm_api_key",
    "岗位契约拦截",
    "访问被拒绝",
    "已取消",
    "工具不存在",
    "参数校验",
    "不支持的",
    "固定任务未配置",
    "未绑定数字员工",
    "预算超限",
    "预算已用完",
)


def rule_reflection(category: str, reason: str, suggestion: str = "") -> dict:
    rule = REFLECTION_RULES.get(category, REFLECTION_RULES["unknown"])
    lowered = (reason or "").lower()
    blocked = any(
        marker.lower() in lowered
        for marker in NON_RETRYABLE_REFLECTION_MARKERS
    )
    return {
        "category": category,
        "diagnosis": rule["diagnosis"],
        "hint": rule["hint"],
        "suggestions": [suggestion] if suggestion else [],
        "retryable": bool(rule["retryable"]) and not blocked,
        "source": "rule",
    }


async def llm_reflection(
    instance,
    steps: list,
    reason: str,
    category: str,
    suggestion: str = "",
) -> dict | None:
    """可选 LLM 反思；失败返回 None，由规则反思兜底。"""
    if not settings.reflection_llm_enabled or not is_configured():
        return None
    messages = [
        {
            "role": "system",
            "content": "你是数字员工的反思与修正器，只输出 JSON，不要输出解释。",
        },
        {
            "role": "user",
            "content": (
                f"任务：{getattr(instance, 'title', '')}\n"
                f"任务类型：{getattr(instance, 'task_type', '')}\n"
                f"输入：{digest_value(getattr(instance, 'input', {}) or {}, 600)}\n"
                f"失败类别：{category}\n"
                f"失败原因：{(reason or '')[:800]}\n"
                f"步骤轨迹：\n{steps_digest(steps)}\n"
                f"规则建议：{suggestion or '无'}\n\n"
                "请给出根因、给下次规划的具体修正提示、可执行建议，"
                "并判断是否适合自动重试。输出 JSON："
                '{"diagnosis":"根因","hint":"具体修正提示",'
                '"suggestions":["建议"],"retryable":true}'
            ),
        },
    ]
    try:
        data, _tokens = await chat_json(messages, timeout=60)
    except LLMError as exc:
        logger.warning("LLM 反思失败，回退规则: %s", exc)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("LLM 反思异常，回退规则")
        return None

    hint = str(data.get("hint") or "").strip()
    if not hint:
        return None
    raw_suggestions = data.get("suggestions") or []
    if not isinstance(raw_suggestions, list):
        raw_suggestions = [raw_suggestions]
    suggestions = [
        str(item).strip() for item in raw_suggestions if str(item).strip()
    ][:6]
    return {
        "diagnosis": str(data.get("diagnosis") or "").strip(),
        "hint": hint,
        "suggestions": suggestions,
        "retryable": data.get("retryable", True) is not False,
        "source": "llm",
    }


async def build_reflection(
    instance,
    steps: list,
    reason: str,
    category: str,
    suggestion: str = "",
) -> dict:
    rule = rule_reflection(category, reason, suggestion)
    llm = await llm_reflection(instance, steps, reason, category, suggestion)
    if llm is None:
        return rule
    return {
        **rule,
        "diagnosis": llm.get("diagnosis") or rule["diagnosis"],
        "hint": llm.get("hint") or rule["hint"],
        "suggestions": llm.get("suggestions") or rule["suggestions"],
        # LLM 只能收紧安全边界，不能把规则判定为不可重试的失败改成可重试。
        "retryable": rule["retryable"] and llm.get("retryable", True),
        "source": "llm",
    }
