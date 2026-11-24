"""员工工作台 / Agent 绑定 / 直接对话 / 群聊 / Token 明细冒烟。

前置：后端已重启，LLM_API_KEY 可用。

运行：
    .venv\\Scripts\\python.exe scripts\\workbench_chat_smoke.py
"""

import os
import sys
import uuid

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


def create_agent(code: str) -> dict:
    return call(
        "POST",
        "/agents",
        json={
            "name": f"工作台冒烟 Agent {code}",
            "code": code,
            "agent_type": "internal",
            "protocol": "builtin",
            "model_provider": "openai",
            "model_name": "deepseek-chat",
            "system_prompt": "你是数字员工实验助手，回答简洁，不编造工具结果。",
            "tools": [],
            "capabilities": ["对话", "总结"],
            "config": {"max_steps": 3},
        },
    )


def create_employee(name: str, code: str, agent_id: int) -> dict:
    return call(
        "POST",
        "/digital-employees",
        json={
            "name": name,
            "code": code,
            "position": "实验助手",
            "status": "active",
            "agent_id": agent_id,
            "model_provider": "openai",
            "model_name": "",
            "system_prompt": "你负责回答管理员的实验问题。",
            "config": {},
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

    agent = create_agent(f"wb_agent_{SUFFIX}")
    employee_a = create_employee("工作台冒烟 A", f"wb_a_{SUFFIX}", agent["id"])
    employee_b = create_employee("工作台冒烟 B", f"wb_b_{SUFFIX}", agent["id"])
    assert employee_a["agent_name"] == agent["name"]
    assert employee_a["model_name"] == "deepseek-chat", employee_a

    workbench = call(
        "GET", f"/digital-employees/{employee_a['id']}/workbench"
    )
    assert workbench["agent"]["id"] == agent["id"], workbench
    assert workbench["status"] == "idle", workbench
    assert "token_summary" in workbench, workbench

    project = call(
        "POST",
        "/projects",
        json={
            "name": f"工作台冒烟项目 {SUFFIX}",
            "code": f"wb_project_{SUFFIX}",
            "description": "验证项目成员、Token 与工作台",
            "owner_employee_id": employee_a["id"],
            "token_budget": 100000,
        },
    )
    call(
        "POST",
        f"/projects/{project['id']}/members",
        json={"employee_id": employee_b["id"], "role": "member"},
    )
    projects = call(
        "GET", f"/digital-employees/{employee_a['id']}/projects"
    )
    assert any(item["id"] == project["id"] for item in projects), projects

    direct = call(
        "POST",
        "/conversations",
        json={
            "mode": "direct",
            "employee_id": employee_a["id"],
            "project_id": project["id"],
        },
    )
    sent = call(
        "POST",
        f"/conversations/{direct['conversation']['id']}/messages",
        json={"content": "请用一句话介绍你自己，不要调用任何工具。"},
    )
    assert sent["replies"], sent
    assert sent["replies"][0]["tokens"] >= 0, sent

    group = call(
        "POST",
        "/conversations",
        json={
            "mode": "group",
            "employee_ids": [employee_a["id"], employee_b["id"]],
            "title": f"工作台冒烟群聊 {SUFFIX}",
            "project_id": project["id"],
        },
    )
    grouped = call(
        "POST",
        f"/conversations/{group['conversation']['id']}/messages",
        json={
            "content": "请各自用一句话说明你能做什么。",
            "routing_mode": "all",
        },
    )
    assert len(grouped["replies"]) == 2, grouped

    tokens = call(
        "GET",
        f"/digital-employees/{employee_a['id']}/token-usage?days=7",
    )
    assert tokens["by_source"].get("chat", 0) > 0, tokens
    assert tokens["events"], tokens

    print(
        "\n工作台/对话冒烟通过："
        f"employee={employee_a['id']}，project={project['id']}，"
        f"chat_tokens={tokens['by_source'].get('chat', 0)}"
    )


if __name__ == "__main__":
    main()
