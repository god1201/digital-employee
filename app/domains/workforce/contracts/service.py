"""岗位契约服务：契约读写、规划上下文、工具调用红线判定。"""

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.workforce.contracts.models import JobContract
from app.domains.workforce.contracts.schemas import JobContractUpsert

AUTONOMY_LEVELS = {"L0", "L1", "L2", "L3"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class ContractDecision:
    action: str
    reason: str
    rule: str
    autonomy_level: str
    matched: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "rule": self.rule,
            "autonomy_level": self.autonomy_level,
            "matched": self.matched,
        }


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _matches(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword and keyword.lower() in lowered]


def _step_text(
    *,
    step_name: str,
    step_description: str,
    tool_name: str = "",
    tool_code: str = "",
    arguments: dict | None = None,
) -> str:
    parts = [step_name, step_description, tool_name, tool_code]
    if arguments:
        parts.append(json.dumps(arguments, ensure_ascii=False))
    return "\n".join(str(part) for part in parts if part)


def _is_write_tool(tool: Any) -> bool:
    if tool is None:
        return True
    config = getattr(tool, "config", None) or {}
    tool_type = str(getattr(tool, "tool_type", "") or "")
    if tool_type == "http":
        method = str(config.get("method") or "GET").upper()
        return method in WRITE_METHODS
    declared = config.get("read_only")
    if isinstance(declared, bool):
        return not declared
    return True


def _iter_values(arguments: Any, key: str):
    """递归查找 arguments 中指定字段名的数值。"""
    if isinstance(arguments, dict):
        for item_key, value in arguments.items():
            if str(item_key).lower() == key.lower() and isinstance(value, (int, float)):
                yield float(value)
            yield from _iter_values(value, key)
    elif isinstance(arguments, list):
        for item in arguments:
            yield from _iter_values(item, key)


def _threshold_hit(arguments: dict | None, key: str, threshold: float) -> float | None:
    for value in _iter_values(arguments or {}, key):
        if value >= threshold:
            return value
    return None


def evaluate_tool_call(
    contract: JobContract | None,
    *,
    tool: Any,
    arguments: dict | None = None,
    step_name: str = "",
    step_description: str = "",
) -> ContractDecision:
    """在工具执行前判定 allow / ask / deny。

    - deny：触碰 cannot_do 或权限红线，直接失败并告警；
    - ask：命中 must_ask、金额/条数阈值或 L1 自主权，转人工确认；
    - allow：契约允许，自动执行。
    """
    if contract is None or contract.status == "archived":
        return ContractDecision("allow", "未配置岗位契约，按平台默认策略执行", "no_contract", "L2")

    tool_code = str(getattr(tool, "code", "") or "")
    tool_name = str(getattr(tool, "name", "") or "")
    red_lines = contract.red_lines or {}
    forbidden = _as_list(red_lines.get("forbidden_tools"))
    allowed = _as_list(red_lines.get("allowed_tools"))

    if tool_code and tool_code in forbidden:
        return ContractDecision(
            "deny",
            f"工具 {tool_code} 在权限红线禁止清单中",
            "red_line.forbidden_tool",
            contract.autonomy_level,
        )

    if allowed and tool_code and tool_code not in allowed:
        return ContractDecision(
            "deny",
            f"工具 {tool_code} 不在允许清单中",
            "red_line.tool_not_allowed",
            contract.autonomy_level,
        )

    text = _step_text(
        step_name=step_name,
        step_description=step_description,
        tool_name=tool_name,
        tool_code=tool_code,
        arguments=arguments,
    )

    matched_forbidden = _matches(text, _as_list(contract.cannot_do))
    if matched_forbidden:
        return ContractDecision(
            "deny",
            f"命中岗位契约 cannot_do：{', '.join(matched_forbidden)}",
            "contract.cannot_do",
            contract.autonomy_level,
            matched_forbidden,
        )

    if red_lines.get("read_only") and _is_write_tool(tool):
        return ContractDecision(
            "deny",
            "该员工为只读契约，禁止执行写操作工具",
            "red_line.read_only",
            contract.autonomy_level,
        )

    matched_ask = _matches(text, _as_list(contract.must_ask))
    if matched_ask:
        return ContractDecision(
            "ask",
            f"命中 must_ask 请示事项：{', '.join(matched_ask)}",
            "contract.must_ask",
            contract.autonomy_level,
            matched_ask,
        )

    amount_threshold = red_lines.get("amount_threshold")
    if amount_threshold is not None:
        amount_field = str(red_lines.get("amount_field") or "amount")
        hit = _threshold_hit(arguments, amount_field, float(amount_threshold))
        if hit is not None:
            return ContractDecision(
                "ask",
                f"金额 {hit:g} 超过阈值 {float(amount_threshold):g}，需要人工确认",
                "red_line.amount_threshold",
                contract.autonomy_level,
                [amount_field],
            )

    count_threshold = red_lines.get("count_threshold")
    if count_threshold is not None:
        count_field = str(red_lines.get("count_field") or "count")
        hit = _threshold_hit(arguments, count_field, float(count_threshold))
        if hit is not None:
            return ContractDecision(
                "ask",
                f"条数 {hit:g} 超过阈值 {count_threshold}，需要人工确认",
                "red_line.count_threshold",
                contract.autonomy_level,
                [count_field],
            )

    overrides = contract.autonomy_overrides or {}
    level = str(
        overrides.get(f"tool:{tool_code}")
        or overrides.get(tool_code)
        or contract.autonomy_level
        or "L2"
    ).upper()
    if level not in AUTONOMY_LEVELS:
        level = "L1"
    write_tool = _is_write_tool(tool)
    if level == "L0" and write_tool:
        return ContractDecision(
            "deny", "自主权 L0（只答不做）不允许执行写操作", "autonomy.L0", level
        )
    if level == "L1" and write_tool:
        return ContractDecision(
            "ask", "自主权 L1（建议待批）写操作需人工确认", "autonomy.L1", level
        )

    return ContractDecision("allow", "岗位契约校验通过", "contract.allow", level)


async def get_contract(
    db: AsyncSession, tenant_id: int, employee_id: int
) -> JobContract | None:
    return await db.scalar(
        select(JobContract).where(
            JobContract.tenant_id == tenant_id,
            JobContract.employee_id == employee_id,
        )
    )


async def get_active_contract(
    db: AsyncSession, tenant_id: int, employee_id: int | None
) -> JobContract | None:
    if not employee_id:
        return None
    contract = await get_contract(db, tenant_id, employee_id)
    if contract is not None and contract.status == "archived":
        return None
    return contract


async def upsert_contract(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    payload: JobContractUpsert,
    *,
    user_id: int | None = None,
) -> JobContract:
    contract = await get_contract(db, tenant_id, employee_id)
    values = payload.model_dump()
    if contract is None:
        contract = JobContract(
            tenant_id=tenant_id,
            employee_id=employee_id,
            created_by=user_id,
            **values,
        )
        db.add(contract)
        await db.flush()
        return contract

    for field_name, value in values.items():
        setattr(contract, field_name, value)
    contract.version += 1
    await db.flush()
    return contract


def build_contract_context(contract: JobContract | None) -> str:
    """把契约压缩成规划器可读的上下文。"""
    if contract is None:
        return "（未配置岗位契约）"

    lines = [
        f"角色：{contract.role or '未声明'}",
        f"可以做：{'、'.join(_as_list(contract.can_do)) or '未声明'}",
        f"不能做：{'、'.join(_as_list(contract.cannot_do)) or '未声明'}",
        f"必须请示：{'、'.join(_as_list(contract.must_ask)) or '未声明'}",
        f"自主权：{contract.autonomy_level}",
    ]
    if contract.autonomy_overrides:
        overrides = "，".join(
            f"{key}={value}" for key, value in contract.autonomy_overrides.items()
        )
        lines.append(f"自主权覆盖：{overrides}")
    red_lines = contract.red_lines or {}
    red_bits = []
    if red_lines.get("read_only"):
        red_bits.append("只读")
    if red_lines.get("forbidden_tools"):
        red_bits.append(f"禁用工具={','.join(_as_list(red_lines['forbidden_tools']))}")
    if red_lines.get("amount_threshold") is not None:
        red_bits.append(f"金额阈值={red_lines['amount_threshold']}")
    if red_lines.get("count_threshold") is not None:
        red_bits.append(f"条数阈值={red_lines['count_threshold']}")
    if red_bits:
        lines.append(f"权限红线：{'；'.join(red_bits)}")
    if contract.kpi:
        lines.append(f"KPI：{json.dumps(contract.kpi, ensure_ascii=False)}")
    if contract.report_to:
        lines.append(f"汇报对象：{contract.report_to}")
    if contract.report_freq:
        lines.append(f"汇报频率：{contract.report_freq}")
    return "\n".join(lines)
