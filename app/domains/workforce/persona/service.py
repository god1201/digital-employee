"""人格层读写、上下文生成、禁忌词检查与统一润色。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, chat_text, is_configured
from app.domains.workforce.persona.models import PersonaProfile
from app.domains.workforce.persona.schemas import PersonaUpsert

TONE_LABELS = {
    "professional": "专业克制",
    "friendly": "亲和友好",
    "concise": "极简直接",
    "formal": "正式书面",
}
FORMAT_LABELS = {
    "conclusion_first": "结论先行，再给依据",
    "bullets": "要点列表",
    "table": "表格优先，表格不超过 5 列",
    "detailed": "详细论证",
}
REPORT_LABELS = {
    "conclusion_first": "结论 + 依据 + 下一步",
    "detailed": "完整背景、分析与建议",
    "bullets": "短要点汇报",
}


async def get_persona(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> PersonaProfile | None:
    return await db.scalar(
        select(PersonaProfile).where(
            PersonaProfile.tenant_id == tenant_id,
            PersonaProfile.employee_id == employee_id,
        )
    )


async def upsert_persona(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    payload: PersonaUpsert,
    *,
    user_id: int | None = None,
) -> PersonaProfile:
    persona = await get_persona(db, tenant_id, employee_id)
    values = payload.model_dump()
    if persona is None:
        persona = PersonaProfile(
            tenant_id=tenant_id,
            employee_id=employee_id,
            created_by=user_id,
            **values,
        )
        db.add(persona)
    else:
        for field, value in values.items():
            setattr(persona, field, value)
        persona.version += 1
    await db.flush()
    return persona


def build_persona_context(persona: PersonaProfile | None) -> str:
    if persona is None:
        return ""
    lines = [
        "【人格表现层】",
        f"语气：{TONE_LABELS.get(persona.tone, persona.tone)}",
        f"输出格式：{FORMAT_LABELS.get(persona.output_format, persona.output_format)}",
        f"汇报风格：{REPORT_LABELS.get(persona.report_style, persona.report_style)}",
    ]
    if persona.address_style:
        lines.append(f"称呼习惯：{persona.address_style}")
    if persona.taboo_words:
        lines.append(f"禁忌词：{'、'.join(str(item) for item in persona.taboo_words)}")
    if persona.signature:
        lines.append(f"落款：{persona.signature}")
    if persona.extra_instructions:
        lines.append(f"额外要求：{persona.extra_instructions}")
    lines.append("技能只输出结构化结果，由本层统一润色；不得改变事实与权限边界。")
    return "\n".join(lines)


def find_taboo(text: str, persona: PersonaProfile | None) -> list[str]:
    if persona is None or not text:
        return []
    lowered = text.lower()
    return [
        str(word)
        for word in (persona.taboo_words or [])
        if word and str(word).lower() in lowered
    ]


async def polish_text(
    text: str, persona: PersonaProfile | None
) -> tuple[str, list[str]]:
    """按人格层润色；未开启或未配置 LLM 时原样返回。"""
    if not text:
        return text, []
    hits = find_taboo(text, persona)
    if persona is None or not persona.polish_enabled or not is_configured():
        return text, hits
    instructions = build_persona_context(persona)
    try:
        polished, _tokens = await chat_text(
            [
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\n只输出润色后的正文，不要解释，不要改变事实、"
                        "数字、结论和权限边界。"
                    ),
                },
                {"role": "user", "content": text},
            ]
        )
    except LLMError:
        return text, hits
    return polished, find_taboo(polished, persona)


async def load_persona_context(
    db: AsyncSession, tenant_id: int, employee_id: int | None
) -> str:
    if not employee_id:
        return ""
    persona = await get_persona(db, tenant_id, employee_id)
    return build_persona_context(persona)
