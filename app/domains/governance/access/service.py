import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance.access.models import AccessRule


def path_matches(pattern: str, path: str) -> bool:
    """支持 `/admin/**` 与 `/user/*` 两种通配写法。"""
    if not pattern:
        return False
    regex = re.escape(pattern)
    regex = regex.replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    try:
        return re.fullmatch(regex, path) is not None
    except re.error:
        return False


@dataclass
class AccessDecision:
    allowed: bool
    effect: str
    rule_id: int | None = None
    reason: str = ""


async def evaluate_access(
    db: AsyncSession,
    tenant_id: int,
    *,
    employee_id: int,
    method: str,
    path: str,
    system_code: str | None = None,
) -> AccessDecision:
    """按优先级评估访问规则：默认拒绝，priority 越大越优先，同级 deny 胜出。"""
    stmt = select(AccessRule).where(
        AccessRule.tenant_id == tenant_id,
        AccessRule.enabled.is_(True),
    )
    rules = list((await db.scalars(stmt)).all())

    matched: list[AccessRule] = []
    for rule in rules:
        if rule.employee_id is not None and rule.employee_id != employee_id:
            continue
        if rule.system_code:
            if system_code is None or rule.system_code != system_code:
                continue
        if rule.method != "*" and rule.method.upper() != method.upper():
            continue
        if path_matches(rule.path_pattern, path):
            matched.append(rule)

    if not matched:
        return AccessDecision(
            allowed=False,
            effect="deny",
            rule_id=None,
            reason="默认拒绝：未匹配到任何允许规则",
        )

    matched.sort(key=lambda rule: (rule.priority, rule.effect == "deny"), reverse=True)
    winner = matched[0]
    allowed = winner.effect == "allow"
    return AccessDecision(
        allowed=allowed,
        effect=winner.effect,
        rule_id=winner.id,
        reason=f"命中规则 #{winner.id}（{winner.path_pattern} -> {winner.effect}）",
    )
