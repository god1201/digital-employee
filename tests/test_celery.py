import pytest

pytest.importorskip("celery")


def test_celery_app_config_and_eager() -> None:
    from app.worker.celery_app import celery_app

    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.task_default_queue

    @celery_app.task(name="digital_employee.test_noop")
    def noop(value: int) -> int:
        return value

    celery_app.conf.task_always_eager = True
    try:
        result = noop.apply(args=[7])
        assert result.get() == 7
    finally:
        celery_app.conf.task_always_eager = False
