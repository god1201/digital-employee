import pytest

from app.core.exceptions import BadRequestError
from app.domains.workflows.approvals.service import (
    evaluate_condition,
    normalize_approvers,
    normalize_fields,
    normalize_nodes,
    validate_form_data,
)


def test_normalize_fields() -> None:
    fields = normalize_fields(
        [
            {"name": "amount", "label": "金额", "type": "number", "required": True},
            {
                "name": "category",
                "label": "类型",
                "type": "select",
                "options": ["差旅", {"value": "meal", "label": "餐饮"}],
            },
        ]
    )
    assert fields[0]["type"] == "number"
    assert fields[1]["options"][0] == {"value": "差旅", "label": "差旅"}
    with pytest.raises(BadRequestError):
        normalize_fields([{"name": "x", "type": "unknown"}])
    with pytest.raises(BadRequestError):
        normalize_fields([{"name": "x"}, {"name": "x"}])


def test_validate_form_data() -> None:
    fields = normalize_fields(
        [
            {"name": "amount", "label": "金额", "type": "number", "required": True},
            {
                "name": "category",
                "label": "类型",
                "type": "select",
                "options": ["travel", "meal"],
            },
            {"name": "day", "label": "日期", "type": "date"},
            {"name": "users", "label": "审批人", "type": "users"},
        ]
    )
    data = validate_form_data(
        fields, {"amount": "5000", "category": "travel", "day": "2026-01-02", "users": [1, 2]}
    )
    assert data["amount"] == 5000
    assert data["day"] == "2026-01-02"
    assert data["users"] == [1, 2]
    with pytest.raises(BadRequestError):
        validate_form_data(fields, {"category": "travel"})
    with pytest.raises(BadRequestError):
        validate_form_data(fields, {"amount": 1, "category": "invalid"})


def test_normalize_nodes() -> None:
    nodes = normalize_nodes(
        [
            {
                "key": "c1",
                "type": "condition",
                "field": "amount",
                "operator": "gt",
                "value": 5000,
                "on_true": "boss",
                "on_false": "finance",
            },
            {
                "key": "finance",
                "type": "approval",
                "approvers": ["admin", "initiator", 1],
                "mode": "sequence",
                "timeout_hours": 12,
                "timeout_action": "remind",
            },
            {
                "key": "boss",
                "type": "approval",
                "approvers": [1],
                "mode": "all",
            },
            {"key": "end", "type": "end"},
        ]
    )
    assert [node["key"] for node in nodes] == ["c1", "finance", "boss", "end"]
    assert nodes[1]["mode"] == "sequence"
    with pytest.raises(BadRequestError):
        normalize_nodes([{"key": "a", "type": "approval", "approvers": []}])
    with pytest.raises(BadRequestError):
        normalize_nodes(
            [{"key": "a", "type": "condition", "field": "x", "on_true": "missing"}]
        )


def test_normalize_approvers() -> None:
    assert normalize_approvers(["admin", "initiator", 3, "5", True]) == [
        "admin",
        "initiator",
        3,
        5,
    ]
    assert normalize_approvers([1, 1, "1"]) == [1]


def test_evaluate_condition() -> None:
    data = {"amount": 8000, "category": "travel", "description": "出差报销"}
    assert evaluate_condition(
        {"field": "amount", "operator": "gt", "value": 5000}, data
    )
    assert not evaluate_condition(
        {"field": "amount", "operator": "lt", "value": 5000}, data
    )
    assert evaluate_condition(
        {"field": "category", "operator": "eq", "value": "travel"}, data
    )
    assert evaluate_condition(
        {"field": "category", "operator": "in", "value": ["travel", "meal"]}, data
    )
    assert evaluate_condition(
        {"field": "description", "operator": "contains", "value": "出差"}, data
    )
    assert evaluate_condition({"field": "amount", "operator": "exists"}, data)
    assert not evaluate_condition(
        {"field": "missing", "operator": "exists"}, data
    )
