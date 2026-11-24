"""入职引导：JD/SOP 抽取岗位契约草稿、导入知识库、沉淀示范案例。"""

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, chat_json, is_configured
from app.domains.knowledge.embedding import embed_texts
from app.domains.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.domains.knowledge.service import chunk_text
from app.domains.knowledge.vector_store import upsert_chunk_vectors
from app.domains.learning.schemas import OnboardingExtractResult
from app.domains.workforce.contracts.models import JobContract
from app.domains.workforce.contracts.service import get_contract

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.、)]|\([一二三四五六七八九十]+\))\s*")
_CANNOT = ("不能", "不得", "禁止", "不可", "严禁", "无权")
_MUST_ASK = ("请示", "审批", "上报", "升级", "超过", "超出", "特批", "确认后")
_ROLE_PREFIX = re.compile(r"^(?:岗位|职位|角色|职位名称)\s*[:：]\s*")


def _clean(line: str) -> str:
    return _BULLET.sub("", line).strip()


def extract_contract_heuristic(text: str) -> dict:
    lines = [_clean(line) for line in text.splitlines() if line.strip()]
    role = ""
    if lines:
        first = lines[0]
        if len(first) <= 64:
            role = _ROLE_PREFIX.sub("", first)
    can_do: list[str] = []
    cannot_do: list[str] = []
    must_ask: list[str] = []
    for line in lines[1:]:
        if any(marker in line for marker in _CANNOT):
            cannot_do.append(line[:200])
        elif any(marker in line for marker in _MUST_ASK):
            must_ask.append(line[:200])
        elif len(can_do) < 15:
            can_do.append(line[:200])
    return {
        "role": role[:128],
        "can_do": can_do,
        "cannot_do": cannot_do,
        "must_ask": must_ask,
        "kpi": {},
        "source": "heuristic",
    }


async def extract_contract(text: str, source_type: str) -> dict:
    if not is_configured():
        return extract_contract_heuristic(text)
    prompt = (
        "你是岗位契约抽取器。根据以下入职资料抽取岗位契约，只输出 JSON："
        '{"role":"岗位","can_do":["..."],"cannot_do":["..."],'
        '"must_ask":["..."],"kpi":{"指标":"目标"}}。'
        "不能做与必须请示要严格区分：涉及金额、减免、对外披露、越权操作的要进入 must_ask。"
        f"\n资料类型：{source_type}\n资料：\n{text[:12000]}"
    )
    try:
        data, _tokens = await chat_json(
            [
                {"role": "system", "content": "只输出 JSON。"},
                {"role": "user", "content": prompt},
            ]
        )
    except LLMError:
        return extract_contract_heuristic(text)

    def _list(key: str) -> list[str]:
        value = data.get(key)
        if not isinstance(value, list):
            return []
        return [str(item)[:200] for item in value if str(item).strip()][:20]

    kpi = data.get("kpi")
    return {
        "role": str(data.get("role") or "")[:128],
        "can_do": _list("can_do"),
        "cannot_do": _list("cannot_do"),
        "must_ask": _list("must_ask"),
        "kpi": kpi if isinstance(kpi, dict) else {},
        "source": "llm",
    }


async def apply_contract_draft(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    extracted: dict,
    *,
    user_id: int | None = None,
) -> JobContract:
    contract = await get_contract(db, tenant_id, employee_id)
    if contract is None:
        contract = JobContract(
            tenant_id=tenant_id,
            employee_id=employee_id,
            role=extracted.get("role", ""),
            can_do=extracted.get("can_do", []),
            cannot_do=extracted.get("cannot_do", []),
            must_ask=extracted.get("must_ask", []),
            kpi=extracted.get("kpi", {}),
            autonomy_level="L2",
            red_lines={},
            status="draft",
            created_by=user_id,
        )
        db.add(contract)
    else:
        contract.role = extracted.get("role") or contract.role
        contract.can_do = extracted.get("can_do") or contract.can_do
        contract.cannot_do = extracted.get("cannot_do") or contract.cannot_do
        contract.must_ask = extracted.get("must_ask") or contract.must_ask
        contract.kpi = extracted.get("kpi") or contract.kpi
        contract.status = "draft"
        contract.version += 1
    await db.flush()
    return contract


async def import_knowledge_document(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    title: str,
    text: str,
    *,
    user_id: int | None = None,
    source: str = "onboarding",
) -> KnowledgeDocument:
    base = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == base_id, KnowledgeBase.tenant_id == tenant_id
        )
    )
    if base is None:
        raise ValueError("知识库不存在")
    chunks = chunk_text(text)
    vectors, model = await embed_texts(chunks)
    document = KnowledgeDocument(
        tenant_id=tenant_id,
        base_id=base.id,
        title=title[:255],
        content=text,
        source=source,
        chunk_count=len(chunks),
        created_by=user_id,
    )
    db.add(document)
    await db.flush()
    chunk_rows = []
    for index, chunk in enumerate(chunks):
        row = KnowledgeChunk(
            tenant_id=tenant_id,
            base_id=base.id,
            document_id=document.id,
            chunk_index=index,
            content=chunk,
            embedding=vectors[index] if index < len(vectors) else [],
            embedding_model=model,
        )
        db.add(row)
        chunk_rows.append(row)
    await db.flush()
    await upsert_chunk_vectors(db, chunk_rows, vectors, model)
    return document


def result_payload(extracted: dict, **extra) -> OnboardingExtractResult:
    return OnboardingExtractResult(
        role=extracted.get("role", ""),
        can_do=extracted.get("can_do", []),
        cannot_do=extracted.get("cannot_do", []),
        must_ask=extracted.get("must_ask", []),
        kpi=extracted.get("kpi", {}),
        source=extracted.get("source", "heuristic"),
        **extra,
    )


def dumps_extracted(extracted: dict) -> str:
    return json.dumps(extracted, ensure_ascii=False)
