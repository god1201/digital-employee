"""示范库：把入职案例注入规划与 LLM 步骤的 Few-shot 上下文。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.learning.models import FewShotExample

MAX_EXAMPLES = 5
MAX_CHARS = 600


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def active_examples(
    db: AsyncSession, tenant_id: int, employee_id: int | None, limit: int = 3
) -> list[FewShotExample]:
    if not employee_id:
        return []
    return list(
        (
            await db.scalars(
                select(FewShotExample)
                .where(
                    FewShotExample.tenant_id == tenant_id,
                    FewShotExample.employee_id == employee_id,
                    FewShotExample.enabled.is_(True),
                )
                .order_by(FewShotExample.id.desc())
                .limit(max(1, min(limit, MAX_EXAMPLES)))
            )
        ).all()
    )


def build_few_shot_context(examples: list[FewShotExample]) -> str:
    if not examples:
        return ""
    lines = ["【示范案例（参考做法，不要照抄事实）】"]
    for index, example in enumerate(examples, start=1):
        lines.append(f"{index}. 输入：{_clip(example.input)}")
        lines.append(f"   期望输出：{_clip(example.output)}")
    return "\n".join(lines)


async def load_few_shot_context(
    db: AsyncSession, tenant_id: int, employee_id: int | None, limit: int = 3
) -> str:
    return build_few_shot_context(
        await active_examples(db, tenant_id, employee_id, limit)
    )
