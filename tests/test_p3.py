from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.deps import callback_token_matches, hash_callback_token
from app.core.exceptions import BadRequestError
from app.domains.learning.schemas import TrainingJobStatusUpdate
from app.domains.learning.training import (
    _expected_text,
    apply_job_status,
    build_dispatch_payload,
)
from app.domains.workflows.tasks.triggers import compute_next_run
from app.domains.workforce.collaboration.schemas import CollaborationCreate
from app.domains.workforce.migrations.service import _proposal_hash


def test_proposal_hash_stable() -> None:
    left = {"content": "结论先行", "action": "update_style"}
    right = {"action": "update_style", "content": "结论先行"}
    assert _proposal_hash(left) == _proposal_hash(right)
    assert _proposal_hash(left) != _proposal_hash({"content": "别的"})


def test_trigger_next_run() -> None:
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    interval = compute_next_run("interval", interval_seconds=120, now=now)
    assert interval == datetime(2026, 1, 1, 10, 2, tzinfo=UTC)

    later_today = compute_next_run("daily", daily_at="18:00", now=now)
    assert later_today == datetime(2026, 1, 1, 18, 0, tzinfo=UTC)

    tomorrow = compute_next_run("daily", daily_at="09:00", now=now)
    assert tomorrow == datetime(2026, 1, 2, 9, 0, tzinfo=UTC)

    assert compute_next_run("event", now=now) is None


def test_collaboration_mode_default() -> None:
    payload = CollaborationCreate(
        owner_employee_id=1,
        goal="核对回款",
        participants=[{"employee_id": 2, "instruction": "查 A 客户"}],
    )
    assert payload.mode == "sequential"
    parallel = CollaborationCreate(
        owner_employee_id=1,
        goal="核对回款",
        mode="parallel",
        participants=[{"employee_id": 2, "instruction": "查 A 客户"}],
    )
    assert parallel.mode == "parallel"


def test_callback_token() -> None:
    token = "trainer-secret"
    digest = hash_callback_token(token)
    assert digest == hash_callback_token(token)
    assert callback_token_matches(token, digest)
    assert not callback_token_matches("wrong", digest)
    assert not callback_token_matches(None, digest)
    assert not callback_token_matches(token, None)


def test_expected_text() -> None:
    assert _expected_text({"text": "账期45天"}) == "账期45天"
    assert _expected_text({"keywords": ["回款率", "85%"]}) == "回款率、85%"
    assert _expected_text({"exact": "done"}) == "done"
    assert _expected_text({}) == ""


def test_dispatch_payload() -> None:
    job = SimpleNamespace(id=9, method="dpo", config={"epochs": 1})
    payload = build_dispatch_payload(
        job,
        [
            '{"prompt":"p","chosen":"c","rejected":"r"}',
            "",
            "not-json",
        ],
    )
    assert payload["job_id"] == 9
    assert payload["method"] == "dpo"
    assert payload["config"] == {"epochs": 1}
    assert payload["dataset_size"] == 2
    assert payload["dataset"][0]["chosen"] == "c"
    assert payload["dataset"][1] == {"raw": "not-json"}


def test_training_job_transitions() -> None:
    job = SimpleNamespace(
        status="pending",
        started_at=None,
        finished_at=None,
        metrics={},
        error=None,
    )
    apply_job_status(job, TrainingJobStatusUpdate(status="running"))
    assert job.status == "running"
    assert job.started_at is not None

    apply_job_status(
        job, TrainingJobStatusUpdate(status="succeeded", metrics={"loss": 0.12})
    )
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.metrics == {"loss": 0.12}

    with pytest.raises(BadRequestError):
        apply_job_status(job, TrainingJobStatusUpdate(status="running"))


def test_training_job_invalid_transition() -> None:
    job = SimpleNamespace(
        status="pending",
        started_at=None,
        finished_at=None,
        metrics={},
        error=None,
    )
    with pytest.raises(BadRequestError):
        apply_job_status(job, TrainingJobStatusUpdate(status="succeeded"))


def test_training_job_dispatch_transitions() -> None:
    # dispatch 端点直接把 pending 置为 dispatched，回调只负责 dispatched→running
    job = SimpleNamespace(
        status="dispatched",
        started_at=None,
        finished_at=None,
        metrics={},
        error=None,
    )
    apply_job_status(job, TrainingJobStatusUpdate(status="running"))
    assert job.status == "running"
