"""技能市场与调教台版本谱系端到端冒烟测试。

先重启后端（确保加载最新代码并完成内置技能种子），再运行：

    .venv\\Scripts\\python.exe scripts\\skill_market_smoke.py

覆盖：
- 内置技能市场（每编码最新版本）
- 依赖自动解析（data.report → data.sql_query）
- 技能上下文注入内容
- 自定义技能 v1 → v2 升级
- 跨员工复制
- 冲突检测（409）
- 学习工件新版本与谱系
- 调教台时间线
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


def create_employee(tag: str) -> dict:
    return call(
        "POST",
        "/digital-employees",
        json={
            "name": f"技能冒烟 {tag} {SUFFIX}",
            "code": f"skill_smoke_{tag}_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {},
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

    packages = call("GET", "/skill-packages?page_size=200")
    codes = {item["code"] for item in packages["items"]}
    assert {"data.report", "audit.contract", "lang.reply_style"} <= codes, codes

    employee_a = create_employee("a")
    employee_b = create_employee("b")

    installed = call(
        "POST",
        f"/digital-employees/{employee_a['id']}/skills",
        json={"code": "data.report"},
    )
    installed_codes = {item["skill_code"] for item in installed["installed"]}
    assert installed_codes == {"data.report", "data.sql_query"}, installed_codes

    context = call("GET", f"/digital-employees/{employee_a['id']}/skills/context")
    assert "data.sql_query" in context["context"]
    assert context["count"] == 2

    recommendations = call(
        "GET",
        f"/digital-employees/{employee_a['id']}/skills/recommend?need=异常",
    )
    assert isinstance(recommendations, list)

    package_v1 = call(
        "POST",
        "/skill-packages",
        json={
            "code": f"custom.helper_{SUFFIX}",
            "name": "自定义助手",
            "category": "process",
            "description": "冒烟用自定义技能",
            "prompt_template": "只输出结构化结果",
            "tool_codes": ["custom_tool"],
            "permissions": {"read_only": False, "risk_level": "medium"},
        },
    )
    call("POST", f"/skill-packages/{package_v1['id']}/publish")
    call(
        "POST",
        f"/digital-employees/{employee_a['id']}/skills",
        json={"code": package_v1["code"]},
    )

    package_v2 = call(
        "POST",
        f"/skill-packages/{package_v1['code']}/versions",
        json={"description": "v2 增强", "prompt_template": "v2 只输出结构化结果"},
    )
    assert package_v2["version"] == 2
    call("POST", f"/skill-packages/{package_v2['id']}/publish")
    upgraded = call(
        "POST",
        f"/digital-employees/{employee_a['id']}/skills/{package_v1['code']}/upgrade",
    )
    assert upgraded["skill"]["version"] == 2, upgraded

    copied = call(
        "POST",
        f"/digital-employees/{employee_b['id']}/skills/copy",
        json={"source_employee_id": employee_a["id"], "skill_code": "data.report"},
    )
    assert {item["skill_code"] for item in copied["installed"]} == {
        "data.report",
        "data.sql_query",
    }

    conflict_a = call(
        "POST",
        "/skill-packages",
        json={
            "code": f"conflict.a_{SUFFIX}",
            "name": "冲突 A",
            "category": "process",
            "conflicts_with": [f"conflict.b_{SUFFIX}"],
        },
    )
    conflict_b = call(
        "POST",
        "/skill-packages",
        json={
            "code": f"conflict.b_{SUFFIX}",
            "name": "冲突 B",
            "category": "process",
            "conflicts_with": [f"conflict.a_{SUFFIX}"],
        },
    )
    call("POST", f"/skill-packages/{conflict_a['id']}/publish")
    call("POST", f"/skill-packages/{conflict_b['id']}/publish")
    call(
        "POST",
        f"/digital-employees/{employee_b['id']}/skills",
        json={"code": conflict_a["code"]},
    )
    blocked = raw(
        "POST",
        f"/digital-employees/{employee_b['id']}/skills",
        json={"code": conflict_b["code"]},
    )
    assert blocked.status_code == 409, blocked.text

    artifact = call(
        "POST",
        "/learning-artifacts",
        json={
            "employee_id": employee_a["id"],
            "attribution": "风格不符",
            "target_layer": "persona_layer",
            "proposal": {
                "action": "update_style_card",
                "content": "结论先行",
            },
            "evidence": ["人工改写"],
        },
    )
    new_version = call(
        "POST",
        f"/learning-artifacts/{artifact['id']}/new-version",
        json={"proposal": {"action": "update_style_card", "content": "结论先行；表格≤5列"}},
    )
    assert new_version["version"] == artifact["version"] + 1
    lineage = call("GET", f"/learning-artifacts/{new_version['id']}/lineage")
    assert [item["version"] for item in lineage] == [1, 2], lineage

    timeline = call("GET", f"/timeline?employee_id={employee_a['id']}&limit=50")
    assert any(item["type"] == "artifact" for item in timeline), timeline

    print("\n技能市场与调教台冒烟全部通过（OK）")


if __name__ == "__main__":
    main()
