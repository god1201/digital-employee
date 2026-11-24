"""统一的员工提示词装配：人格、契约、偏好、技能、经验、示范与路由。"""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tokenizer import count_tokens
from app.domains.learning.fewshot import load_few_shot_context
from app.domains.learning.rollout import load_artifacts_context
from app.domains.learning.service import active_preferences, build_preference_context
from app.domains.workforce.contracts.service import (
    build_contract_context,
    get_active_contract,
)
from app.domains.workforce.persona.service import load_persona_context
from app.domains.workforce.routing import build_routing_context


def estimate_tokens(text: str, *, model: str | None = None) -> int:
    """兼容旧调用：优先真实 tokenizer，缺失时回退字符估算。"""
    return count_tokens(text, model=model)


def _truncate_to_tokens(
    text: str,
    max_tokens: int,
    counter: Callable[[str], int],
) -> str:
    if max_tokens <= 0 or not text:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if counter(text[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def fit_sections(
    sections: list[tuple[str, str]],
    max_tokens: int,
    *,
    counter: Callable[[str], int] | None = None,
) -> str:
    """按顺序装配上下文；超出预算时按真实 token 截断最后一段并标注。"""
    if max_tokens <= 0:
        return "\n\n".join(text for _, text in sections if text)

    count = counter or count_tokens
    remaining = max_tokens
    parts: list[str] = []
    for _name, text in sections:
        if not text:
            continue
        tokens = count(text)
        if tokens <= remaining:
            parts.append(text)
            remaining -= tokens
            continue
        if remaining <= 0:
            break
        truncated = _truncate_to_tokens(text, remaining, count)
        if not truncated:
            break
        parts.append(truncated + "\n（该部分已按提示词预算压缩）")
        break
    return "\n\n".join(parts)


async def build_employee_prompt(
    db: AsyncSession,
    tenant_id: int,
    employee,
    *,
    trace_id: str | None = None,
    include_canary: bool = True,
    extra: str = "",
) -> str:
    base = employee.system_prompt or "你是一名数字员工。"
    contract = await get_active_contract(db, tenant_id, employee.id)
    persona = await load_persona_context(db, tenant_id, employee.id)
    preferences = await active_preferences(db, tenant_id, employee.id)
    preferences_text = build_preference_context(preferences)
    artifacts = await load_artifacts_context(
        db,
        tenant_id,
        employee.id,
        trace_id=trace_id,
        include_canary=include_canary,
    )
    few_shot = await load_few_shot_context(db, tenant_id, employee.id)
    routing = await build_routing_context(db, tenant_id, employee.id)

    # 延迟导入，避免 marketplace 与 prompting 的循环依赖
    from app.domains.skills.marketplace.service import build_skills_context

    skills = await build_skills_context(db, tenant_id, employee.id)

    sections = [
        ("契约", build_contract_context(contract) if contract is not None else ""),
        ("人格", persona),
        ("偏好", preferences_text),
        ("技能", skills),
        ("经验", artifacts),
        ("示范", few_shot),
        ("协作", routing),
    ]
    budget = int((employee.config or {}).get("prompt_token_budget") or 0)
    model = employee.model_name or None
    context = fit_sections(
        sections,
        budget,
        counter=lambda text: count_tokens(text, model=model),
    )
    if extra:
        context = f"{context}\n\n{extra}" if context else extra
    return f"{base}\n\n{context}" if context else base
