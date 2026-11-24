"""失败反思与自我修正端到端冒烟。

覆盖：
- 固定任务工具失败后生成 reflection 步骤
- 反思结果写入任务 output，可在回放中查看
- 同一任务只保留一条失败归因（反思/重试不重复归因）
- 固定任务不会自动重试（避免重复不可逆工具动作）

运行前确保后端已重启：

    .venv\\Scripts\\python.exe scripts\\reflection_smoke.py
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
            "name": f"反思冒烟 {SUFFIX}",
            "code": f"reflect_smoke_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {},
        },
    )
    tool = call(
        "POST",
        "/tools",
        json={
            "name": "反思必败工具",
            "code": f"reflect_fail_{SUFFIX}",
            "tool_type": "python",
            "description": "制造工具失败",
            "parameters_schema": {},
            "config": {
                "code": "def run(args):\n    raise RuntimeError('reflection boom')\n"
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
            "name": "反思冒烟任务",
            "code": f"reflect_task_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "执行必败工具",
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
        json={
            "employee_id": employee["id"],
            "definition_id": definition["id"],
            "input": {},
        },
    )
    finished = wait_instance(instance["id"])
    assert finished["status"] == "failed", finished

    reflection = (finished.get("output") or {}).get("reflection") or {}
    assert reflection, finished
    assert reflection.get("category") == "tool_misuse", reflection
    assert reflection.get("auto_retry") is False, reflection
    assert reflection.get("hint"), reflection

    replay = call("GET", f"/tasks/instances/{instance['id']}/replay")
    frames = [
        frame
        for frame in replay["frames"]
        if frame["step_type"] == "reflection"
    ]
    assert frames, replay
    assert frames[0]["output"]["category"] == "tool_misuse", frames[0]

    attributions = call(
        "GET", f"/attributions?instance_id={instance['id']}&page_size=20"
    )
    assert attributions["total"] == 1, attributions
    assert attributions["items"][0]["category"] == "tool_misuse"

    print("\n失败反思冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
