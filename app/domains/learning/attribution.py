"""失败归因与自动路由。

用户价值：不做归因，所有失败都会被塞进 Prompt，最终膨胀到互相打架。
默认用确定性规则覆盖最常见类别；配置 LLM 后可对低置信度归因做复核，
LLM 失败时始终回退规则，不阻断任务失败链路。
"""

import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.llm import LLMError, chat_json, is_configured
from app.domains.learning.models import FailureAttribution, InterventionDelta
from app.domains.workflows.tasks.models import TaskInstance, TaskStep

logger = logging.getLogger(__name__)

ROUTES: dict[str, tuple[str, str]] = {
    "knowledge_missing": (
        "create_knowledge_ticket",
        "生成知识缺口工单：补齐文档并重建索引，再重跑同类任务",
    ),
    "retrieval_miss": (
        "retune_chunk",
        "库里有但没召回：调整分块、同义词与 Rerank，不要改 Prompt",
    ),
    "tool_misuse": (
        "fix_tool_schema",
        "修正工具 Schema 描述、参数校验与示例，必要时给工具加兜底",
    ),
    "planning_error": (
        "add_sop_step",
        "补 SOP 节点或 Few-shot 轨迹，明确步骤顺序与前置条件",
    ),
    "style_mismatch": (
        "update_persona",
        "内容正确但被改写：更新人格层风格卡，不要动技能逻辑",
    ),
    "permission_violation": (
        "tighten_permission",
        "触碰权限红线：收紧契约与工具权限并告警，禁止进入学习",
    ),
    "intent_misunderstanding": (
        "collect_intent_samples",
        "补充意图样例与澄清话术，必要时先反问再执行",
    ),
    "unknown": ("manual_review", "无法自动归因，转人工复核并补充规则"),
}

PERMISSION_MARKERS = (
    "岗位契约拦截",
    "访问被拒绝",
    "默认拒绝",
    "禁止",
    "越权",
    "权限",
)
TOOL_MARKERS = (
    "工具不存在",
    "工具执行",
    "参数",
    "schema",
    "HTTP 4",
    "HTTP 5",
    "超时",
    "连接失败",
)
PLANNING_MARKERS = (
    "规划结果为空",
    "没有可执行的步骤",
    "步骤未全部完成",
    "固定任务未配置",
)
INTENT_MARKERS = ("意图", "无法理解", "歧义", "需求不明确")

TEXT_KEYS = {
    "text",
    "content",
    "answer",
    "summary",
    "body",
    "title",
    "description",
    "reply",
    "message",
}


LLM_CATEGORY_GUIDE = """
- knowledge_missing 知识缺失：知识库里确实没有答案或文档缺失
- retrieval_miss 检索未召回：库里应有但没有召回，或相似度过低
- tool_misuse 工具用错：工具 Schema、参数、超时、连接或执行失败
- planning_error 规划错误：步骤缺失、顺序错误或固定任务未配置
- style_mismatch 风格不符：内容正确但被人工改写表述
- permission_violation 越权/合规：触碰契约红线，禁止进入学习
- intent_misunderstanding 理解偏差：需求歧义或意图识别错误
- unknown 无法从现有信息判断
""".strip()


def _route(category: str) -> tuple[str, str]:
    return ROUTES.get(category, ROUTES["unknown"])


def digest_value(value, limit: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:limit]


def steps_digest(steps: list[TaskStep], limit: int = 12) -> str:
    lines: list[str] = []
    for step in steps[:limit]:
        line = (
            f"#{step.step_index} {step.name} [{step.step_type}] "
            f"status={step.status}"
        )
        if step.error:
            line += f" error={str(step.error)[:240]}"
        if step.output:
            line += f" output={digest_value(step.output, 320)}"
        lines.append(line)
    return "\n".join(lines) or "（无步骤记录）"


def _llm_context(
    *,
    instance: TaskInstance | None = None,
    steps: list[TaskStep] | None = None,
    intervention: InterventionDelta | None = None,
    error: str | None = None,
) -> str:
    parts: list[str] = []
    if instance is not None:
        parts.append(f"任务：{instance.title}")
        parts.append(f"任务类型：{instance.task_type}，状态：{instance.status}")
        if instance.input:
            parts.append(f"输入：{digest_value(instance.input)}")
        if instance.plan:
            plan = [
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "tool_code": item.get("tool_code"),
                }
                for item in instance.plan[:12]
                if isinstance(item, dict)
            ]
            parts.append(f"计划：{digest_value(plan)}")
        if error or instance.error:
            parts.append(f"错误：{str(error or instance.error)[:800]}")
    if steps:
        parts.append("步骤：\n" + steps_digest(steps))
    if intervention is not None:
        parts.append(f"人工接管 diff：{digest_value(intervention.diff, 1200)}")
    return "\n".join(parts) or "（无现场信息）"


async def classify_failure_llm(
    *,
    instance: TaskInstance | None = None,
    steps: list[TaskStep] | None = None,
    intervention: InterventionDelta | None = None,
    error: str | None = None,
) -> dict | None:
    """用 LLM 归因；未配置或失败时返回 None，由调用方回退规则。"""
    if not is_configured():
        return None
    context = _llm_context(
        instance=instance,
        steps=steps,
        intervention=intervention,
        error=error,
    )
    messages = [
        {
            "role": "system",
            "content": "你是数字员工失败归因器，只输出 JSON，不要输出解释。",
        },
        {
            "role": "user",
            "content": (
                f"可选类别：\n{LLM_CATEGORY_GUIDE}\n\n"
                f"现场信息：\n{context}\n\n"
                "请判断最可能的失败类别，并给出证据与修复建议。输出 JSON："
                '{"category":"类别代码","confidence":0.0,'
                '"signals":["判定信号"],"suggestion":"修复建议"}'
            ),
        },
    ]
    try:
        data, _tokens = await chat_json(messages, timeout=60)
    except LLMError as exc:
        logger.warning("LLM 归因失败，回退规则: %s", exc)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("LLM 归因异常，回退规则")
        return None

    category = str(data.get("category") or "").strip()
    if category not in ROUTES:
        logger.warning("LLM 归因返回未知类别: %s", category)
        return None
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    raw_signals = data.get("signals") or []
    if not isinstance(raw_signals, list):
        raw_signals = [raw_signals]
    signals = [str(item).strip() for item in raw_signals if str(item).strip()][:8]
    signals.insert(0, "LLM 归因")

    routed_action, fallback_suggestion = _route(category)
    suggestion = str(data.get("suggestion") or "").strip() or fallback_suggestion
    return {
        "category": category,
        "confidence": round(confidence, 4),
        "signals": signals,
        "suggestion": suggestion[:512],
        "routed_action": routed_action,
    }


def _apply_llm_result(attribution: FailureAttribution, result: dict) -> None:
    previous = f"{attribution.category}/{float(attribution.confidence or 0):.2f}"
    attribution.category = result["category"]
    attribution.confidence = result["confidence"]
    signals = list(result.get("signals") or [])
    signals.append(f"LLM 复核：原 {previous}，来源 {attribution.source}")
    attribution.signals = signals
    attribution.suggestion = result["suggestion"]
    attribution.routed_action = result["routed_action"]
    attribution.source = "llm"
    attribution.status = "new"


async def reanalyze_attribution_llm(
    db: AsyncSession,
    attribution: FailureAttribution,
    *,
    user_id: int | None = None,
) -> FailureAttribution:
    """用 LLM 复核一条归因；失败时抛 LLMError，保留原记录。"""
    if not is_configured():
        raise LLMError("未配置 LLM_API_KEY，无法使用 LLM 归因")
    if attribution.category == "permission_violation":
        raise LLMError("越权/合规类失败不进入 LLM 学习复核")
    if attribution.artifact_id is not None:
        raise LLMError("该归因已生成学习工件，请先回滚工件后再复核")

    instance = None
    steps: list[TaskStep] = []
    intervention = None
    if attribution.instance_id is not None:
        instance = await db.scalar(
            select(TaskInstance).where(
                TaskInstance.id == attribution.instance_id,
                TaskInstance.tenant_id == attribution.tenant_id,
            )
        )
        if instance is not None:
            steps = list(
                (
                    await db.scalars(
                        select(TaskStep)
                        .where(TaskStep.instance_id == instance.id)
                        .order_by(TaskStep.step_index)
                    )
                ).all()
            )
    elif attribution.intervention_id is not None:
        intervention = await db.scalar(
            select(InterventionDelta).where(
                InterventionDelta.id == attribution.intervention_id,
                InterventionDelta.tenant_id == attribution.tenant_id,
            )
        )
    if instance is None and intervention is None:
        raise LLMError("归因缺少任务或接管记录，无法复核")

    result = await classify_failure_llm(
        instance=instance,
        steps=steps,
        intervention=intervention,
        error=instance.error if instance is not None else None,
    )
    if result is None:
        raise LLMError("LLM 未返回合法归因")
    _apply_llm_result(attribution, result)
    if user_id is not None:
        attribution.created_by = attribution.created_by or user_id
    await db.flush()
    return attribution


async def upgrade_rule_attributions(
    db: AsyncSession,
    *,
    lookback_hours: int = 24,
    tenant_id: int | None = None,
    limit: int | None = None,
) -> dict:
    """日结批次用 LLM 复核低置信度规则归因（未配置时直接跳过）。"""
    if not settings.llm_attribution_enabled or not is_configured():
        return {"enabled": False, "scanned": 0, "upgraded": 0, "items": []}

    cutoff = utcnow() - timedelta(hours=max(1, lookback_hours))
    conditions = [
        FailureAttribution.created_at >= cutoff,
        FailureAttribution.source == "rule",
        FailureAttribution.confidence < settings.llm_attribution_min_confidence,
        FailureAttribution.artifact_id.is_(None),
        FailureAttribution.status != "resolved",
        FailureAttribution.category != "permission_violation",
    ]
    if tenant_id is not None:
        conditions.append(FailureAttribution.tenant_id == tenant_id)
    rows = list(
        (
            await db.scalars(
                select(FailureAttribution)
                .where(*conditions)
                .order_by(FailureAttribution.id.desc())
                .limit(
                    limit
                    or max(1, settings.llm_attribution_max_per_run)
                )
            )
        ).all()
    )

    upgraded: list[dict] = []
    for attribution in rows:
        try:
            await reanalyze_attribution_llm(db, attribution)
        except LLMError as exc:
            logger.info("跳过 LLM 归因复核 #%s: %s", attribution.id, exc)
            continue
        upgraded.append(
            {
                "attribution_id": attribution.id,
                "category": attribution.category,
                "confidence": attribution.confidence,
            }
        )
    return {
        "enabled": True,
        "scanned": len(rows),
        "upgraded": len(upgraded),
        "items": upgraded,
    }


def _last_segment(path: str) -> str:
    return path.split(".")[-1].split("[")[0]


def _all_text_changes(diff: list[dict]) -> bool:
    if not diff:
        return False
    for item in diff:
        if item.get("op") != "change":
            return False
        path = str(item.get("path") or "")
        if path and _last_segment(path) not in TEXT_KEYS:
            return False
    return True


def _knowledge_signals(steps: list[TaskStep]) -> tuple[bool, bool, list[str]]:
    missing = False
    weak = False
    signals: list[str] = []
    for step in steps:
        if step.step_type not in {"knowledge", "graph_rag"}:
            continue
        results = (step.output or {}).get("results") or []
        if not results:
            missing = True
            signals.append(f"步骤「{step.name}」检索结果为空")
            continue
        try:
            top_score = max(float(item.get("score") or 0) for item in results)
        except (TypeError, ValueError):
            top_score = 0.0
        if top_score < 0.35:
            weak = True
            signals.append(f"步骤「{step.name}」Top1 相似度仅 {top_score:.2f}")
    return missing, weak, signals


def classify_failure(
    *,
    instance: TaskInstance | None = None,
    steps: list[TaskStep] | None = None,
    intervention: InterventionDelta | None = None,
    error: str | None = None,
) -> dict:
    """返回 {category, confidence, signals, suggestion, routed_action}。"""
    steps = steps or []
    error_text = " ".join(
        [error or "", *[str(step.error or "") for step in steps]]
    ).strip()
    signals: list[str] = []

    if any(marker in error_text for marker in PERMISSION_MARKERS):
        category, confidence = "permission_violation", 0.95
        signals.append(f"错误信息命中权限标记：{error_text[:160]}")
    else:
        failed_tool = next(
            (
                step
                for step in steps
                if step.step_type == "tool" and str(step.status) == "failed"
            ),
            None,
        )
        knowledge_missing, retrieval_weak, knowledge_signals = _knowledge_signals(steps)

        if failed_tool is not None and any(
            marker in str(failed_tool.error or "") for marker in TOOL_MARKERS
        ):
            category, confidence = "tool_misuse", 0.85
            signals.append(f"工具步骤失败：{str(failed_tool.error or '')[:160]}")
        elif knowledge_missing:
            category, confidence = "knowledge_missing", 0.9
            signals.extend(knowledge_signals)
        elif retrieval_weak:
            category, confidence = "retrieval_miss", 0.75
            signals.extend(knowledge_signals)
        elif any(marker in error_text for marker in PLANNING_MARKERS):
            category, confidence = "planning_error", 0.85
            signals.append(f"规划校验失败：{error_text[:160]}")
        elif intervention is not None and _all_text_changes(list(intervention.diff or [])):
            category, confidence = "style_mismatch", 0.75
            signals.append("人工接管只改写了文本表述，未改变结构或步骤")
        elif intervention is not None and intervention.diff:
            category, confidence = "planning_error", 0.6
            signals.append("人工接管新增/删除了字段或步骤，疑似规划缺失")
        elif any(marker in error_text for marker in INTENT_MARKERS):
            category, confidence = "intent_misunderstanding", 0.7
            signals.append(f"意图识别失败：{error_text[:160]}")
        elif failed_tool is not None:
            category, confidence = "tool_misuse", 0.6
            signals.append(f"工具步骤失败：{str(failed_tool.error or '')[:160]}")
        elif instance is not None and not (instance.plan or []):
            category, confidence = "planning_error", 0.7
            signals.append("任务没有固化执行计划")
        else:
            category, confidence = "unknown", 0.3
            signals.append("未命中已知归因规则")

    routed_action, suggestion = _route(category)
    if intervention is not None:
        signals.append(f"接管 diff {len(intervention.diff or [])} 处变更")
    return {
        "category": category,
        "confidence": confidence,
        "signals": signals,
        "suggestion": suggestion,
        "routed_action": routed_action,
    }


def classify_for_intervention(intervention: InterventionDelta) -> dict:
    return classify_failure(intervention=intervention)


async def attribute_instance_failure(
    db: AsyncSession,
    instance: TaskInstance,
    *,
    error: str | None = None,
    user_id: int | None = None,
    use_llm: bool = False,
) -> FailureAttribution:
    # 同一任务实例只保留一条失败归因；重试/反思重复触发时返回已有记录。
    existing = await db.scalar(
        select(FailureAttribution)
        .where(FailureAttribution.instance_id == instance.id)
        .order_by(FailureAttribution.id.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    steps = list(
        (
            await db.scalars(
                select(TaskStep)
                .where(TaskStep.instance_id == instance.id)
                .order_by(TaskStep.step_index)
            )
        ).all()
    )
    failed_step = next((step for step in steps if step.status == "failed"), None)
    result = None
    if use_llm:
        result = await classify_failure_llm(
            instance=instance, steps=steps, error=error or instance.error
        )
    source = "llm" if result is not None else "rule"
    if result is None:
        result = classify_failure(
            instance=instance, steps=steps, error=error or instance.error
        )
    attribution = FailureAttribution(
        tenant_id=instance.tenant_id,
        employee_id=instance.employee_id,
        instance_id=instance.id,
        step_id=failed_step.id if failed_step is not None else None,
        trace_id=instance.trace_id,
        source=source,
        created_by=user_id,
        **result,
    )
    db.add(attribution)
    await db.flush()
    return attribution


async def attribute_intervention(
    db: AsyncSession,
    intervention: InterventionDelta,
    *,
    user_id: int | None = None,
    use_llm: bool = False,
) -> FailureAttribution:
    result = None
    if use_llm:
        result = await classify_failure_llm(intervention=intervention)
    source = "llm" if result is not None else "rule"
    if result is None:
        result = classify_for_intervention(intervention)
    attribution = FailureAttribution(
        tenant_id=intervention.tenant_id,
        employee_id=intervention.employee_id,
        instance_id=intervention.instance_id,
        step_id=intervention.step_id,
        intervention_id=intervention.id,
        trace_id=intervention.trace_id,
        source=source,
        created_by=user_id,
        **result,
    )
    db.add(attribution)
    await db.flush()
    return attribution


TARGET_LAYER_BY_CATEGORY = {
    "knowledge_missing": "semantic_memory",
    "retrieval_miss": "semantic_memory",
    "style_mismatch": "persona_layer",
    "tool_misuse": "tool_config",
    "permission_violation": "tool_config",
    "planning_error": "procedural_memory",
    "intent_misunderstanding": "persona_layer",
    "unknown": "procedural_memory",
}

RISK_BY_CATEGORY = {
    "style_mismatch": "low",
    "knowledge_missing": "low",
    "retrieval_miss": "low",
    "tool_misuse": "medium",
    "planning_error": "medium",
    "intent_misunderstanding": "low",
    "permission_violation": "high",
    "unknown": "medium",
}


def attribution_artifact_payload(
    attribution: FailureAttribution,
    *,
    target_layer: str | None = None,
    proposal: dict | None = None,
    scope: str = "personal",
) -> dict:
    """把归因结果转成学习工件创建参数。"""
    evidence = list(attribution.signals or [])
    evidence.append(attribution.suggestion)
    category = attribution.category or "unknown"
    return {
        "employee_id": attribution.employee_id,
        "source": {
            "type": "failure_attribution",
            "attribution_id": attribution.id,
            "instance_id": attribution.instance_id,
            "intervention_id": attribution.intervention_id,
            "trace_id": attribution.trace_id,
        },
        "attribution": category,
        "target_layer": target_layer or TARGET_LAYER_BY_CATEGORY.get(
            category, "procedural_memory"
        ),
        "proposal": proposal
        or {
            "action": attribution.routed_action,
            "content": attribution.suggestion,
        },
        "evidence": evidence,
        "risk": RISK_BY_CATEGORY.get(category, "medium"),
        "scope": scope,
        "status": "pending_approval",
    }


def route_label(category: str) -> tuple[str, str]:
    """供前端/接口展示的类别中文名与修复动作。"""
    labels = {
        "knowledge_missing": "知识缺失",
        "retrieval_miss": "检索未召回",
        "tool_misuse": "工具用错",
        "planning_error": "规划错误",
        "style_mismatch": "风格不符",
        "permission_violation": "越权/合规",
        "intent_misunderstanding": "理解偏差",
        "unknown": "未知",
    }
    return labels.get(category, category), ROUTES.get(category, ROUTES["unknown"])[0]
