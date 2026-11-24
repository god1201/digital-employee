"""P0 岗位契约与学习闭环端到端冒烟测试。

先重启后端（确保加载最新代码并启动内联 Worker），再运行：

    .venv\\Scripts\\python.exe scripts\\p0_smoke.py

覆盖：
- 岗位契约创建 / 读取 / 预检
- 偏好记忆写入与提示词上下文
- 接管增量采集与 diff
- 接管增量 → 学习工件 → 审批 → 生效 → 回滚
- L1 自主权写操作自动转人工，放行后重新执行并成功
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
            "name": f"P0 冒烟员工 {SUFFIX}",
            "code": f"p0_emp_{SUFFIX}",
            "position": "应收账款专员",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是应收账款专员。",
            "config": {},
        },
    )
    employee_id = employee["id"]

    contract = call(
        "PUT",
        f"/digital-employees/{employee_id}/contract",
        json={
            "role": "应收账款专员",
            "can_do": ["账款核对", "生成对账单", "发送催款邮件"],
            "cannot_do": ["修改合同金额", "承诺减免"],
            "must_ask": ["减免申请", "单笔超过50万"],
            "kpi": {"回款率": ">=85%"},
            "report_to": "财务主管-张三",
            "report_freq": "每日18:00日报",
            "autonomy_level": "L1",
            "autonomy_overrides": {"tool:query_erp": "L3"},
            "red_lines": {
                "forbidden_tools": ["drop_database"],
                "amount_threshold": 500000,
                "amount_field": "amount",
            },
            "status": "active",
        },
    )
    assert contract["version"] == 1

    decision = call(
        "POST",
        f"/digital-employees/{employee_id}/contract/check",
        json={
            "tool_code": "send_email",
            "arguments": {"amount": 800000},
            "step_name": "发送催款邮件",
        },
    )
    assert decision["action"] == "ask", decision

    preference = call(
        "POST",
        "/preferences",
        json={
            "employee_id": employee_id,
            "key": "address_style",
            "value": "以后称呼我为王哥；结论先行。",
            "scope": "personal",
            "source": "real_time",
        },
    )
    context = call("GET", f"/preferences/context/{employee_id}")
    assert preference["key"] in context["context"]

    intervention = call(
        "POST",
        "/interventions",
        json={
            "employee_id": employee_id,
            "source_type": "single_demonstration",
            "original_output": {"text": "请尽快回款", "attachments": []},
            "final_output": {
                "text": "请尽快回款，附件为双方盖章对账明细",
                "attachments": ["对账明细.pdf"],
            },
            "comment": "缺少附件被退回 3 次",
        },
    )
    detail = call("GET", f"/interventions/{intervention['id']}")
    assert detail["summary"]["total"] >= 2, detail

    artifact = call(
        "POST",
        f"/interventions/{intervention['id']}/artifact",
        json={
            "attribution": "规划错误-步骤缺失",
            "target_layer": "procedural_memory",
            "risk": "medium",
            "scope": "personal",
            "proposal": {
                "action": "add_sop_step",
                "content": "发送催款邮件前必须附上双方盖章的对账明细",
            },
        },
    )
    assert artifact["status"] == "pending_approval"
    artifact_id = artifact["id"]

    assert call("POST", f"/learning-artifacts/{artifact_id}/approve", json={"note": "同意"})[
        "status"
    ] == "approved"
    assert call("POST", f"/learning-artifacts/{artifact_id}/activate")["status"] == "active"
    assert call("POST", f"/learning-artifacts/{artifact_id}/rollback", json={"note": "试点回滚"})[
        "status"
    ] == "rolled_back"

    tool = call(
        "POST",
        "/tools",
        json={
            "name": "回显工具",
            "code": f"echo_tool_{SUFFIX}",
            "tool_type": "python",
            "description": "回显参数",
            "parameters_schema": {},
            "config": {"code": "def run(args):\n    return {'echo': args}\n", "read_only": False},
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
            "name": "契约门禁任务",
            "code": f"gate_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "发送邮件",
                    "type": "tool",
                    "tool_code": tool["code"],
                    "arguments": {"amount": 1},
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
    waiting = wait_instance(instance["id"], {"waiting_human", "succeeded", "failed"})
    assert waiting["status"] == "waiting_human", waiting
    assert any((step.get("output") or {}).get("contract_gate") for step in waiting["steps"])

    call(
        "POST",
        f"/tasks/instances/{instance['id']}/resume",
        json={"approved": True, "comment": "L1 放行"},
    )
    finished = wait_instance(instance["id"], {"succeeded", "failed", "cancelled"})
    assert finished["status"] == "succeeded", finished

    print("\nP0 冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
