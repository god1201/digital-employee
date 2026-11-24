"""综合评估套件：打分、执行与回归门禁。"""

import difflib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utcnow
from app.core.llm import LLMError, chat_text, is_configured
from app.domains.learning.models import (
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
)


def text_similarity(actual: str, expected: str) -> float:
    if not actual or not expected:
        return 0.0
    return round(difflib.SequenceMatcher(None, actual, expected).ratio(), 4)


def keyword_recall(actual: str, keywords: list[str]) -> tuple[float, list[str], list[str]]:
    if not keywords:
        return 0.0, [], []
    matched = [keyword for keyword in keywords if keyword and keyword in actual]
    missing = [keyword for keyword in keywords if keyword and keyword not in actual]
    return round(len(matched) / len(keywords), 4), matched, missing


def score_output(actual: str, expected: dict) -> dict:
    """按期望文本/关键词给一次输出打分。"""
    actual = str(actual or "")
    expected = expected or {}
    keywords = [str(item) for item in expected.get("keywords") or []]
    target_text = str(expected.get("text") or "")
    exact = expected.get("exact")

    if exact is not None:
        score = 1.0 if actual.strip() == str(exact).strip() else 0.0
        return {
            "score": score,
            "keyword_score": score,
            "similarity": score,
            "matched_keywords": keywords,
            "missing_keywords": [],
        }

    recall, matched, missing = keyword_recall(actual, keywords)
    similarity = text_similarity(actual, target_text) if target_text else 0.0
    if keywords and target_text:
        score = 0.7 * recall + 0.3 * similarity
    elif keywords:
        score = recall
    elif target_text:
        score = similarity
    else:
        score = 1.0 if actual.strip() else 0.0
    return {
        "score": round(score, 4),
        "keyword_score": recall,
        "similarity": similarity,
        "matched_keywords": matched,
        "missing_keywords": missing,
    }


async def suites_for_employee(
    db: AsyncSession, tenant_id: int, employee_id: int | None
) -> list[EvaluationSuite]:
    if not employee_id:
        return []
    return list(
        (
            await db.scalars(
                select(EvaluationSuite).where(
                    EvaluationSuite.tenant_id == tenant_id,
                    EvaluationSuite.employee_id == employee_id,
                    EvaluationSuite.enabled.is_(True),
                    EvaluationSuite.enforce_on_activate.is_(True),
                )
            )
        ).all()
    )


async def latest_run_score(db: AsyncSession, suite_id: int) -> float | None:
    run = await db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.suite_id == suite_id, EvaluationRun.status == "succeeded")
        .order_by(EvaluationRun.id.desc())
        .limit(1)
    )
    return float(run.score) if run is not None else None


async def run_suite(
    db: AsyncSession,
    suite: EvaluationSuite,
    *,
    employee=None,
    system_prompt: str = "",
    artifact_id: int | None = None,
    trigger: str = "manual",
    outputs: dict[str, str] | None = None,
    user_id: int | None = None,
) -> EvaluationRun:
    outputs = outputs or {}
    cases = list(
        (
            await db.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.suite_id == suite.id, EvaluationCase.enabled.is_(True))
                .order_by(EvaluationCase.id)
            )
        ).all()
    )
    baseline = await latest_run_score(db, suite.id)
    run = EvaluationRun(
        tenant_id=suite.tenant_id,
        suite_id=suite.id,
        employee_id=suite.employee_id or (employee.id if employee is not None else None),
        artifact_id=artifact_id,
        trigger=trigger,
        status="running",
        threshold=suite.threshold,
        baseline_score=baseline,
        started_at=utcnow(),
        created_by=user_id,
    )
    db.add(run)
    await db.flush()

    if not cases:
        run.status = "failed"
        run.error = "评估套件没有启用的用例"
        run.finished_at = utcnow()
        await db.flush()
        return run

    details: list[dict] = []
    weighted_total = 0.0
    weight_sum = 0.0
    llm_failures = 0
    llm_cases = 0

    for case in cases:
        weight = float(case.weight or 1.0)
        weight_sum += weight
        actual = ""
        error: str | None = None
        try:
            if case.case_type == "assertion":
                actual = str(outputs.get(str(case.id)) or (case.input or {}).get("actual") or "")
                if not actual:
                    error = "缺少实际输出（assertion 用例需传入 outputs）"
            else:
                llm_cases += 1
                case_input = case.input or {}
                prompt = str(case_input.get("prompt") or case_input.get("text") or "")
                if not prompt:
                    error = "LLM 用例缺少 input.prompt"
                elif not is_configured():
                    error = "未配置 LLM_API_KEY，无法执行 LLM 用例"
                else:
                    actual, _tokens = await chat_text(
                        [
                            {
                                "role": "system",
                                "content": system_prompt or "你是一名数字员工。",
                            },
                            {"role": "user", "content": prompt},
                        ]
                    )
        except LLMError as exc:
            error = str(exc)

        if error:
            if case.case_type == "llm":
                llm_failures += 1
            scored = {
                "score": 0.0,
                "keyword_score": 0.0,
                "similarity": 0.0,
                "matched_keywords": [],
                "missing_keywords": [],
            }
        else:
            scored = score_output(actual, case.expected or {})

        weighted_total += float(scored["score"]) * weight
        details.append(
            {
                "case_id": case.id,
                "name": case.name,
                "case_type": case.case_type,
                "weight": weight,
                **scored,
                "actual": actual[:1000],
                "expected": case.expected,
                "error": error,
            }
        )

    run.score = round(weighted_total / weight_sum, 4) if weight_sum else 0.0
    run.details = details
    run.delta = round(run.score - baseline, 4) if baseline is not None else None
    run.passed = bool(
        run.score >= suite.threshold
        and (
            baseline is None
            or run.score >= baseline - suite.regression_tolerance
        )
    )
    run.finished_at = utcnow()
    if llm_cases and llm_failures == llm_cases:
        run.status = "failed"
        run.error = "全部 LLM 用例执行失败，请检查 LLM 配置或用例输入"
        run.passed = False
    else:
        run.status = "succeeded"
    await db.flush()
    return run
