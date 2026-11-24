"""团队模板 → 自定义团队 → 确认启用 冒烟测试。"""

import os
import sys
import time

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=60.0)


def call(method: str, path: str, token: str | None = None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
    payload = response.json()
    print(f"{method} {path} -> {response.status_code}")
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(payload)
        sys.exit(1)
    return payload.get("data")


def main() -> None:
    for _ in range(30):
        try:
            if client.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)

    login = call(
        "POST",
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    templates = call("GET", "/api/v1/team-templates", token)
    presets = call("GET", "/api/v1/role-presets", token)
    template_items = templates["items"]
    print("templates:", [(item["id"], item["name"], len(item["roles"])) for item in template_items])
    print("role presets:", len(presets["items"]))
    assert len(template_items) >= 5, templates
    assert len(presets["items"]) >= 10, presets

    template = template_items[0]
    team = call(
        "POST",
        "/api/v1/teams",
        token,
        json={
            "template_id": template["id"],
            "name": "AI 内容组",
            "description": "从 AI 团队模板创建",
            "auto_activate": False,
        },
    )
    print("team status:", team["status"], "members:", len(team["members"]))
    assert team["status"] == "pending_confirmation", team
    assert len(team["members"]) == len(template["roles"]), team

    activated = call("POST", f"/api/v1/teams/{team['id']}/activate", token, json={})
    print("activated:", activated["status"], [member["status"] for member in activated["members"]])
    assert activated["status"] == "active", activated
    assert all(member["status"] == "active" for member in activated["members"]), activated

    custom = call(
        "POST",
        "/api/v1/teams",
        token,
        json={
            "template_id": template["id"],
            "name": "自定义内容组",
            "description": "自定义成员",
            "auto_activate": True,
            "members": [
                {
                    "role_code": "content_planner",
                    "employee_name": "主策划",
                    "skills": ["script.plan", "custom.skill"],
                    "tools": ["DeepSeek", "知识库"],
                    "approval_threshold": "medium",
                    "sandbox": "none",
                }
            ],
        },
    )
    print("custom team:", custom["status"], len(custom["members"]))
    assert custom["status"] == "active", custom
    assert len(custom["members"]) == 1, custom
    assert custom["members"][0]["employee_name"] == "主策划", custom

    paused = call("POST", f"/api/v1/teams/{custom['id']}/pause", token, json={})
    print("paused:", paused["status"])
    assert paused["status"] == "paused", paused

    employees = call("GET", "/api/v1/digital-employees?page_size=200", token)
    team_employees = [item for item in employees["items"] if item["code"].startswith("tm_")]
    print("team employees:", len(team_employees))
    assert len(team_employees) >= 5, team_employees

    print("TEAM SMOKE PASSED")


if __name__ == "__main__":
    main()
