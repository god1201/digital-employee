from types import SimpleNamespace

from app.domains.learning.attribution import classify_failure, route_label
from app.domains.learning.evaluation import (
    keyword_recall,
    score_output,
    text_similarity,
)
from app.domains.learning.rollout import (
    artifact_visible,
    build_artifacts_context,
    canary_bucket,
)
from app.domains.learning.service import compute_diff, diff_summary
from app.domains.workforce.contracts.service import evaluate_tool_call


def _contract(**overrides):
    values = {
        "status": "active",
        "autonomy_level": "L2",
        "autonomy_overrides": {},
        "cannot_do": [],
        "must_ask": [],
        "red_lines": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _tool(code="send_email", method="POST", tool_type="http"):
    return SimpleNamespace(
        code=code,
        name="发送邮件",
        tool_type=tool_type,
        config={"method": method},
    )


def test_compute_diff_nested() -> None:
    original = {
        "text": "原稿缺少附件",
        "amount": 100,
        "items": [{"id": 1}, {"id": 2}],
        "meta": {"keep": True},
    }
    final = {
        "text": "原稿已附对账明细",
        "amount": 120,
        "items": [{"id": 1}],
        "meta": {"keep": True, "reviewed": True},
    }
    diff = compute_diff(original, final)
    paths = {item["path"]: item["op"] for item in diff}

    assert paths["text"] == "change"
    assert paths["amount"] == "change"
    assert paths["items[1]"] == "remove"
    assert paths["meta.reviewed"] == "add"
    assert "meta.keep" not in paths

    summary = diff_summary(diff)
    assert summary["change"] == 2
    assert summary["remove"] == 1
    assert summary["add"] == 1
    assert summary["total"] == 4


def test_compute_diff_identical() -> None:
    assert compute_diff({"a": 1}, {"a": 1}) == []


def test_contract_allows_without_contract() -> None:
    decision = evaluate_tool_call(None, tool=_tool())
    assert decision.action == "allow"
    assert decision.rule == "no_contract"


def test_contract_forbidden_tool() -> None:
    contract = _contract(red_lines={"forbidden_tools": ["send_email"]})
    decision = evaluate_tool_call(contract, tool=_tool())
    assert decision.action == "deny"
    assert decision.rule == "red_line.forbidden_tool"


def test_contract_cannot_do_and_must_ask() -> None:
    contract = _contract(cannot_do=["承诺减免"])
    deny = evaluate_tool_call(
        contract,
        tool=_tool(),
        step_name="给客户发送承诺减免邮件",
    )
    assert deny.action == "deny"
    assert deny.rule == "contract.cannot_do"

    contract = _contract(must_ask=["退款金额超过 1000"])
    ask = evaluate_tool_call(
        contract,
        tool=_tool(),
        step_name="处理退款金额超过 1000 的申请",
    )
    assert ask.action == "ask"
    assert ask.rule == "contract.must_ask"


def test_contract_amount_threshold() -> None:
    contract = _contract(red_lines={"amount_threshold": 5000, "amount_field": "amount"})
    decision = evaluate_tool_call(contract, tool=_tool(), arguments={"amount": 8000})
    assert decision.action == "ask"
    assert decision.rule == "red_line.amount_threshold"

    allowed = evaluate_tool_call(contract, tool=_tool(), arguments={"amount": 1000})
    assert allowed.action == "allow"


def test_contract_read_only() -> None:
    contract = _contract(red_lines={"read_only": True})
    denied = evaluate_tool_call(contract, tool=_tool(method="POST"))
    assert denied.action == "deny"
    assert denied.rule == "red_line.read_only"

    allowed = evaluate_tool_call(contract, tool=_tool(method="GET"))
    assert allowed.action == "allow"


def test_contract_autonomy_levels() -> None:
    assert evaluate_tool_call(_contract(autonomy_level="L0"), tool=_tool(method="POST")).action == (
        "deny"
    )
    assert evaluate_tool_call(_contract(autonomy_level="L1"), tool=_tool(method="POST")).action == (
        "ask"
    )
    assert evaluate_tool_call(_contract(autonomy_level="L1"), tool=_tool(method="GET")).action == (
        "allow"
    )
    assert evaluate_tool_call(_contract(autonomy_level="L3"), tool=_tool(method="POST")).action == (
        "allow"
    )


def test_contract_autonomy_override() -> None:
    contract = _contract(
        autonomy_level="L3",
        autonomy_overrides={"tool:send_email": "L1"},
    )
    decision = evaluate_tool_call(contract, tool=_tool(method="POST"))
    assert decision.action == "ask"
    assert decision.autonomy_level == "L1"


def _step(**overrides):
    values = {
        "name": "步骤",
        "step_type": "tool",
        "status": "succeeded",
        "error": None,
        "output": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_attribution_permission_violation() -> None:
    result = classify_failure(error="岗位契约拦截：触碰红线")
    assert result["category"] == "permission_violation"
    assert result["routed_action"] == "tighten_permission"
    assert result["confidence"] >= 0.9


def test_attribution_knowledge_missing() -> None:
    step = _step(step_type="knowledge", output={"results": []})
    result = classify_failure(steps=[step])
    assert result["category"] == "knowledge_missing"
    assert result["routed_action"] == "create_knowledge_ticket"


def test_attribution_retrieval_miss() -> None:
    step = _step(
        step_type="knowledge",
        output={"results": [{"score": 0.12}, {"score": 0.08}]},
    )
    result = classify_failure(steps=[step])
    assert result["category"] == "retrieval_miss"
    assert result["routed_action"] == "retune_chunk"


def test_attribution_tool_misuse() -> None:
    step = _step(status="failed", error="HTTP 422 参数校验失败")
    result = classify_failure(steps=[step], error="执行失败")
    assert result["category"] == "tool_misuse"
    assert result["routed_action"] == "fix_tool_schema"


def test_attribution_planning_error() -> None:
    result = classify_failure(error="规划结果为空")
    assert result["category"] == "planning_error"
    assert result["routed_action"] == "add_sop_step"


def test_attribution_style_vs_planning_from_intervention() -> None:
    text_only = SimpleNamespace(
        diff=[
            {"path": "text", "op": "change", "before": "原文", "after": "改写"},
            {"path": "summary", "op": "change", "before": "旧", "after": "新"},
        ]
    )
    assert classify_failure(intervention=text_only)["category"] == "style_mismatch"

    structural = SimpleNamespace(
        diff=[
            {"path": "attachments[0]", "op": "add", "before": None, "after": "对账明细.pdf"}
        ]
    )
    assert classify_failure(intervention=structural)["category"] == "planning_error"


def test_attribution_unknown_and_label() -> None:
    result = classify_failure()
    assert result["category"] == "unknown"
    label, route = route_label("unknown")
    assert label == "未知"
    assert route == "manual_review"


def _artifact(**overrides):
    values = {
        "id": 7,
        "status": "active",
        "target_layer": "persona_layer",
        "proposal": {"content": "结论先行"},
        "rollout": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_canary_bucket_deterministic() -> None:
    first = canary_bucket("trace-a", 7)
    assert first == canary_bucket("trace-a", 7)
    assert 0 <= first < 100


def test_artifact_visibility() -> None:
    assert artifact_visible(_artifact(status="active"), trace_id=None)
    assert not artifact_visible(_artifact(status="shadow"), trace_id="t1")
    assert not artifact_visible(
        _artifact(status="canary", rollout={"traffic": 0.0}), trace_id="t1"
    )
    assert artifact_visible(
        _artifact(status="canary", rollout={"traffic": 1.0}), trace_id="t1"
    )
    assert artifact_visible(
        _artifact(status="canary", rollout={"traffic": 0.0}), trace_id=None
    )
    assert not artifact_visible(
        _artifact(status="canary", rollout={"traffic": 1.0}),
        trace_id="t1",
        include_canary=False,
    )


def test_build_artifacts_context() -> None:
    context = build_artifacts_context(
        [
            _artifact(status="active"),
            _artifact(
                id=8,
                target_layer="procedural_memory",
                proposal={"content": "催款前附对账明细"},
            ),
        ]
    )
    assert "结论先行" in context
    assert "催款前附对账明细" in context
    assert "persona_layer" in context
    assert build_artifacts_context([]) == ""


def test_evaluation_scoring() -> None:
    recall, matched, missing = keyword_recall(
        "回款率 85%，差错率 0.4%", ["回款率", "差错率", "时效"]
    )
    assert recall == 0.6667
    assert matched == ["回款率", "差错率"]
    assert missing == ["时效"]

    assert text_similarity("同一个句子", "同一个句子") == 1.0
    assert text_similarity("完全不同的内容", "另一个答案") < 0.6

    scored = score_output(
        "按合同约定，回款率需达到 85%，本月为 91%。",
        {"keywords": ["回款率", "85%"], "text": "回款率需达到 85%"},
    )
    assert scored["keyword_score"] == 1.0
    assert scored["score"] >= 0.85

    exact = score_output("done", {"exact": "done"})
    assert exact["score"] == 1.0
