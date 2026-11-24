from types import SimpleNamespace

import pytest

from app.domains.learning import attribution
from app.domains.skills.marketplace import service as marketplace


@pytest.mark.asyncio
async def test_llm_attribution_skips_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(attribution, "is_configured", lambda: False)
    assert await attribution.classify_failure_llm(error="boom") is None


@pytest.mark.asyncio
async def test_llm_attribution_valid(monkeypatch) -> None:
    async def fake_chat_json(messages, **kwargs):
        assert "失败归因器" in messages[0]["content"]
        return (
            {
                "category": "tool_misuse",
                "confidence": 0.88,
                "signals": ["HTTP 422 参数校验失败"],
                "suggestion": "修正工具参数 Schema",
            },
            12,
        )

    monkeypatch.setattr(attribution, "is_configured", lambda: True)
    monkeypatch.setattr(attribution, "chat_json", fake_chat_json)

    result = await attribution.classify_failure_llm(error="工具执行失败 HTTP 422")
    assert result is not None
    assert result["category"] == "tool_misuse"
    assert result["confidence"] == 0.88
    assert result["routed_action"] == "fix_tool_schema"
    assert result["signals"][0] == "LLM 归因"


@pytest.mark.asyncio
async def test_llm_attribution_rejects_unknown_category(monkeypatch) -> None:
    async def fake_chat_json(messages, **kwargs):
        return {"category": "made_up", "confidence": 0.9}, 5

    monkeypatch.setattr(attribution, "is_configured", lambda: True)
    monkeypatch.setattr(attribution, "chat_json", fake_chat_json)
    assert await attribution.classify_failure_llm(error="boom") is None


@pytest.mark.asyncio
async def test_llm_attribution_failure_returns_none(monkeypatch) -> None:
    async def fake_chat_json(messages, **kwargs):
        raise attribution.LLMError("network down")

    monkeypatch.setattr(attribution, "is_configured", lambda: True)
    monkeypatch.setattr(attribution, "chat_json", fake_chat_json)
    assert await attribution.classify_failure_llm(error="boom") is None


def test_llm_recommendation_validation() -> None:
    packages = [
        SimpleNamespace(code="data.report", name="报表生成", category="data", version=2),
        SimpleNamespace(code="data.sql_query", name="SQL 查询", category="data", version=1),
    ]
    picks = [
        {"code": "data.report", "score": 0.9, "reason": "匹配月报"},
        {"code": "hallucinated.code", "score": 1.0, "reason": "不存在"},
        {"code": "data.report", "score": 0.5, "reason": "重复"},
        {"code": "data.sql_query", "score": 7, "reason": "依赖"},
    ]
    items = marketplace._parse_llm_recommendations(picks, packages)
    assert [item["code"] for item in items] == ["data.report", "data.sql_query"]
    assert items[0]["score"] == 9.0
    assert items[1]["score"] == 7.0
    assert items[0]["source"] == "llm"
    assert items[0]["reason"].startswith("LLM：")


def test_llm_score_normalization() -> None:
    assert marketplace._score_llm(0.8) == 8.0
    assert marketplace._score_llm(7) == 7.0
    assert marketplace._score_llm(99) == 10.0
    assert marketplace._score_llm("bad") == 0.0
