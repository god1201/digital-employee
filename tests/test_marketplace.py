from types import SimpleNamespace

from app.domains.skills.marketplace.service import (
    build_skills_context_from_packages,
    merge_permissions,
)


def _package(**overrides):
    values = {
        "code": "demo.skill",
        "name": "示例技能",
        "description": "示例",
        "version": 1,
        "tool_codes": [],
        "knowledge_base_ids": [],
        "prompt_template": "只输出结构化结果",
        "permissions": {
            "read_only": True,
            "risk_level": "low",
            "amount_threshold": None,
            "data_scopes": [],
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_merge_permissions_union() -> None:
    read_only = _package()
    writer = _package(
        code="process.ticket",
        tool_codes=["ticket_update"],
        permissions={
            "read_only": False,
            "risk_level": "medium",
            "amount_threshold": 50000,
            "data_scopes": ["contacts"],
        },
    )
    finance = _package(
        code="audit.invoice",
        tool_codes=["invoice_check"],
        permissions={
            "read_only": True,
            "risk_level": "high",
            "amount_threshold": 20000,
            "data_scopes": ["finance"],
        },
    )
    merged = merge_permissions([read_only, writer, finance])

    assert merged["read_only"] is False
    assert merged["risk_level"] == "high"
    assert merged["amount_threshold"] == 20000
    assert merged["tool_codes"] == ["invoice_check", "ticket_update"]
    assert merged["data_scopes"] == ["contacts", "finance"]


def test_merge_permissions_all_read_only() -> None:
    merged = merge_permissions([_package(), _package(code="lang.emotion")])
    assert merged["read_only"] is True
    assert merged["risk_level"] == "low"
    assert merged["amount_threshold"] is None


def test_skills_context() -> None:
    context = build_skills_context_from_packages(
        [
            _package(
                code="data.sql_query",
                name="SQL 查询",
                version=2,
                tool_codes=["sql_query"],
                knowledge_base_ids=[3],
                prompt_template="只生成 SELECT",
            )
        ]
    )
    assert "SQL 查询" in context
    assert "v2" in context
    assert "sql_query" in context
    assert "3" in context
    assert "只生成 SELECT" in context


def test_empty_skills_context() -> None:
    assert build_skills_context_from_packages([]) == "（未装配技能）"
