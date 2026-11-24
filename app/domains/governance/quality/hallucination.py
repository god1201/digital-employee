"""幻觉检测：按答案句子与来源的证据重合度估算支撑度。"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance.quality.models import HallucinationCheck
from app.domains.governance.quality.schemas import HallucinationCheckRequest
from app.domains.knowledge.service import tokenize

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")
SUPPORT_THRESHOLD = 0.35
GROUNDED_THRESHOLD = 0.6


def split_sentences(answer: str) -> list[str]:
    return [item.strip() for item in _SENTENCE_SPLIT.split(answer) if item.strip()]


def score_grounding(answer: str, sources: list[str]) -> dict:
    sentences = split_sentences(answer)
    source_tokens = [set(tokenize(str(source))) for source in sources if source]
    if not sentences or not source_tokens:
        return {
            "score": 0.0,
            "grounded": False,
            "details": [],
            "sentences": len(sentences),
        }

    details = []
    supported = 0
    for sentence in sentences:
        tokens = set(tokenize(sentence))
        if not tokens:
            continue
        best = 0.0
        for candidate in source_tokens:
            overlap = len(tokens & candidate) / len(tokens)
            if overlap > best:
                best = overlap
        grounded = best >= SUPPORT_THRESHOLD
        if grounded:
            supported += 1
        details.append(
            {
                "sentence": sentence[:300],
                "support": round(best, 4),
                "grounded": grounded,
            }
        )

    total = len(details) or 1
    score = round(supported / total, 4)
    return {
        "score": score,
        "grounded": score >= GROUNDED_THRESHOLD,
        "details": details,
        "sentences": len(details),
    }


async def run_check(
    db: AsyncSession,
    tenant_id: int,
    payload: HallucinationCheckRequest,
    *,
    user_id: int | None = None,
) -> HallucinationCheck:
    result = score_grounding(payload.answer, payload.sources)
    record = HallucinationCheck(
        tenant_id=tenant_id,
        employee_id=payload.employee_id,
        instance_id=payload.instance_id,
        question=payload.question,
        answer=payload.answer,
        sources=payload.sources,
        score=result["score"],
        grounded=result["grounded"],
        details=result["details"],
        created_by=user_id,
    )
    db.add(record)
    await db.flush()
    return record
