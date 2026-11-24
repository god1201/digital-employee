"""DeepSeek 端到端冒烟：内部 Agent 调用 + 自由任务规划执行。

前置条件：
- 服务已启动
- 已配置 DEEPSEEK_API_KEY 或 LLM_API_KEY
- 数据库已有管理员 admin / admin123 / demo（可用 smoke_test.py 初始化）
"""

import os
import sys
import time

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=180.0)


def call(method: str, path: str, token: str | None = None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
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


def main() -> None:
    login = call(
        "POST",
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    agent = call(
        "POST",
        "/api/v1/agents",
        token,
        json={
            "name": "DeepSeek 助手",
            "code": f"deepseek_helper_{int(time.time())}",
            "agent_type": "internal",
            "protocol": "builtin",
            "system_prompt": "你是简洁的中文助手，回答不超过 100 字。",
            "tools": [],
            "capabilities": ["问答"],
            "config": {"max_steps": 3},
        },
    )
    invoked = call(
        "POST",
        f"/api/v1/agents/{agent['id']}/invoke",
        token,
        json={"input": {"text": "用一句话介绍你自己"}, "prompt": "用一句话介绍你自己"},
    )
    print("agent tokens:", invoked["tokens"])
    print("agent output:", str(invoked["output"])[:300])
    assert invoked["output"].get("text"), invoked

    employees = call("GET", "/api/v1/digital-employees?page_size=10", token)["items"]
    if not employees:
        print("没有数字员工，请先运行 smoke_test.py")
        sys.exit(1)

    task = call(
        "POST",
        "/api/v1/tasks/instances",
        token,
        json={
            "employee_id": employees[0]["id"],
            "title": "DeepSeek 自由任务",
            "input": {"request": "用一句话总结数字员工平台的价值"},
        },
    )
    instance_id = task["id"]

    deadline = time.time() + 120
    detail: dict = {}
    while time.time() < deadline:
        detail = call("GET", f"/api/v1/tasks/instances/{instance_id}", token)
        if detail["status"] in {"succeeded", "failed", "waiting_human", "cancelled"}:
            break
        time.sleep(2)

    print("free task status:", detail.get("status"))
    print("free task error:", detail.get("error"))
    for step in detail.get("steps", []):
        print(
            " step",
            step["step_index"],
            step["step_type"],
            step["status"],
            "tokens=",
            step.get("tokens"),
            "error=",
            step.get("error"),
        )
        if step.get("output"):
            print("  output:", str(step["output"])[:300])
    print("plan:", str(detail.get("plan"))[:500])

    if detail.get("status") == "waiting_human":
        call(
            "POST",
            f"/api/v1/tasks/instances/{instance_id}/resume",
            token,
            json={"approved": True, "comment": "LLM smoke"},
        )
        time.sleep(3)
        detail = call("GET", f"/api/v1/tasks/instances/{instance_id}", token)
        print("after resume:", detail.get("status"))

    storyboard = call(
        "POST",
        "/api/v1/storyboards",
        token,
        json={
            "title": "DeepSeek 分镜测试",
            "genre": "短剧",
            "style": "写实电影感",
            "script": (
                "夜，咖啡馆。小林推门而入，看到阿杰坐在窗边。小林：你等了很久吗？阿杰：还好，坐吧。"
            ),
        },
    )
    generated = call("POST", f"/api/v1/storyboards/{storyboard['id']}/generate", token, json={})
    print(
        "storyboard:",
        generated["status"],
        generated["scene_count"],
        "scenes /",
        generated["shot_count"],
        "shots /",
        generated["tokens"],
        "tokens",
    )
    assert generated["status"] == "ready", generated
    assert generated["scene_count"] > 0 and generated["shot_count"] > 0, generated

    knowledge_bases = call("GET", "/api/v1/knowledge-bases?page_size=10", token)
    if knowledge_bases.get("items"):
        rag = call(
            "POST",
            f"/api/v1/knowledge-bases/{knowledge_bases['items'][0]['id']}/graph-search",
            token,
            json={
                "query": "退款政策",
                "top_k": 3,
                "max_hops": 1,
                "answer": True,
            },
        )
        print("graph-rag tokens:", rag.get("tokens"))
        print("graph-rag answer:", str(rag.get("answer"))[:300])
        assert rag.get("answer"), rag

    print("LLM SMOKE FINISHED")


if __name__ == "__main__":
    main()
