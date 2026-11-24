"""学习节奏自动化：日结批量归因、自动提问、周报生成与投递。

设计原则：
- 所有任务都幂等：失败任务已有归因则跳过，同周期周报已生成则跳过；
- 自动提问仍受每日预算约束，且静默跳过重复问题；
- 定时器只负责编排，具体统计复用 reviews / attribution / questions 模块；
- 时间统一按 UTC 解释，避免多实例部署时区漂移。
"""

import asyncio
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import BadRequestError
from app.domains.learning.attribution import (
    ROUTES,
    attribute_instance_failure,
    upgrade_rule_attributions,
)
from app.domains.learning.models import (
    FailureAttribution,
    LearningQuestion,
    WeeklyReview,
)
from app.domains.learning.questions import (
    budget_info,
    create_question,
)
from app.domains.learning.reviews import CATEGORY_LABELS, build_weekly_review
from app.domains.learning.schemas import LearningQuestionCreate
from app.domains.workflows.tasks.models import TaskInstance, TaskStep
from app.domains.workforce.employees.models import DigitalEmployee

logger = logging.getLogger(__name__)

AUTO_PREFIX = "（自动触发）"

# 进程内记录最近一次成功执行；定时器重启后依靠幂等查询兜底。
LAST_RUNS: dict[str, str] = {}


@dataclass
class AutoQuestion:
    kind: str
    employee_id: int
    instance_id: int | None
    question: str
    options: list[dict]
    default_option: str | None

    def as_item(self) -> dict:
        return {
            "kind": self.kind,
            "employee_id": self.employee_id,
            "instance_id": self.instance_id,
            "question": self.question,
        }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_hhmm(value: str | None) -> tuple[int, int] | None:
    if not value or ":" not in value:
        return None
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def week_start_of(value: datetime) -> datetime:
    current = _aware(value)
    return (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def daily_due(now: datetime, at: str, last_date: str | None) -> bool:
    """当天到点且当天尚未执行过。支持进程晚启动后的补跑。"""
    parsed = parse_hhmm(at)
    if parsed is None:
        return False
    current = _aware(now)
    scheduled = current.replace(
        hour=parsed[0], minute=parsed[1], second=0, microsecond=0
    )
    return current >= scheduled and last_date != current.date().isoformat()


def weekly_due(
    now: datetime,
    weekday: int,
    at: str,
    last_period_start: str | None,
) -> bool:
    """本周到点后执行一次，统计上一自然周；支持晚启动补跑。"""
    parsed = parse_hhmm(at)
    if parsed is None or not 0 <= weekday <= 6:
        return False
    current = _aware(now)
    scheduled = week_start_of(current) + timedelta(
        days=weekday, hours=parsed[0], minutes=parsed[1]
    )
    if current < scheduled:
        return False
    target_period = week_start_of(current) - timedelta(days=7)
    return last_period_start != target_period.date().isoformat()


def category_options() -> list[dict]:
    """归因选项：越权类失败不进入学习，直接排除。"""
    return [
        {"value": category, "label": label}
        for category, label in CATEGORY_LABELS.items()
        if category != "permission_violation"
    ]


def low_confidence_question(
    attribution: FailureAttribution,
    *,
    title: str | None = None,
    threshold: float = 0.6,
) -> AutoQuestion | None:
    if attribution.category == "permission_violation":
        return None
    if attribution.employee_id is None:
        return None
    if float(attribution.confidence or 0) >= threshold:
        return None
    label = CATEGORY_LABELS.get(attribution.category, attribution.category)
    task_name = (title or f"任务 #{attribution.instance_id or '—'}").strip()
    confidence = float(attribution.confidence or 0)
    return AutoQuestion(
        kind="low_confidence",
        employee_id=attribution.employee_id,
        instance_id=attribution.instance_id,
        question=(
            f"{AUTO_PREFIX}任务「{task_name}」失败，我暂时归因为「{label}」"
            f"（置信度 {confidence:.0%}）。更接近哪种原因？"
        ),
        options=category_options(),
        default_option="unknown",
    )


def recurrence_question(
    employee_id: int,
    category: str,
    count: int,
) -> AutoQuestion | None:
    if category == "permission_violation" or count < 2:
        return None
    label = CATEGORY_LABELS.get(category, category)
    action, suggestion = ROUTES.get(category, ROUTES["unknown"])
    return AutoQuestion(
        kind="recurrence",
        employee_id=employee_id,
        instance_id=None,
        question=(
            f"{AUTO_PREFIX}最近「{label}」类失败出现 {count} 次。"
            f"你希望我优先怎么处理？"
        ),
        options=[
            {"value": action, "label": suggestion},
            {"value": "observe", "label": "先观察，暂不调整配置"},
            {"value": "manual", "label": "转人工排查根因"},
        ],
        default_option=action,
    )


def must_ask_question(
    employee_id: int,
    instance_id: int | None,
    reason: str,
    *,
    title: str | None = None,
) -> AutoQuestion:
    task_name = (title or f"任务 #{instance_id or '—'}").strip()
    return AutoQuestion(
        kind="must_ask",
        employee_id=employee_id,
        instance_id=instance_id,
        question=(
            f"{AUTO_PREFIX}任务「{task_name}」因「{reason[:180]}」停下来请示。"
            f"以后遇到同类情况怎么处理？"
        ),
        options=[
            {"value": "always_ask", "label": "继续每次都请示"},
            {"value": "auto_within_limit", "label": "在现有红线内自动执行，超出再请示"},
            {"value": "escalate", "label": "直接升级给上级"},
        ],
        default_option="always_ask",
    )


async def attribute_pending_failures(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    lookback_hours: int = 24,
    limit: int = 200,
    tenant_id: int | None = None,
    use_llm: bool | None = None,
) -> dict:
    """给窗口内尚未归因的失败任务补归因。"""
    current = _aware(now or utcnow())
    llm_enabled = (
        settings.llm_attribution_enabled if use_llm is None else use_llm
    )
    cutoff = current - timedelta(hours=max(1, lookback_hours))
    conditions = [
        TaskInstance.status == "failed",
        or_(
            TaskInstance.finished_at >= cutoff,
            and_(
                TaskInstance.finished_at.is_(None),
                TaskInstance.created_at >= cutoff,
            ),
        ),
        not_(
            select(FailureAttribution.id)
            .where(FailureAttribution.instance_id == TaskInstance.id)
            .exists()
        ),
    ]
    if tenant_id is not None:
        conditions.append(TaskInstance.tenant_id == tenant_id)

    instances = list(
        (
            await db.scalars(
                select(TaskInstance)
                .where(*conditions)
                .order_by(TaskInstance.id)
                .limit(limit)
            )
        ).all()
    )
    categories: Counter[str] = Counter()
    items: list[dict] = []
    for instance in instances:
        attribution = await attribute_instance_failure(
            db, instance, error=instance.error, use_llm=llm_enabled
        )
        categories[attribution.category] += 1
        items.append(
            {
                "instance_id": instance.id,
                "employee_id": instance.employee_id,
                "category": attribution.category,
                "confidence": attribution.confidence,
            }
        )

    return {
        "scanned": len(instances),
        "attributed": len(items),
        "categories": dict(categories),
        "items": items,
    }


async def _collect_must_ask_steps(
    db: AsyncSession,
    *,
    cutoff: datetime,
    tenant_id: int | None,
    limit: int = 200,
) -> dict[int, list[dict]]:
    conditions = [
        TaskInstance.created_at >= cutoff,
        TaskStep.status == "waiting",
        TaskStep.step_type == "tool",
    ]
    if tenant_id is not None:
        conditions.append(TaskInstance.tenant_id == tenant_id)
    rows = await db.execute(
        select(TaskStep, TaskInstance)
        .join(TaskInstance, TaskStep.instance_id == TaskInstance.id)
        .where(*conditions)
        .order_by(TaskStep.id.desc())
        .limit(limit)
    )
    grouped: dict[int, list[dict]] = defaultdict(list)
    seen_instances: set[int] = set()
    for step, instance in rows:
        if instance.employee_id is None or instance.id in seen_instances:
            continue
        gate = (step.output or {}).get("contract_gate") or {}
        if gate.get("rule") != "contract.must_ask":
            continue
        seen_instances.add(instance.id)
        grouped[instance.employee_id].append(
            {
                "instance_id": instance.id,
                "reason": str(gate.get("reason") or step.name or "必须请示"),
                "title": instance.title,
            }
        )
    return grouped


async def create_auto_questions(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    lookback_hours: int = 24,
    tenant_id: int | None = None,
) -> dict:
    """按 must_ask → 低置信度 → 同类复发 的优先级自动提问。"""
    if not settings.learning_auto_question_enabled:
        return {"created": 0, "items": [], "disabled": True}

    current = _aware(now or utcnow())
    cutoff = current - timedelta(hours=max(1, lookback_hours))

    attribution_conditions = [
        FailureAttribution.created_at >= cutoff,
        FailureAttribution.employee_id.is_not(None),
    ]
    if tenant_id is not None:
        attribution_conditions.append(
            FailureAttribution.tenant_id == tenant_id
        )
    attributions = list(
        (
            await db.scalars(
                select(FailureAttribution)
                .where(*attribution_conditions)
                .order_by(FailureAttribution.id.desc())
                .limit(300)
            )
        ).all()
    )
    by_employee: dict[int, list[FailureAttribution]] = defaultdict(list)
    for attribution in attributions:
        if attribution.employee_id is not None:
            by_employee[attribution.employee_id].append(attribution)

    must_ask_by_employee = await _collect_must_ask_steps(
        db, cutoff=cutoff, tenant_id=tenant_id
    )
    employee_ids = set(by_employee) | set(must_ask_by_employee)
    if not employee_ids:
        return {"created": 0, "items": []}

    employees = list(
        (
            await db.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.id.in_(employee_ids)
                )
            )
        ).all()
    )
    employees_by_id = {employee.id: employee for employee in employees}

    instance_ids = {
        attribution.instance_id
        for attribution in attributions
        if attribution.instance_id is not None
    }
    titles: dict[int, str] = {}
    if instance_ids:
        rows = await db.execute(
            select(TaskInstance.id, TaskInstance.title).where(
                TaskInstance.id.in_(instance_ids)
            )
        )
        titles = {row[0]: row[1] for row in rows}

    # 7 天内同一员工出现过相同问题就不再重复提问（含已回答/已忽略），
    # 避免进程重启后同一批归因再次生成重复问题。
    recent_keys: set[tuple[int, str]] = {
        (row[0], row[1])
        for row in await db.execute(
            select(LearningQuestion.employee_id, LearningQuestion.question).where(
                LearningQuestion.created_at >= current - timedelta(days=7),
            )
        )
    }

    created: list[dict] = []
    for employee_id in sorted(employee_ids):
        employee = employees_by_id.get(employee_id)
        if employee is None:
            continue
        info = await budget_info(db, employee)
        if info["remaining"] <= 0:
            continue

        candidates: list[AutoQuestion] = []
        for item in must_ask_by_employee.get(employee_id, [])[:2]:
            candidates.append(
                must_ask_question(
                    employee_id,
                    item["instance_id"],
                    item["reason"],
                    title=item.get("title"),
                )
            )
        for attribution in by_employee.get(employee_id, []):
            candidate = low_confidence_question(
                attribution,
                title=titles.get(attribution.instance_id),
                threshold=settings.learning_auto_question_confidence,
            )
            if candidate is not None:
                candidates.append(candidate)
        counts = Counter(
            attribution.category
            for attribution in by_employee.get(employee_id, [])
        )
        for category, count in counts.most_common():
            if count < settings.learning_auto_question_recurrence:
                continue
            candidate = recurrence_question(employee_id, category, count)
            if candidate is not None:
                candidates.append(candidate)

        budget_left = min(
            info["remaining"], max(1, settings.learning_auto_question_max_per_run)
        )
        for candidate in candidates:
            if budget_left <= 0:
                break
            key = (employee_id, candidate.question)
            if key in recent_keys:
                continue
            try:
                question, _ = await create_question(
                    db,
                    employee.tenant_id,
                    employee,
                    LearningQuestionCreate(
                        employee_id=employee_id,
                        instance_id=candidate.instance_id,
                        question=candidate.question,
                        options=candidate.options,
                        default_option=candidate.default_option,
                    ),
                )
            except BadRequestError:
                break
            recent_keys.add(key)
            budget_left -= 1
            created.append({**candidate.as_item(), "question_id": question.id})

    return {"created": len(created), "items": created}


async def run_daily_learning_batch(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    lookback_hours: int | None = None,
    tenant_id: int | None = None,
) -> dict:
    current = _aware(now or utcnow())
    window = lookback_hours or settings.learning_daily_lookback_hours
    attribution_result = await attribute_pending_failures(
        db, now=current, lookback_hours=window, tenant_id=tenant_id
    )
    upgrade_result = await upgrade_rule_attributions(
        db, lookback_hours=window, tenant_id=tenant_id
    )
    question_result = await create_auto_questions(
        db, now=current, lookback_hours=window, tenant_id=tenant_id
    )
    return {
        "run_at": current.isoformat(),
        "lookback_hours": window,
        "attribution": attribution_result,
        "attribution_upgrade": upgrade_result,
        "questions": question_result,
    }


async def _tenant_ids(db: AsyncSession, tenant_id: int | None) -> list[int]:
    if tenant_id is not None:
        return [tenant_id]
    rows = await db.execute(
        select(DigitalEmployee.tenant_id).distinct()
    )
    return [int(row[0]) for row in rows]


async def run_weekly_review_batch(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    tenant_id: int | None = None,
    week_start: datetime | None = None,
    force: bool = False,
    deliver: bool = False,
    previous_week: bool = True,
) -> dict:
    """为有任务的员工生成周报；默认统计上一自然周。"""
    current = _aware(now or utcnow())
    if week_start is not None:
        period_start = _aware(week_start).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        period_start = week_start_of(current)
        if previous_week:
            period_start -= timedelta(days=7)
    period_end = period_start + timedelta(days=7)

    created: list[dict] = []
    skipped = 0
    for tid in await _tenant_ids(db, tenant_id):
        employee_rows = await db.execute(
            select(TaskInstance.employee_id)
            .where(
                TaskInstance.tenant_id == tid,
                TaskInstance.employee_id.is_not(None),
                TaskInstance.created_at >= period_start,
                TaskInstance.created_at < period_end,
            )
            .distinct()
        )
        employee_ids = sorted(
            int(row[0]) for row in employee_rows if row[0] is not None
        )
        for employee_id in employee_ids:
            if not force:
                exists_id = await db.scalar(
                    select(WeeklyReview.id).where(
                        WeeklyReview.tenant_id == tid,
                        WeeklyReview.employee_id == employee_id,
                        WeeklyReview.period_start == period_start,
                    )
                )
                if exists_id is not None:
                    skipped += 1
                    continue
            review = await build_weekly_review(
                db, tid, employee_id, week_start=period_start
            )
            delivery = None
            if deliver and settings.weekly_review_delivery_url:
                delivery = await deliver_weekly_review(db, review)
            created.append(
                {
                    "review_id": review.id,
                    "employee_id": employee_id,
                    "period_start": review.period_start.isoformat(),
                    "status": review.status,
                    "delivery": delivery,
                }
            )

    return {
        "generated": len(created),
        "skipped": skipped,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "items": created,
    }


def _review_payload(review: WeeklyReview) -> dict:
    learned = dict(review.learned or {})
    learned.pop("delivery", None)
    return {
        "id": review.id,
        "tenant_id": review.tenant_id,
        "employee_id": review.employee_id,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "metrics": review.metrics,
        "top_errors": review.top_errors,
        "learned": learned,
        "recommendations": review.recommendations,
        "summary": review.summary,
        "status": review.status,
    }


async def deliver_weekly_review(
    db: AsyncSession,
    review: WeeklyReview,
    *,
    url: str | None = None,
    timeout: float | None = None,
) -> dict:
    """把周报推送到配置的 webhook；未配置时只返回未投递原因。"""
    target = url or settings.weekly_review_delivery_url
    if not target:
        return {"delivered": False, "reason": "未配置 WEEKLY_REVIEW_DELIVERY_URL"}

    delivered_at = utcnow()
    try:
        async with httpx.AsyncClient(
            timeout=timeout or settings.weekly_review_delivery_timeout
        ) as client:
            response = await client.post(target, json=_review_payload(review))
        ok = 200 <= response.status_code < 300
        result: dict = {
            "delivered": ok,
            "status_code": response.status_code,
            "url": target,
            "at": delivered_at.isoformat(),
        }
        if not ok:
            result["error"] = response.text[:300]
    except Exception as exc:  # noqa: BLE001
        result = {
            "delivered": False,
            "url": target,
            "at": delivered_at.isoformat(),
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }

    review.status = "delivered" if result["delivered"] else "delivery_failed"
    learned = dict(review.learned or {})
    learned["delivery"] = result
    review.learned = learned
    await db.flush()
    return result


def scheduler_status() -> dict:
    return {
        "enabled": settings.learning_scheduler_enabled,
        "daily_at": settings.learning_daily_at,
        "daily_lookback_hours": settings.learning_daily_lookback_hours,
        "weekly_weekday": settings.learning_weekly_weekday,
        "weekly_at": settings.learning_weekly_at,
        "auto_question_enabled": settings.learning_auto_question_enabled,
        "delivery_configured": bool(settings.weekly_review_delivery_url),
        "last_runs": dict(LAST_RUNS),
        "timezone": "UTC",
    }


async def run_learning_scheduler(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        now = utcnow()
        try:
            if daily_due(now, settings.learning_daily_at, LAST_RUNS.get("daily")):
                async with SessionLocal() as session:
                    result = await run_daily_learning_batch(
                        session,
                        now=now,
                        lookback_hours=settings.learning_daily_lookback_hours,
                    )
                    await session.commit()
                LAST_RUNS["daily"] = _aware(now).date().isoformat()
                logger.info(
                    "日结学习批量完成: 归因 %s 条，LLM 复核 %s 条，自动提问 %s 条",
                    result["attribution"]["attributed"],
                    result["attribution_upgrade"]["upgraded"],
                    result["questions"]["created"],
                )
            if weekly_due(
                now,
                settings.learning_weekly_weekday,
                settings.learning_weekly_at,
                LAST_RUNS.get("weekly"),
            ):
                async with SessionLocal() as session:
                    result = await run_weekly_review_batch(
                        session, now=now, deliver=True
                    )
                    await session.commit()
                LAST_RUNS["weekly"] = result["period_start"][:10]
                logger.info(
                    "周报批量生成完成: %s 份，跳过 %s 份",
                    result["generated"],
                    result["skipped"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("学习节奏调度异常")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(5, settings.learning_scheduler_poll_interval),
            )
        except TimeoutError:
            continue
