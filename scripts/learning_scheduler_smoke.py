"""学习节奏自动化端到端冒烟。

覆盖：
- 日结批量归因接口返回与自动提问（同类复发触发）
- 学习节奏调度状态
- 数字履历能力雷达与学习曲线
- 批量周报生成与 webhook 未配置时的投递反馈

运行前确保后端已重启加载最新代码：

    .venv\\Scripts\\python.exe scripts\\learning_scheduler_smoke.py
"""

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
SUFFIX = uuid.uuid4().hex[:6]
client = httpx.Client(timeout=60.0)
token: str | None = None


def call(method: str, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        print(f"{method} {path} -> {response.status_code} non-JSON")
        sys.exit(1)
    print(f"{method} {path} -> {response.status_code}")
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(payload)
        sys.exit(1)
    return payload.get("data")


def wait_instance(instance_id: int, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    detail: dict = {}
    while time.time() < deadline:
        detail = call("GET", f"/tasks/instances/{instance_id}")
        if detail["status"] in {"succeeded", "failed", "cancelled"}:
            return detail
        time.sleep(1)
    print(f"任务未结束: {detail.get('status')}")
    sys.exit(1)


def main() -> None:
    global token
    health = client.get(f"{BASE}/health")
    assert health.status_code == 200, health.text

    login = call(
        "POST",
        "/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    status_before = call("GET", "/learning/scheduler/status")
    assert status_before["timezone"] == "UTC"
    assert status_before["daily_at"] and status_before["weekly_at"]

    employee = call(
        "POST",
        "/digital-employees",
        json={
            "name": f"学习节奏冒烟 {SUFFIX}",
            "code": f"learn_smoke_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {"active_learning_budget": 3},
        },
    )
    tool = call(
        "POST",
        "/tools",
        json={
            "name": "必败工具",
            "code": f"learn_fail_{SUFFIX}",
            "tool_type": "python",
            "description": "用于制造可归因失败",
            "parameters_schema": {},
            "config": {
                "code": "def run(args):\n    raise RuntimeError('smoke boom')\n"
            },
            "risk_level": "low",
            "enabled": True,
            "source": "custom",
        },
    )
    definition = call(
        "POST",
        "/tasks/definitions",
        json={
            "employee_id": employee["id"],
            "name": "学习节奏失败任务",
            "code": f"learn_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "执行必败工具",
                    "type": "tool",
                    "tool_code": tool["code"],
                    "arguments": {"hello": "world"},
                }
            ],
            "enabled": True,
        },
    )
    instances = []
    for _ in range(2):
        instance = call(
            "POST",
            "/tasks/instances",
            json={
                "employee_id": employee["id"],
                "definition_id": definition["id"],
                "input": {},
            },
        )
        finished = wait_instance(instance["id"])
        assert finished["status"] == "failed", finished
        instances.append(instance["id"])

    daily = call(
        "POST", "/learning/jobs/daily-batch?lookback_hours=24", json={}
    )
    assert "attribution" in daily and "questions" in daily, daily

    attributions = call(
        "GET", f"/attributions?employee_id={employee['id']}&page_size=20"
    )
    categories = {item["category"] for item in attributions["items"]}
    assert "tool_misuse" in categories, attributions

    questions = call(
        "GET", f"/learning-questions?employee_id={employee['id']}&page_size=20"
    )
    auto_questions = [
        item
        for item in questions["items"]
        if item["question"].startswith("（自动触发）")
    ]
    assert auto_questions, questions
    assert any("类失败出现" in item["question"] for item in auto_questions)

    profile = call("GET", f"/digital-employees/{employee['id']}/profile")
    radar = profile.get("capability_radar") or []
    assert len(radar) >= 5, profile
    assert all(0 <= float(axis["value"]) <= 1 for axis in radar), radar

    trend = call("GET", f"/digital-employees/{employee['id']}/profile/trend?days=30")
    assert len(trend["series"]) == 30, trend
    assert any(item["total"] >= 2 for item in trend["series"]), trend

    now = datetime.now(UTC)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    batch = call(
        "POST",
        "/weekly-reviews/generate-batch",
        json={
            "week_start": week_start.isoformat(),
            "force": True,
            "deliver": False,
        },
    )
    own = [
        item for item in batch["items"] if item["employee_id"] == employee["id"]
    ]
    assert own, batch

    delivered = call(
        "POST", f"/weekly-reviews/{own[0]['review_id']}/deliver", json={}
    )
    assert delivered["delivery"]["delivered"] is False
    assert delivered["delivery"].get("reason") or delivered["delivery"].get("error")

    print("\n学习节奏自动化冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
