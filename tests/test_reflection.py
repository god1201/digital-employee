from types import SimpleNamespace

import pytest
from langgraph.graph import END

from app.domains.learning import reflection
from app.domains.workflows.tasks import engine
from app.domains.workflows.tasks.engine import (
    route_after_execute,
    route_after_plan,
    route_after_verify,
    should_auto_retry,
)


def test_rule_reflection_retry_boundaries() -> None:
    planning = reflection.rule_reflection("planning_error", "步骤未全部完成")
    assert planning["retryable"] is True
    assert "重新规划" in planning["hint"]

    blocked = reflection.rule_reflection(
        "planning_error", "固定任务未配置可执行步骤"
    )
    assert blocked["retryable"] is False

    permission = reflection.rule_reflection(
        "permission_violation", "岗位契约拦截：触碰红线"
    )
    assert permission["retryable"] is False

    unknown = reflection.rule_reflection("unknown", "未知错误")
    assert unknown["retryable"] is True


@pytest.mark.asyncio
async def test_llm_reflection_merges_and_can_only_tighten(monkeypatch) -> None:
    async def fake_chat_json(messages, **kwargs):
        return (
            {
                "diagnosis": "计划缺少对账步骤",
                "hint": "补上对账步骤后再生成月报",
                "suggestions": ["先查回款", "再生成月报"],
                "retryable": False,
            },
            10,
        )

    monkeypatch.setattr(reflection, "is_configured", lambda: True)
    monkeypatch.setattr(
        reflection.settings, "reflection_llm_enabled", True
    )
    monkeypatch.setattr(reflection, "chat_json", fake_chat_json)

    instance = SimpleNamespace(title="生成月报", task_type="free", input={})
    result = await reflection.build_reflection(
        instance, [], "步骤未全部完成", "planning_error", "补 SOP"
    )
    assert result["source"] == "llm"
    assert result["hint"] == "补上对账步骤后再生成月报"
    assert result["retryable"] is False

    # 规则已判定不可重试时，LLM 不能放宽
    monkeypatch.setattr(
        reflection,
        "chat_json",
        lambda messages, **kwargs: _truthy_llm(),
    )
    permission = await reflection.build_reflection(
        instance, [], "岗位契约拦截", "permission_violation"
    )
    assert permission["retryable"] is False


async def _truthy_llm():
    return {"hint": "可以重试", "retryable": True}, 5


@pytest.mark.asyncio
async def test_llm_reflection_falls_back_on_failure(monkeypatch) -> None:
    async def fake_chat_json(messages, **kwargs):
        raise reflection.LLMError("network down")

    monkeypatch.setattr(reflection, "is_configured", lambda: True)
    monkeypatch.setattr(
        reflection.settings, "reflection_llm_enabled", True
    )
    monkeypatch.setattr(reflection, "chat_json", fake_chat_json)

    result = await reflection.build_reflection(
        SimpleNamespace(title="t", task_type="free", input={}),
        [],
        "未知错误",
        "unknown",
    )
    assert result["source"] == "rule"
    assert result["retryable"] is True


def test_should_auto_retry(monkeypatch) -> None:
    monkeypatch.setattr(engine.settings, "reflection_auto_retry", True)
    monkeypatch.setattr(engine.settings, "reflection_max_retries", 1)
    instance = SimpleNamespace(task_type="free", attempt=1, max_attempts=3)
    retryable = {"retryable": True}

    assert should_auto_retry(instance, retryable, 0) is True
    assert should_auto_retry(instance, retryable, 1) is False
    assert should_auto_retry(
        SimpleNamespace(task_type="fixed", attempt=1, max_attempts=3),
        retryable,
        0,
    ) is False
    assert should_auto_retry(
        SimpleNamespace(task_type="free", attempt=3, max_attempts=3),
        retryable,
        0,
    ) is False
    assert should_auto_retry(instance, {"retryable": False}, 0) is False

    monkeypatch.setattr(engine.settings, "reflection_auto_retry", False)
    assert should_auto_retry(instance, retryable, 0) is False


def test_reflection_graph_routes() -> None:
    assert route_after_plan({"error": "boom"}) == "reflect"
    assert route_after_plan({}) == "execute"
    assert route_after_execute({"need_human": True}) == END
    assert route_after_execute({"error": "boom"}) == "reflect"
    assert route_after_execute({}) == "verify"
    assert route_after_verify({"verified": True}) == END
    assert route_after_verify({"verified": False}) == "reflect"
