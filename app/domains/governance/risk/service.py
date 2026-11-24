from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.governance.risk.models import RiskRule

SEVERITY_SCORE = {"low": 1.0, "medium": 2.0, "high": 3.0}
ACTION_PRIORITY = {"allow": 0, "review": 1, "block": 2}


async def evaluate_risk(
    db: AsyncSession,
    tenant_id: int,
    content: str,
    category: str = "content",
) -> dict:
    rules = list(
        (
            await db.scalars(
                select(RiskRule).where(
                    RiskRule.tenant_id == tenant_id,
                    RiskRule.enabled.is_(True),
                    RiskRule.category == category,
                )
            )
        ).all()
    )

    lowered = content.lower()
    matched: list[dict] = []
    score = 0.0
    decision = "allow"

    for rule in rules:
        hits = [
            str(keyword) for keyword in (rule.keywords or []) if str(keyword).lower() in lowered
        ]
        if not hits:
            continue
        matched.append(
            {
                "rule_id": rule.id,
                "name": rule.name,
                "action": rule.action,
                "severity": rule.severity,
                "hits": hits,
            }
        )
        score += SEVERITY_SCORE.get(rule.severity, 1.0)
        if ACTION_PRIORITY.get(rule.action, 0) > ACTION_PRIORITY.get(decision, 0):
            decision = rule.action

    return {"decision": decision, "score": score, "matched_rules": matched}
