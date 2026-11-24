from types import SimpleNamespace

from app.domains.governance.quality.hallucination import score_grounding
from app.domains.learning.memory import memory_key
from app.domains.learning.onboarding import extract_contract_heuristic
from app.domains.workforce.employees.service import bound_knowledge_base_ids
from app.domains.workforce.persona.service import (
    build_persona_context,
    find_taboo,
)
from app.domains.workforce.prompting import estimate_tokens, fit_sections
from app.domains.workforce.routing import score_contact
from app.domains.workforce.templates.seed import TEMPLATE_SEEDS


def _persona(**overrides):
    values = {
        "tone": "professional",
        "address_style": "称呼王哥",
        "output_format": "conclusion_first",
        "report_style": "conclusion_first",
        "taboo_words": ["绝对", "百分百"],
        "signature": "财务部",
        "extra_instructions": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_persona_context_and_taboo() -> None:
    context = build_persona_context(_persona())
    assert "人格表现层" in context
    assert "称呼王哥" in context
    assert "结论先行" in context
    assert find_taboo("我们绝对可以退款", _persona()) == ["绝对"]
    assert find_taboo("正常内容", _persona()) == []


def test_prompt_budget() -> None:
    assert estimate_tokens("a" * 25) >= 1
    sections = [("契约", "a" * 100), ("技能", "b" * 100)]
    def counter(text: str) -> int:
        return len(text) // 10

    only_first = fit_sections(sections, 10, counter=counter)
    assert "a" * 100 in only_first
    assert "b" * 100 not in only_first

    truncated = fit_sections(sections, 15, counter=counter)
    assert "按提示词预算压缩" in truncated
    assert "b" * 100 not in truncated
    assert "b" * 50 in truncated

    unlimited = fit_sections(sections, 0, counter=counter)
    assert "a" * 100 in unlimited and "b" * 100 in unlimited


def test_tokenizer_measurement() -> None:
    from app.core.tokenizer import count_tokens, heuristic_tokens, tokenizer_backend

    assert count_tokens("") == 0
    assert count_tokens("hello world") >= 1
    assert count_tokens("客户账期以合同为准") >= 1
    assert heuristic_tokens("") == 0
    assert tokenizer_backend() in {"tiktoken", "heuristic"}


def test_bound_knowledge_base_ids() -> None:
    assert bound_knowledge_base_ids(None) == []
    assert bound_knowledge_base_ids(SimpleNamespace(config={})) == []
    assert bound_knowledge_base_ids(
        SimpleNamespace(
            config={"knowledge_base_ids": [3, "5", 3, "bad", 0, -1]}
        )
    ) == [3, 5]


def test_routing_score() -> None:
    assert score_contact("回款 合同", "应收账款专员 负责回款与合同初审") == 2
    assert score_contact("", "任意") == 0
    assert score_contact("税务", "负责回款") == 0


def test_onboarding_heuristic_extract() -> None:
    text = (
        "应收账款专员\n"
        "- 负责账款核对\n"
        "- 生成对账单\n"
        "- 不得修改合同金额\n"
        "- 单笔超过50万需审批\n"
    )
    result = extract_contract_heuristic(text)
    assert result["role"] == "应收账款专员"
    assert "负责账款核对" in result["can_do"]
    assert "生成对账单" in result["can_do"]
    assert "不得修改合同金额" in result["cannot_do"]
    assert "单笔超过50万需审批" in result["must_ask"]
    assert result["source"] == "heuristic"


def test_hallucination_grounding() -> None:
    sources = [
        "订单签收后 7 天内可以申请无理由退款。退款需提供订单号与支付凭证。"
    ]
    good = score_grounding("订单签收后 7 天内可以申请无理由退款。", sources)
    assert good["grounded"] is True
    assert good["score"] >= 0.8

    bad = score_grounding("公司提供终身免费换新并承担全部运费。", sources)
    assert bad["grounded"] is False
    assert bad["score"] < 0.6

    empty = score_grounding("任意答案", [])
    assert empty["grounded"] is False


def test_job_template_seeds() -> None:
    assert len(TEMPLATE_SEEDS) >= 8
    for seed in TEMPLATE_SEEDS:
        assert seed["skill_codes"]
        assert seed["persona"]
        assert seed["contract"]
        assert seed["contract"].get("can_do")


def test_memory_key() -> None:
    artifact = SimpleNamespace(
        proposal={"key": "customer_a_credit_days", "content": "45 天"}
    )
    assert memory_key(artifact) == "customer_a_credit_days"
    assert memory_key(SimpleNamespace(proposal={"content": "无 key"})) is None
