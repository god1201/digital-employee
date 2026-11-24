"""P3 多员工协作 / DPO 数据 / 能力迁移端到端冒烟测试。

先重启后端（确保只有最新代码的 Worker 在跑），再运行：

    .venv\\Scripts\\python.exe scripts\\p3_smoke.py

覆盖：
- 多员工协作：employee 委派步骤、子任务执行、父任务汇总
- DPO：接管增量采集偏好对、JSONL 导出、训练任务状态回调
- 能力迁移：dry_run 预览、执行后目标获得技能/偏好/契约草稿/待审批工件
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


def wait_instance(instance_id: int, statuses: set[str], timeout: float = 60.0) -> dict:
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
            "name": f"P3 冒烟 {tag} {SUFFIX}",
            "code": f"p3_smoke_{tag}_{SUFFIX}",
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

    source = create_employee("a", budget=2)
    target = create_employee("b")
    echo = call(
        "POST",
        "/tools",
        json={
            "name": "回显工具",
            "code": f"p3_echo_{SUFFIX}",
            "tool_type": "python",
            "description": "回显",
            "parameters_schema": {},
            "config": {"code": "def run(args):\n    return {'echo': args}\n"},
            "risk_level": "low",
            "enabled": True,
            "source": "custom",
        },
    )

    collaboration = call(
        "POST",
        "/collaborations",
        json={
            "owner_employee_id": source["id"],
            "goal": "核对两家客户回款",
            "summarize": False,
            "participants": [
                {
                    "employee_id": target["id"],
                    "instruction": "查 A 客户",
                    "steps": [
                        {
                            "name": "查A",
                            "type": "tool",
                            "tool_code": echo["code"],
                            "arguments": {"customer": "A"},
                        }
                    ],
                },
                {
                    "employee_id": source["id"],
                    "instruction": "查 B 客户",
                    "steps": [
                        {
                            "name": "查B",
                            "type": "tool",
                            "tool_code": echo["code"],
                            "arguments": {"customer": "B"},
                        }
                    ],
                },
            ],
        },
    )
    parent_id = collaboration["parent_instance_id"]
    assert parent_id
    parent = wait_instance(parent_id, {"succeeded", "failed", "cancelled"})
    assert parent["status"] == "succeeded", parent
    assert [step["step_type"] for step in parent["steps"]].count("employee") == 2

    parallel = call(
        "POST",
        "/collaborations",
        json={
            "owner_employee_id": source["id"],
            "goal": "并行核对两家客户回款",
            "mode": "parallel",
            "summarize": False,
            "participants": [
                {
                    "employee_id": target["id"],
                    "instruction": "查 A 客户",
                    "steps": [
                        {
                            "name": "查A",
                            "type": "tool",
                            "tool_code": echo["code"],
                            "arguments": {"customer": "A"},
                        }
                    ],
                },
                {
                    "employee_id": source["id"],
                    "instruction": "查 B 客户",
                    "steps": [
                        {
                            "name": "查B",
                            "type": "tool",
                            "tool_code": echo["code"],
                            "arguments": {"customer": "B"},
                        }
                    ],
                },
            ],
        },
    )
    parallel_parent = wait_instance(
        parallel["parent_instance_id"], {"succeeded", "failed", "cancelled"}
    )
    assert parallel_parent["status"] == "succeeded", parallel_parent
    assert any(step["step_type"] == "parallel" for step in parallel_parent["steps"])

    call(
        "POST",
        "/interventions",
        json={
            "employee_id": source["id"],
            "source_type": "single_demonstration",
            "original_output": {"text": "请尽快回款"},
            "final_output": {"text": "请尽快回款，附对账明细"},
            "comment": "缺附件",
        },
    )
    collected = call(
        "POST",
        "/preference-pairs/collect",
        json={
            "employee_id": source["id"],
            "sources": ["intervention"],
            "limit": 50,
        },
    )
    assert collected["created"] >= 1, collected
    exported = call(
        "POST",
        "/preference-pairs/export",
        json={"employee_id": source["id"]},
    )
    assert exported["count"] >= 1 and exported["bytes"] > 0, exported
    job = call(
        "POST",
        "/training-jobs",
        json={
            "employee_id": source["id"],
            "method": "dpo",
            "dataset_path": exported["path"],
            "config": {"epochs": 1},
        },
    )
    assert job["status"] == "pending"
    call("POST", f"/training-jobs/{job['id']}/status", json={"status": "running"})
    finished = call(
        "POST",
        f"/training-jobs/{job['id']}/status",
        json={"status": "succeeded", "metrics": {"loss": 0.12}},
    )
    assert finished["status"] == "succeeded"

    call(
        "PUT",
        f"/digital-employees/{source['id']}/contract",
        json={
            "role": "应收专员",
            "can_do": ["核对"],
            "cannot_do": ["减免"],
            "must_ask": ["减免申请"],
            "autonomy_level": "L2",
            "red_lines": {},
            "status": "active",
        },
    )
    call(
        "POST",
        f"/digital-employees/{source['id']}/skills",
        json={"code": "data.report"},
    )
    artifact = call(
        "POST",
        "/learning-artifacts",
        json={
            "employee_id": source["id"],
            "attribution": "风格不符",
            "target_layer": "persona_layer",
            "risk": "low",
            "scope": "personal",
            "proposal": {"content": f"结论先行-{SUFFIX}"},
            "evidence": ["smoke"],
        },
    )
    call("POST", f"/learning-artifacts/{artifact['id']}/approve", json={})
    call("POST", f"/learning-artifacts/{artifact['id']}/activate")
    call(
        "POST",
        "/preferences",
        json={
            "employee_id": source["id"],
            "key": "address_style",
            "value": "称呼王哥",
            "scope": "personal",
            "source": "manual",
        },
    )

    dry = call(
        "POST",
        "/capability-migrations",
        json={
            "source_employee_id": source["id"],
            "target_employee_id": target["id"],
            "components": ["skills", "artifacts", "preferences", "contract"],
            "dry_run": True,
        },
    )
    assert dry["report"]["skills"]["planned"], dry
    migration = call(
        "POST",
        "/capability-migrations",
        json={
            "source_employee_id": source["id"],
            "target_employee_id": target["id"],
            "components": ["skills", "artifacts", "preferences", "contract"],
            "dry_run": False,
        },
    )
    assert migration["status"] == "completed", migration
    target_skills = call("GET", f"/digital-employees/{target['id']}/skills")
    assert {item["skill_code"] for item in target_skills} >= {
        "data.sql_query",
        "data.report",
    }
    target_preferences = call("GET", f"/preferences?employee_id={target['id']}")
    assert any(item["key"] == "address_style" for item in target_preferences["items"])
    target_contract = call(
        "GET", f"/digital-employees/{target['id']}/contract"
    )
    assert target_contract["status"] == "draft"
    target_context = call(
        "GET", f"/digital-employees/{target['id']}/artifacts/context"
    )
    assert f"结论先行-{SUFFIX}" in target_context["context"]

    print("\nP3 冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
