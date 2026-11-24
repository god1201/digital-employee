"""员工知识库绑定端到端冒烟。

覆盖：
- 设置/读取员工知识库绑定
- 已绑定知识库的检索步骤正常执行
- 未绑定知识库的检索步骤被拒绝
- 清空绑定后恢复为“不限制”

运行前确保后端已重启：

    .venv\\Scripts\\python.exe scripts\\knowledge_binding_smoke.py
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


def create_kb(name: str, code: str) -> dict:
    return call(
        "POST",
        "/knowledge-bases",
        json={
            "name": name,
            "code": code,
            "domain": "custom",
            "description": "知识库绑定冒烟",
            "status": "active",
        },
    )


def create_knowledge_task(
    employee_id: int,
    code: str,
    knowledge_base_id: int,
) -> dict:
    definition = call(
        "POST",
        "/tasks/definitions",
        json={
            "employee_id": employee_id,
            "name": code,
            "code": code,
            "task_type": "fixed",
            "steps": [
                {
                    "name": "检索知识库",
                    "type": "knowledge",
                    "knowledge_base_id": knowledge_base_id,
                    "query": "测试查询",
                }
            ],
            "enabled": True,
        },
    )
    return call(
        "POST",
        "/tasks/instances",
        json={
            "employee_id": employee_id,
            "definition_id": definition["id"],
            "input": {},
        },
    )


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
            "name": f"知识绑定冒烟 {SUFFIX}",
            "code": f"kb_bind_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {},
        },
    )
    kb_allowed = create_kb(f"允许知识库 {SUFFIX}", f"kb_ok_{SUFFIX}")
    kb_denied = create_kb(f"禁止知识库 {SUFFIX}", f"kb_no_{SUFFIX}")

    bound = call(
        "PUT",
        f"/digital-employees/{employee['id']}/knowledge-bases",
        json={"knowledge_base_ids": [kb_allowed["id"]]},
    )
    assert bound["bound_ids"] == [kb_allowed["id"]], bound
    assert bound["restricted"] is True

    listing = call(
        "GET", f"/digital-employees/{employee['id']}/knowledge-bases"
    )
    assert listing["bound_ids"] == [kb_allowed["id"]], listing
    bound_items = {
        item["id"]: item["bound"] for item in listing["items"]
    }
    assert bound_items[kb_allowed["id"]] is True
    assert bound_items[kb_denied["id"]] is False

    allowed_task = create_knowledge_task(
        employee["id"], f"kb_ok_task_{SUFFIX}", kb_allowed["id"]
    )
    allowed_result = wait_instance(allowed_task["id"])
    assert allowed_result["status"] == "succeeded", allowed_result

    denied_task = create_knowledge_task(
        employee["id"], f"kb_no_task_{SUFFIX}", kb_denied["id"]
    )
    denied_result = wait_instance(denied_task["id"])
    assert denied_result["status"] == "failed", denied_result
    assert "不在员工已绑定范围内" in (denied_result.get("error") or ""), denied_result

    cleared = call(
        "PUT",
        f"/digital-employees/{employee['id']}/knowledge-bases",
        json={"knowledge_base_ids": []},
    )
    assert cleared["bound_ids"] == []
    assert cleared["restricted"] is False

    print("\n知识库绑定冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
