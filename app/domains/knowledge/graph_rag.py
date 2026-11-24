"""GraphRAG：实体匹配 + 多跳图谱扩展 + 分块检索 + LLM 回答。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, chat_text, is_configured
from app.domains.knowledge.models import GraphEntity, GraphRelation
from app.domains.knowledge.service import search_knowledge, tokenize


def rank_entities(query: str, entities: list[dict], limit: int = 5) -> list[dict]:
    """按查询词与实体名的重叠程度排序，作为图谱扩展的种子节点。"""
    tokens = tokenize(query)
    query_lower = query.lower()
    scored: list[tuple[float, dict]] = []

    for entity in entities:
        name = str(entity.get("name") or "")
        name_lower = name.lower()
        if not name_lower:
            continue
        score = 0.0
        if query_lower and query_lower in name_lower:
            score += len(query_lower) * 3
        if name_lower in query_lower:
            score += len(name_lower) * 2
        for token in tokens:
            if token in name_lower:
                score += len(token)
        if score > 0:
            scored.append((score, entity))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [{**entity, "score": round(score, 2)} for score, entity in scored[:limit]]


def expand_neighborhood(
    seed_ids: set[int],
    relations: list[dict],
    max_hops: int = 1,
    max_nodes: int = 50,
    max_edges: int = 100,
) -> tuple[set[int], list[dict]]:
    nodes = set(seed_ids)
    edges: list[dict] = []
    frontier = set(seed_ids)
    hops = max(1, min(int(max_hops), 3))

    for _ in range(hops):
        next_frontier: set[int] = set()
        for relation in relations:
            source = relation["source"]
            target = relation["target"]
            if source not in frontier and target not in frontier:
                continue
            if relation not in edges:
                edges.append(relation)
            for node in (source, target):
                if node not in nodes and len(nodes) < max_nodes:
                    nodes.add(node)
                    next_frontier.add(node)
        frontier = next_frontier
        if not frontier or len(edges) >= max_edges:
            break

    return nodes, edges[:max_edges]


def build_context(
    entities: list[dict],
    relations: list[dict],
    chunks: list[dict],
    max_chars: int = 8000,
) -> str:
    lines: list[str] = []

    if relations:
        lines.append("知识图谱关系：")
        for relation in relations:
            lines.append(
                f"- {relation['source_name']} [{relation['source_type']}] "
                f"--{relation['type']}--> "
                f"{relation['target_name']} [{relation['target_type']}]"
            )
    elif entities:
        lines.append("知识图谱实体：")
        for entity in entities:
            lines.append(f"- {entity['name']} [{entity['type']}]")

    if chunks:
        lines.append("知识片段：")
        for chunk in chunks:
            lines.append(f"- 《{chunk['document_title']}》{chunk['content'][:1200]}")

    return "\n".join(lines)[:max_chars]


async def graph_rag(
    db: AsyncSession,
    tenant_id: int,
    base_id: int,
    query: str,
    top_k: int = 5,
    max_hops: int = 1,
    answer: bool = True,
) -> dict:
    entity_rows = list(
        (
            await db.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.tenant_id == tenant_id,
                    GraphEntity.base_id == base_id,
                )
                .limit(2000)
            )
        ).all()
    )
    relation_rows = list(
        (
            await db.scalars(
                select(GraphRelation)
                .where(
                    GraphRelation.tenant_id == tenant_id,
                    GraphRelation.base_id == base_id,
                )
                .limit(5000)
            )
        ).all()
    )

    entities = [
        {
            "id": entity.id,
            "name": entity.name,
            "type": entity.entity_type,
            "properties": entity.properties,
        }
        for entity in entity_rows
    ]
    relations = [
        {
            "id": relation.id,
            "source": relation.source_id,
            "target": relation.target_id,
            "type": relation.relation_type,
        }
        for relation in relation_rows
    ]

    seeds = rank_entities(query, entities)
    seed_ids = {seed["id"] for seed in seeds}
    node_ids, edge_dicts = expand_neighborhood(seed_ids, relations, max_hops)

    by_id = {entity["id"]: entity for entity in entities}
    selected_entities = [by_id[node_id] for node_id in node_ids if node_id in by_id]
    selected_relations = []
    for edge in edge_dicts:
        source = by_id.get(edge["source"])
        target = by_id.get(edge["target"])
        if source is None or target is None:
            continue
        selected_relations.append(
            {
                **edge,
                "source_name": source["name"],
                "source_type": source["type"],
                "target_name": target["name"],
                "target_type": target["type"],
            }
        )

    chunks = await search_knowledge(db, tenant_id, base_id, query, top_k=top_k, mode="auto")
    context = build_context(selected_entities, selected_relations, chunks)

    answer_text: str | None = None
    answer_error: str | None = None
    tokens = 0

    if answer:
        if is_configured():
            try:
                answer_text, tokens = await chat_text(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是知识库问答助手。只根据提供的上下文回答，不要编造。"
                                "如果上下文不足，请明确说明。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"问题：{query}\n\n上下文：\n{context or '（无可用上下文）'}"
                            ),
                        },
                    ],
                    timeout=90,
                )
            except LLMError as exc:
                answer_error = str(exc)
        else:
            answer_error = "未配置 LLM_API_KEY"

    return {
        "query": query,
        "max_hops": max_hops,
        "seed_entities": seeds,
        "entities": selected_entities,
        "relations": selected_relations,
        "chunks": chunks,
        "context": context,
        "answer": answer_text,
        "answer_error": answer_error,
        "tokens": tokens,
    }
