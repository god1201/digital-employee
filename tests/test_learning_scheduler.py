from datetime import UTC, datetime
from types import SimpleNamespace

from app.domains.learning.scheduler import (
    category_options,
    daily_due,
    low_confidence_question,
    must_ask_question,
    parse_hhmm,
    recurrence_question,
    scheduler_status,
    week_start_of,
    weekly_due,
)


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _attribution(**overrides):
    values = {
        "employee_id": 7,
        "instance_id": 11,
        "category": "unknown",
        "confidence": 0.3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_parse_hhmm() -> None:
    assert parse_hhmm("02:30") == (2, 30)
    assert parse_hhmm("23:59") == (23, 59)
    assert parse_hhmm("24:00") is None
    assert parse_hhmm("bad") is None
    assert parse_hhmm(None) is None


def test_daily_due_with_catch_up() -> None:
    assert not daily_due(_dt(2026, 11, 2, 1, 59), "02:00", None)
    assert daily_due(_dt(2026, 11, 2, 2, 0), "02:00", None)
    assert daily_due(_dt(2026, 11, 2, 15, 0), "02:00", None)
    assert not daily_due(_dt(2026, 11, 2, 15, 0), "02:00", "2026-11-02")
    assert daily_due(_dt(2026, 11, 3, 2, 0), "02:00", "2026-11-02")


def test_week_start_of_monday() -> None:
    # 2026-11-02 是周一
    assert week_start_of(_dt(2026, 11, 2, 8, 0)) == _dt(2026, 11, 2, 0, 0)
    assert week_start_of(_dt(2026, 11, 5, 8, 0)) == _dt(2026, 11, 2, 0, 0)


def test_weekly_due_reports_previous_week() -> None:
    assert not weekly_due(_dt(2026, 11, 2, 8, 59), 0, "09:00", None)
    assert weekly_due(_dt(2026, 11, 2, 9, 0), 0, "09:00", None)
    # 目标周期是上一自然周：2026-10-26
    assert not weekly_due(_dt(2026, 11, 2, 9, 0), 0, "09:00", "2026-10-26")
    # 周中晚启动补跑
    assert weekly_due(_dt(2026, 11, 4, 12, 0), 0, "09:00", None)


def test_category_options_exclude_permission_violation() -> None:
    values = {item["value"] for item in category_options()}
    assert "permission_violation" not in values
    assert "unknown" in values


def test_low_confidence_question() -> None:
    question = low_confidence_question(_attribution(), title="核对账单")
    assert question is not None
    assert question.kind == "low_confidence"
    assert "核对账单" in question.question
    assert question.default_option == "unknown"

    assert low_confidence_question(_attribution(confidence=0.9)) is None
    assert low_confidence_question(
        _attribution(category="permission_violation")
    ) is None


def test_recurrence_question() -> None:
    question = recurrence_question(7, "tool_misuse", 3)
    assert question is not None
    assert question.kind == "recurrence"
    assert question.default_option == "fix_tool_schema"
    assert {item["value"] for item in question.options} == {
        "fix_tool_schema",
        "observe",
        "manual",
    }
    assert recurrence_question(7, "tool_misuse", 1) is None
    assert recurrence_question(7, "permission_violation", 5) is None


def test_must_ask_question() -> None:
    question = must_ask_question(7, 12, "单笔超过5万", title="付款申请")
    assert question.kind == "must_ask"
    assert "单笔超过5万" in question.question
    assert question.default_option == "always_ask"


def test_scheduler_status_exposes_config() -> None:
    status = scheduler_status()
    assert status["timezone"] == "UTC"
    assert "last_runs" in status
    assert isinstance(status["enabled"], bool)
