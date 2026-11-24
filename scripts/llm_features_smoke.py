"""LLM 归因与技能推荐端到端冒烟。

前置：
- 后端已启动，且已配置 LLM_API_KEY / DEEPSEEK_API_KEY；
- 会产生一次失败任务、一次 LLM 归因复核与一次 LLM 技能推荐调用，注意 Token 成本。

运行：
    .venv\\Scripts\\python.exe scripts\\llm_features_smoke.py
"""

import os
import sys
import time
import uuid
from urllib.parse import quote

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
SUFFIX = uuid.uuid4().hex[:6]
client = httpx.Client(timeout=120.0)
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
    assert client.get(f"{BASE}/health").status_code == 200

    login = call(
        "POST",
        "/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    employee = call(
        "POST",
        "/digital-employees",
        json={
            "name": f"LLM 冒烟 {SUFFIX}",
            "code": f"llm_smoke_{SUFFIX}",
            "position": "应收账款专员",
            "description": "负责回款催收、对账与月报",
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
            "name": "LLM 冒烟必败工具",
            "code": f"llm_fail_{SUFFIX}",
            "tool_type": "python",
            "description": "制造工具失败",
            "parameters_schema": {},
            "config": {
                "code": "def run(args):\n    raise RuntimeError('llm smoke boom')\n"
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
            "name": "LLM 归因冒烟任务",
            "code": f"llm_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "查询客户回款状态",
                    "type": "tool",
                    "tool_code": tool["code"],
                    "arguments": {"customer": "A 客户"},
                }
            ],
            "enabled": True,
        },
    )
    instance = call(
        "POST",
        "/tasks/instances",
        json={
            "employee_id": employee["id"],
            "definition_id": definition["id"],
            "input": {"customer": "A 客户"},
        },
    )
    finished = wait_instance(instance["id"])
    assert finished["status"] == "failed", finished

    attributions = call(
        "GET", f"/attributions?employee_id={employee['id']}&page_size=20"
    )
    own = [
        item
        for item in attributions["items"]
        if item["instance_id"] == instance["id"]
    ]
    assert own, attributions
    reanalyzed = call(
        "POST", f"/attributions/{own[0]['id']}/reanalyze-llm", json={}
    )
    assert reanalyzed["source"] == "llm", reanalyzed

    need = quote("催收回款并生成月报")
    recommendations = call(
        "GET",
        f"/digital-employees/{employee['id']}/skills/recommend"
        f"?need={need}&use_llm=true",
    )
    assert isinstance(recommendations, list), recommendations
    assert recommendations, recommendations
    assert any(item.get("source") == "llm" for item in recommendations), recommendations
    print("推荐来源:", [item.get("source") for item in recommendations])

    print("\nLLM 归因与技能推荐冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
