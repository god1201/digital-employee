from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestError
from app.domains.learning.schemas import TrainingJobStatusUpdate
from app.domains.learning.training import apply_job_status


def test_callback_metrics_merge_dispatch_metadata() -> None:
    job = SimpleNamespace(
        status="dispatched",
        metrics={"dispatch": {"external_job_id": "ref-1"}},
        error=None,
        started_at=None,
        finished_at=None,
    )
    apply_job_status(
        job,
        TrainingJobStatusUpdate(
            status="running", metrics={"epoch": 1, "loss": 0.5}
        ),
    )
    assert job.status == "running"
    assert job.metrics["dispatch"]["external_job_id"] == "ref-1"
    assert job.metrics["epoch"] == 1

    apply_job_status(
        job,
        TrainingJobStatusUpdate(
            status="succeeded", metrics={"loss": 0.1, "accuracy": 0.98}
        ),
    )
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.metrics["dispatch"]["external_job_id"] == "ref-1"
    assert job.metrics["accuracy"] == 0.98


def test_callback_rejects_invalid_transition() -> None:
    job = SimpleNamespace(
        status="succeeded",
        metrics={},
        error=None,
        started_at=None,
        finished_at=None,
    )
    with pytest.raises(BadRequestError):
        apply_job_status(
            job, TrainingJobStatusUpdate(status="running", metrics={})
        )
