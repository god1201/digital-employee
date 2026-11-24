"""任务级 Token / 成本预算。"""

from typing import Any


def _number(config: dict | None, key: str) -> float:
    if not isinstance(config, dict):
        return 0.0
    value: Any = config.get(key)
    if value in (None, ""):
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def budget_limits(config: dict | None) -> tuple[float, float]:
    """返回 (max_tokens_per_task, max_cost_per_task)，0 表示不限制。"""
    return (
        _number(config, "max_tokens_per_task"),
        _number(config, "max_cost_per_task"),
    )


def budget_exceeded(
    used_tokens: float,
    used_cost: float,
    limits: tuple[float, float],
) -> str | None:
    token_limit, cost_limit = limits
    if token_limit > 0 and used_tokens > token_limit:
        return f"任务 Token 预算超限：{used_tokens:g} > {token_limit:g}"
    if cost_limit > 0 and used_cost > cost_limit:
        return f"任务成本预算超限：{used_cost:.4f} > {cost_limit:g}"
    return None
