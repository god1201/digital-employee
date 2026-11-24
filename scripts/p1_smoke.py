"""P1 失败归因 / 综合评估 / 上岗认证端到端冒烟测试。

先重启后端（确保加载最新代码并启动内联 Worker），再运行：

    .venv\\Scripts\\python.exe scripts\\p1_smoke.py

覆盖：
- 接管增量自动归因（文本改写 → style_mismatch）
- 归因转学习工件
- assertion 评估套件：好/坏输出与基线回归
- 学习工件生效前强制评估拦截
- 认证样本不足 / 影子试运行样本不足
- 任务失败自动归因（tool_misuse）
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


def main() -> None:
    global token
    wait_health()

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
            "name": f"P1 冒烟员工 {SUFFIX}",
            "code": f"p1_emp_{SUFFIX}",
            "position": "应收账款专员",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是应收账款专员。",
            "config": {},
        },
    )
    employee_id = employee["id"]

    intervention = call(
        "POST",
        "/interventions",
        json={
            "employee_id": employee_id,
            "source_type": "single_demonstration",
            "original_output": {"text": "请尽快回款", "summary": "催款"},
            "final_output": {"text": "请尽快回款，附件为对账明细", "summary": "催款并附明细"},
            "comment": "只改写了文本",
        },
    )
    attribution = call(
        "POST", "/attributions/analyze", json={"intervention_id": intervention["id"]}
    )
    assert attribution["category"] == "style_mismatch", attribution
    artifact = call("POST", f"/attributions/{attribution['id']}/artifact", json={})
    artifact_id = artifact["id"]

    suite = call(
        "POST",
        "/evaluation-suites",
        json={
            "employee_id": employee_id,
            "name": "回款话术回归",
            "code": f"suite_{SUFFIX}",
            "threshold": 0.8,
            "enforce_on_activate": False,
        },
    )
    suite_id = suite["id"]
    case_a = call(
        "POST",
        f"/evaluation-suites/{suite_id}/cases",
        json={
            "name": "必须提到对账明细",
            "case_type": "assertion",
            "input": {},
            "expected": {"keywords": ["对账明细", "盖章"]},
        },
    )
    case_b = call(
        "POST",
        f"/evaluation-suites/{suite_id}/cases",
        json={
            "name": "必须给出账期",
            "case_type": "assertion",
            "input": {},
            "expected": {"text": "账期45天"},
        },
    )
    good = call(
        "POST",
        f"/evaluation-suites/{suite_id}/run",
        json={
            "outputs": {
                str(case_a["id"]): "已附双方盖章对账明细",
                str(case_b["id"]): "账期45天",
            }
        },
    )
    assert good["passed"] is True and good["score"] == 1.0, good

    bad = call(
        "POST", f"/evaluation-suites/{suite_id}/run", json={"outputs": {}}
    )
    assert bad["passed"] is False and bad["score"] == 0.0, bad
    assert bad["baseline_score"] == 1.0 and bad["delta"] == -1.0, bad

    call("POST", f"/learning-artifacts/{artifact_id}/approve", json={})
    call("PATCH", f"/evaluation-suites/{suite_id}", json={"enforce_on_activate": True})
    blocked = raw("POST", f"/learning-artifacts/{artifact_id}/activate", json={})
    assert blocked.status_code == 400, blocked.text
    runs = call("GET", f"/evaluation-runs?suite_id={suite_id}")
    assert any(item["trigger"] == "artifact_activation" for item in runs["items"])
    call("DELETE", f"/evaluation-suites/{suite_id}")
    activated = call("POST", f"/learning-artifacts/{artifact_id}/activate")
    assert activated["status"] == "active"

    certification = call(
        "POST",
        f"/digital-employees/{employee_id}/trials",
        json={"mode": "certification", "sample_size": 20, "threshold": 0.8},
    )
    assert certification["decision"] == "insufficient_samples", certification
    shadow = call(
        "POST",
        f"/digital-employees/{employee_id}/trials",
        json={"mode": "shadow", "sample_size": 20, "threshold": 0.8},
    )
    assert shadow["status"] == "running", shadow

    tool = call(
        "POST",
        "/tools",
        json={
            "name": "报错工具",
            "code": f"boom_tool_{SUFFIX}",
            "tool_type": "python",
            "description": "故意报错",
            "parameters_schema": {},
            "config": {"code": "def run(args):\n    raise RuntimeError('HTTP 422 参数错误')\n"},
            "risk_level": "low",
            "enabled": True,
            "source": "custom",
        },
    )
    definition = call(
        "POST",
        "/tasks/definitions",
        json={
            "employee_id": employee_id,
            "name": "归因任务",
            "code": f"attr_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "调用报错工具",
                    "type": "tool",
                    "tool_code": tool["code"],
                    "arguments": {},
                }
            ],
            "enabled": True,
        },
    )
    instance = call(
        "POST",
        "/tasks/instances",
        json={"employee_id": employee_id, "definition_id": definition["id"], "input": {}},
    )
    finished = wait_instance(instance["id"], {"failed", "succeeded", "cancelled"})
    assert finished["status"] == "failed", finished
    time.sleep(1)
    attributions = call("GET", f"/attributions?instance_id={instance['id']}")
    assert attributions["items"], "任务失败后没有自动归因"
    assert attributions["items"][0]["category"] == "tool_misuse", attributions["items"][0]

    profile = call("GET", f"/digital-employees/{employee_id}/profile")
    assert profile["total_tasks"] >= 1

    print("\nP1 冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
