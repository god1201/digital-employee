import re

from app.domains.governance.quality.models import InspectionRule


def _rule_hit(rule: InspectionRule, content: str) -> tuple[bool, dict]:
    config = rule.config or {}
    lowered = content.lower()

    if rule.rule_type == "keyword":
        keywords = [
            str(keyword).strip()
            for keyword in (config.get("keywords") or [])
            if str(keyword).strip()
        ]
        hits = [keyword for keyword in keywords if keyword.lower() in lowered]
        return bool(hits), {"hits": hits}

    if rule.rule_type == "regex":
        pattern = str(config.get("pattern") or "")
        if not pattern:
            return False, {}
        try:
            match = re.search(pattern, content, re.IGNORECASE)
        except re.error:
            return False, {"error": "invalid regex"}
        return bool(match), {"match": match.group(0) if match else None}

    if rule.rule_type == "min_length":
        try:
            value = int(config.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        return len(content) < value, {"length": len(content), "min": value}

    if rule.rule_type == "max_length":
        try:
            value = int(config.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        return len(content) > value, {"length": len(content), "max": value}

    return False, {}


def evaluate_inspection(rules: list[InspectionRule], content: str) -> dict:
    score = 100.0
    rule_results: list[dict] = []
    blocking_hit = False

    for rule in rules:
        hit, detail = _rule_hit(rule, content)
        if hit:
            score -= rule.penalty
            blocking_hit = blocking_hit or rule.blocking
        rule_results.append(
            {
                "rule_id": rule.id,
                "name": rule.name,
                "rule_type": rule.rule_type,
                "hit": hit,
                "penalty": rule.penalty,
                "blocking": rule.blocking,
                "detail": detail,
            }
        )

    score = max(0.0, min(100.0, score))
    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    else:
        grade = "D"

    if blocking_hit:
        decision = "reject"
    elif score >= 75:
        decision = "pass"
    else:
        decision = "review"

    return {
        "score": round(score, 1),
        "grade": grade,
        "decision": decision,
        "rule_results": rule_results,
    }
