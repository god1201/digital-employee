"""P2 学习增强端到端冒烟测试。

先重启后端（确保加载最新代码并启动内联 Worker），再运行：

    .venv\\Scripts\\python.exe scripts\\p2_smoke.py

覆盖：
- 学习工件影子 → 金丝雀 → 全量发布与生效上下文
- 共享到组织（副本审批/生效后影响其他员工）
- 主动学习每日预算、结构化提问与回答入库
- 成长周报生成
- 专家轨迹候选、蒸馏与轨迹回放
"""

import os
import sys
import time
import uuid

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


def raw(method: str, path: str, **kwargs) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
    print(f"{method} {path} -> {response.status_code}")
    return response


def wait_health(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get(f"{BASE}/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    print("服务未就绪")
    sys.exit(1)


def wait_instance(instance_id: int, statuses: set[str], timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    detail: dict = {}
    while time.time() < deadline:
        detail = call("GET", f"/tasks/instances/{instance_id}")
        if detail["status"] in statuses:
            return detail
        time.sleep(1)
    print(f"任务未进入预期状态: {detail.get('status')}")
    sys.exit(1)


def create_employee(tag: str, budget: int = 3) -> dict:
    return call(
        "POST",
        "/digital-employees",
        json={
            "name": f"P2 冒烟 {tag} {SUFFIX}",
            "code": f"p2_smoke_{tag}_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {"active_learning_budget": budget},
        },
    )


def main() -> None:
    global token
    wait_health()
    login = call(
        "POST",
        "/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    employee_a = create_employee("a", budget=2)
    employee_b = create_employee("b")
    rule_text = f"结论先行，表格不超过5列-{SUFFIX}"

    artifact = call(
        "POST",
        "/learning-artifacts",
        json={
            "employee_id": employee_a["id"],
            "attribution": "风格不符",
            "target_layer": "persona_layer",
            "risk": "low",
            "scope": "personal",
            "proposal": {"action": "update_style_card", "content": rule_text},
            "evidence": ["人工改写"],
        },
    )
    call("POST", f"/learning-artifacts/{artifact['id']}/approve", json={})

    shadow = call(
        "POST",
        f"/learning-artifacts/{artifact['id']}/rollout",
        json={"mode": "shadow", "note": "影子观察"},
    )
    assert shadow["status"] == "shadow" and shadow["rollout"]["traffic"] == 0.0
    context = call("GET", f"/digital-employees/{employee_a['id']}/artifacts/context")
    assert rule_text not in context["context"]

    canary = call("POST", f"/learning-artifacts/{artifact['id']}/promote")
    assert canary["status"] == "canary" and canary["rollout"]["traffic"] == 0.1
    active = call("POST", f"/learning-artifacts/{artifact['id']}/promote")
    assert active["status"] == "active" and active["rollout"]["traffic"] == 1.0

    context = call("GET", f"/digital-employees/{employee_a['id']}/artifacts/context")
    assert rule_text in context["context"]

    shared = call(
        "POST",
        f"/learning-artifacts/{artifact['id']}/share",
        json={"scope": "organization", "note": "组织共享"},
    )
    assert shared["status"] == "pending_approval" and shared["scope"] == "organization"
    call("POST", f"/learning-artifacts/{shared['id']}/approve", json={})
    call("POST", f"/learning-artifacts/{shared['id']}/activate")
    shared_context = call(
        "GET", f"/digital-employees/{employee_b['id']}/artifacts/context"
    )
    assert rule_text in shared_context["context"], shared_context

    first = call(
        "POST",
        "/learning-questions",
        json={
            "employee_id": employee_a["id"],
            "question": "A客户账期以哪个为准？",
            "options": [
                {"value": "30天", "label": "30天"},
                {"value": "45天", "label": "45天"},
            ],
            "default_option": "45天",
        },
    )
    assert first["budget"]["remaining"] == 1, first
    call(
        "POST",
        "/learning-questions",
        json={
            "employee_id": employee_a["id"],
            "question": "B客户账期？",
            "options": [{"value": "30天", "label": "30天"}],
        },
    )
    exhausted = raw(
        "POST",
        "/learning-questions",
        json={
            "employee_id": employee_a["id"],
            "question": "C客户账期？",
            "options": [{"value": "30天", "label": "30天"}],
        },
    )
    assert exhausted.status_code == 400, exhausted.text

    answered = call(
        "POST",
        f"/learning-questions/{first['question']['id']}/answer",
        json={"answer": "45天", "note": "以最新合同为准"},
    )
    assert answered["artifact"]["target_layer"] == "semantic_memory"
    budget = call("GET", f"/digital-employees/{employee_a['id']}/learning-budget")
    assert budget["used"] == 2 and budget["remaining"] == 0

    review = call(
        "POST", "/weekly-reviews/generate", json={"employee_id": employee_a["id"]}
    )
    assert "本周" in review["summary"]
    assert call("GET", "/weekly-reviews")["total"] >= 1

    tool = call(
        "POST",
        "/tools",
        json={
            "name": "回显工具",
            "code": f"p2_echo_{SUFFIX}",
            "tool_type": "python",
            "description": "回显参数",
            "parameters_schema": {},
            "config": {"code": "def run(args):\n    return {'echo': args}\n"},
            "risk_level": "low",
            "enabled": True,
            "source": "custom",
        },
    )
    definition = call(
        "POST",
        "/tasks/definitions",
        json={
            "employee_id": employee_a["id"],
            "name": "P2 回放任务",
            "code": f"p2_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "调用回显工具",
                    "type": "tool",
                    "tool_code": tool["code"],
                    "arguments": {"hello": "world"},
                }
            ],
            "enabled": True,
        },
    )
    instance = call(
        "POST",
        "/tasks/instances",
        json={"employee_id": employee_a["id"], "definition_id": definition["id"], "input": {}},
    )
    finished = wait_instance(instance["id"], {"succeeded", "failed", "cancelled"})
    assert finished["status"] == "succeeded", finished

    candidates = call(
        "GET",
        f"/expert-trajectories/candidates?employee_id={employee_a['id']}&limit=10",
    )
    assert any(item["instance_id"] == instance["id"] for item in candidates), candidates
    distilled = call(
        "POST",
        "/expert-trajectories/distill",
        json={"instance_id": instance["id"], "scope": "personal"},
    )
    assert distilled["target_layer"] == "procedural_memory"
    assert distilled["proposal"]["steps"]

    replay = call("GET", f"/tasks/instances/{instance['id']}/replay")
    assert replay["frames"] and replay["frames"][0]["status"] == "succeeded"

    print("\nP2 冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
