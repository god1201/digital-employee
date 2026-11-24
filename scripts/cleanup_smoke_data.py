"""清理演示租户里的冒烟测试数据。

策略（安全、可逆）：
- 保留一个演示数字员工（code=01）和一个通用 Agent（code=general_assistant）；
- 其余员工停用（status=disabled），前端默认只显示 active；
- 明显属于冒烟的 Agent 停用；
- 只由已停用员工组成的会话归档，避免会话页继续出现测试会话。

 smoke 脚本仍可运行；运行后建议再执行一次本脚本，或让前端默认隐藏 disabled。

运行：
    .venv\\Scripts\\python.exe scripts/cleanup_smoke_data.py
"""

import os
import sys

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
client = httpx.Client(timeout=60.0, trust_env=False)
token: str | None = None

KEEP_EMPLOYEE_CODES = {"01", "001"}
SMOKE_AGENT_PREFIXES = (
    "p2_",
    "p3_",
    "skill_",
    "tune_",
    "mm_",
    "mock_",
    "internal_agent_",
    "deepseek_helper_",
    "wb_agent_",
    "chat_agent_",
    "llm_",
    "train_",
)
GENERAL_AGENT_CODE = "general_assistant"


def call(method: str, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(f"{method} {path} -> {response.status_code}: {payload}")
        return None
    return payload.get("data")


def all_items(path: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        data = call("GET", f"{path}{'&' if '?' in path else '?'}page={page}&page_size=200")
        if not data:
            break
        items.extend(data.get("items", []))
        if len(items) >= data.get("total", 0) or not data.get("items"):
            break
        page += 1
    return items


def ensure_general_agent() -> dict:
    agents = all_items("/agents")
    existing = next(
        (agent for agent in agents if agent["code"] == GENERAL_AGENT_CODE), None
    )
    if existing:
        call("PATCH", f"/agents/{existing['id']}", json={"status": "active"})
        return {"id": existing["id"], "code": existing["code"], "name": existing["name"]}
    created = call(
        "POST",
        "/agents",
        json={
            "name": "通用助手",
            "code": GENERAL_AGENT_CODE,
            "agent_type": "internal",
            "protocol": "builtin",
            "model_provider": "openai",
            "model_name": "deepseek-chat",
            "system_prompt": (
                "你是通用数字员工，负责回答、总结、检索与执行平台工具。"
                "回答简洁，遵守岗位契约，不编造工具结果。"
            ),
            "tools": [],
            "capabilities": ["对话", "总结", "检索"],
            "config": {"max_steps": 6},
        },
    )
    if created is None:
        sys.exit(1)
    return created


def main() -> None:
    global token
    login = call(
        "POST",
        "/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    if login is None:
        print("登录失败")
        sys.exit(1)
    token = login["access_token"]

    general = ensure_general_agent()
    employees = all_items("/digital-employees")
    disabled = 0
    kept = []
    for employee in employees:
        if employee["code"] in KEEP_EMPLOYEE_CODES:
            kept.append(employee)
            continue
        if employee["status"] != "disabled":
            call(
                "PATCH",
                f"/digital-employees/{employee['id']}",
                json={"status": "disabled"},
            )
            disabled += 1

    # 只保留一个 active 演示员工；把通用 Agent 绑定给它
    demo = next(
        (employee for employee in kept if employee["code"] == "01"), None
    )
    if demo is not None:
        call(
            "PATCH",
            f"/digital-employees/{demo['id']}",
            json={
                "name": "通用数字员工",
                "position": "通用助理",
                "status": "active",
                "agent_id": general["id"],
            },
        )
        kept = [item for item in kept if item["id"] != demo["id"]]
        kept.append(
            {
                **demo,
                "name": "通用数字员工",
                "position": "通用助理",
                "agent_id": general["id"],
                "agent_name": general["name"],
                "status": "active",
            }
        )

    agents = all_items("/agents")
    disabled_agents = 0
    for agent in agents:
        if agent["id"] == general["id"]:
            continue
        if agent["code"].startswith(SMOKE_AGENT_PREFIXES) and agent["status"] != "disabled":
            call("DELETE", f"/agents/{agent['id']}")
            disabled_agents += 1

    disabled_ids = {
        employee["id"]
        for employee in all_items("/digital-employees")
        if employee["status"] == "disabled"
    }
    archived = 0
    conversations = call("GET", "/conversations?limit=200") or []
    for conversation in conversations:
        detail = call("GET", f"/conversations/{conversation['id']}")
        if not detail:
            continue
        member_ids = {item["employee_id"] for item in detail.get("members", [])}
        if member_ids and member_ids <= disabled_ids:
            call("POST", f"/conversations/{conversation['id']}/archive")
            archived += 1

    print(
        f"清理完成：停用员工 {disabled} 个，停用 Agent {disabled_agents} 个，"
        f"归档测试会话 {archived} 个；保留演示员工 {len(kept)} 个。"
    )
    for employee in kept:
        if employee.get("status") != "active":
            continue
        print(
            f"  - {employee['name']}（{employee['code']}）"
            f" Agent={employee.get('agent_name') or '未绑定'}"
        )


if __name__ == "__main__":
    main()
