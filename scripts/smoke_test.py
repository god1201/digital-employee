"""End-to-end smoke test. Start uvicorn on 127.0.0.1:8000 first.

Covers:
- bootstrap admin / login
- digital employee + Python tool + fixed task
- human approval step + resume
- access rules (allow / deny), default deny
- HTTP tool execution
- MCP stdio server sync + MCP tool execution
- Agent registration + third-party Agent + multi-agent orchestration
- persistent queue worker + automatic retry
- knowledge base chunking/search + graph + GraphRAG + knowledge task step
- risk control rules and content check
- quality inspection rules, scoring and manual review
- monitoring overview / workers / queue
- alert rule evaluation + event acknowledgement
- OpenAPI import + one-click tool conversion
- audit logs
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE_URL, timeout=30.0)
SUFFIX = str(int(time.time()))[-6:]


def call(method: str, path: str, token: str | None = None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        print(f"{method} {path} -> {response.status_code} non-JSON response")
        sys.exit(1)
    print(f"{method} {path} -> {response.status_code} code={payload.get('code')}")
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(payload)
        sys.exit(1)
    return payload.get("data")


def wait_status(
    instance_id: int,
    token: str,
    expected: set[str],
    timeout: float = 20.0,
    tolerate_retries: bool = False,
) -> dict:
    deadline = time.time() + timeout
    detail: dict = {}
    while time.time() < deadline:
        detail = call("GET", f"/api/v1/tasks/instances/{instance_id}", token)
        if detail["status"] in expected:
            if (
                tolerate_retries
                and detail["status"] == "failed"
                and detail.get("attempt", 0) < detail.get("max_attempts", 1)
            ):
                time.sleep(0.2)
                continue
            return detail
        time.sleep(0.2)
    print("timeout waiting for task status:", detail.get("status"))
    sys.exit(1)


def wait_mock_agent(url: str = "http://127.0.0.1:8020/invoke", timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = httpx.post(url, json={"ping": True}, timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"mock agent server not ready: {last_error}")


def run_fixed_task(
    token: str,
    employee_id: int,
    code: str,
    name: str,
    steps: list[dict],
    task_input: dict,
    *,
    max_attempts: int | None = None,
    tolerate_retries: bool = False,
) -> dict:
    definition = call(
        "POST",
        "/api/v1/tasks/definitions",
        token,
        json={
            "employee_id": employee_id,
            "name": name,
            "code": code,
            "task_type": "fixed",
            "steps": steps,
        },
    )
    payload = {
        "employee_id": employee_id,
        "definition_id": definition["id"],
        "input": task_input,
    }
    if max_attempts is not None:
        payload["max_attempts"] = max_attempts

    instance = call("POST", "/api/v1/tasks/instances", token, json=payload)
    return wait_status(
        instance["id"],
        token,
        {"succeeded", "failed", "waiting_human", "cancelled"},
        tolerate_retries=tolerate_retries,
    )


def main() -> None:
    health = client.get("/health")
    print("health:", health.json())
    if health.status_code != 200:
        sys.exit(1)

    register = client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": "演示租户",
            "tenant_code": "demo",
            "username": "admin",
            "password": "admin123",
            "full_name": "管理员",
        },
    )
    print("register:", register.status_code)

    login = call(
        "POST",
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    employee = call(
        "POST",
        "/api/v1/digital-employees",
        token,
        json={
            "name": "审核员",
            "code": f"reviewer_{SUFFIX}",
            "position": "内容审核",
            "description": "负责内容审核与结果确认",
            "status": "active",
        },
    )

    # 1. Python tool + human approval + resume
    python_tool_code = f"calc_amount_{SUFFIX}"
    call(
        "POST",
        "/api/v1/tools",
        token,
        json={
            "name": "计算金额",
            "code": python_tool_code,
            "tool_type": "python",
            "description": "计算两个数之和",
            "parameters_schema": {"type": "object"},
            "config": {"code": "def run(args):\n    return {'total': args['a'] + args['b']}"},
        },
    )

    rules = [
        {
            "employee_id": employee["id"],
            "path_pattern": "/user/**",
            "effect": "allow",
            "priority": 10,
            "method": "GET",
            "description": "allow user apis",
        },
        {
            "employee_id": employee["id"],
            "path_pattern": "/admin/**",
            "effect": "deny",
            "priority": 100,
            "method": "*",
            "description": "deny admin apis",
        },
        {
            "employee_id": employee["id"],
            "path_pattern": "/health",
            "effect": "allow",
            "priority": 50,
            "method": "GET",
            "description": "allow health check",
        },
    ]
    for rule in rules:
        call("POST", "/api/v1/access-rules", token, json=rule)

    allowed = call(
        "POST",
        "/api/v1/access-rules/check",
        token,
        json={"employee_id": employee["id"], "method": "GET", "path": "/user/123"},
    )
    assert allowed["allowed"] is True, allowed
    denied = call(
        "POST",
        "/api/v1/access-rules/check",
        token,
        json={"employee_id": employee["id"], "method": "GET", "path": "/admin/users"},
    )
    assert denied["allowed"] is False, denied

    # 3. Automatic retry: first attempt times out, second succeeds
    flaky_code = f"flaky_tool_{SUFFIX}"
    counter_name = f"de_flaky_{SUFFIX}.txt"
    flaky_source = (
        "import os\n"
        "import tempfile\n\n"
        "def run(args):\n"
        f"    path = os.path.join(tempfile.gettempdir(), '{counter_name}')\n"
        "    count = int(open(path).read()) if os.path.exists(path) else 0\n"
        "    count += 1\n"
        "    with open(path, 'w') as fh:\n"
        "        fh.write(str(count))\n"
        "    if count == 1:\n"
        "        raise TimeoutError('timed out')\n"
        "    return {'attempts': count}\n"
    )
    call(
        "POST",
        "/api/v1/tools",
        token,
        json={
            "name": "不稳定工具",
            "code": flaky_code,
            "tool_type": "python",
            "description": "first call times out",
            "config": {"code": flaky_source},
        },
    )
    retry_result = run_fixed_task(
        token,
        employee["id"],
        f"retry_task_{SUFFIX}",
        "自动重试验证",
        [{"name": "调用不稳定工具", "type": "tool", "tool_code": flaky_code}],
        {},
        max_attempts=2,
        tolerate_retries=True,
    )
    print("retry task:", retry_result["status"], "attempts:", retry_result["attempt"])
    assert retry_result["status"] == "succeeded", retry_result
    assert retry_result["attempt"] == 2, retry_result
    succeeded_steps = [step for step in retry_result["steps"] if step["status"] == "succeeded"]
    assert succeeded_steps, retry_result
    assert succeeded_steps[-1]["output"]["result"]["attempts"] == 2, retry_result

    definition = call(
        "POST",
        "/api/v1/tasks/definitions",
        token,
        json={
            "employee_id": employee["id"],
            "name": "计算并确认",
            "code": f"calc_confirm_{SUFFIX}",
            "task_type": "fixed",
            "steps": [
                {
                    "name": "计算",
                    "type": "tool",
                    "tool_code": python_tool_code,
                    "arguments": {"a": "{{input.a}}", "b": "{{input.b}}"},
                },
                {"name": "人工确认", "type": "human", "description": "确认计算结果"},
            ],
        },
    )
    instance = call(
        "POST",
        "/api/v1/tasks/instances",
        token,
        json={
            "employee_id": employee["id"],
            "definition_id": definition["id"],
            "input": {"a": 3, "b": 4},
        },
    )
    waiting = wait_status(instance["id"], token, {"waiting_human", "failed"})
    print(
        "waiting state:",
        waiting["status"],
        [(step["step_index"], step["status"]) for step in waiting["steps"]],
    )
    assert waiting["status"] == "waiting_human", waiting
    assert waiting["steps"][0]["status"] == "succeeded", waiting
    assert waiting["steps"][0]["output"]["result"]["total"] == 7, waiting

    call(
        "POST",
        f"/api/v1/tasks/instances/{instance['id']}/resume",
        token,
        json={"approved": True, "comment": "ok"},
    )
    finished = wait_status(instance["id"], token, {"succeeded", "failed", "cancelled"})
    print("final state:", finished["status"], finished.get("output", {}).get("summary"))
    assert finished["status"] == "succeeded", finished

    # 2. HTTP tool execution against this server
    http_tool_code = f"health_check_{SUFFIX}"
    call(
        "POST",
        "/api/v1/tools",
        token,
        json={
            "name": "健康检查",
            "code": http_tool_code,
            "tool_type": "http",
            "description": "GET /health",
            "parameters_schema": {"type": "object"},
            "config": {
                "system_code": "self",
                "method": "GET",
                "url": f"{BASE_URL}/health",
            },
        },
    )
    http_result = run_fixed_task(
        token,
        employee["id"],
        f"http_check_{SUFFIX}",
        "HTTP 健康检查",
        [{"name": "调用健康检查", "type": "tool", "tool_code": http_tool_code}],
        {},
    )
    print("http task:", http_result["status"])
    assert http_result["status"] == "succeeded", http_result
    assert http_result["steps"][0]["output"]["status_code"] == 200, http_result

    # 3. Default deny: /admin/** must fail
    denied_tool_code = f"admin_secret_{SUFFIX}"
    call(
        "POST",
        "/api/v1/tools",
        token,
        json={
            "name": "管理接口",
            "code": denied_tool_code,
            "tool_type": "http",
            "description": "should be denied",
            "config": {
                "system_code": "self",
                "method": "GET",
                "url": f"{BASE_URL}/admin/secret",
            },
        },
    )
    denied_result = run_fixed_task(
        token,
        employee["id"],
        f"deny_check_{SUFFIX}",
        "默认拒绝验证",
        [{"name": "访问管理接口", "type": "tool", "tool_code": denied_tool_code}],
        {},
    )
    print("deny task:", denied_result["status"], denied_result.get("error"))
    assert denied_result["status"] == "failed", denied_result
    assert "拒绝" in (denied_result.get("error") or ""), denied_result

    # 4. OpenAPI import + one-click tool conversion
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/user/{id}": {
                "get": {
                    "summary": "查询用户",
                    "operationId": "getUser",
                    "tags": ["crm"],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"type": "object"}}}}
                    },
                }
            }
        },
    }
    imported = call(
        "POST",
        "/api/v1/api-registries/import-openapi",
        token,
        json={"system_name": "CRM", "system_code": "crm", "spec": spec},
    )
    print("openapi import:", imported)
    api_list = call("GET", "/api/v1/api-registries?system_code=crm", token)
    api_id = api_list["items"][0]["id"]
    converted = call("POST", f"/api/v1/api-registries/{api_id}/to-tool", token)
    assert converted.get("tool_id"), converted

    # 5. MCP stdio server: register -> sync -> execute
    demo_script = str(Path(__file__).resolve().parent / "demo_mcp_server.py")
    mcp_server = call(
        "POST",
        "/api/v1/mcp-servers",
        token,
        json={
            "name": "Demo MCP",
            "code": f"demo_{SUFFIX}",
            "transport": "stdio",
            "command": sys.executable,
            "args": [demo_script],
            "description": "local demo mcp server",
        },
    )
    synced = call("POST", f"/api/v1/mcp-servers/{mcp_server['id']}/sync", token)
    print("mcp sync:", {key: synced[key] for key in ("tool_count", "created", "updated")})
    assert synced["tool_count"] >= 2, synced

    mcp_tools = call("GET", f"/api/v1/mcp-servers/{mcp_server['id']}/tools", token)
    add_tool = next(item for item in mcp_tools["items"] if item["config"].get("mcp_tool") == "add")
    mcp_result = run_fixed_task(
        token,
        employee["id"],
        f"mcp_task_{SUFFIX}",
        "MCP 计算",
        [
            {
                "name": "MCP add",
                "type": "tool",
                "tool_code": add_tool["code"],
                "arguments": {"a": 2, "b": 5},
            }
        ],
        {},
    )
    print("mcp task:", mcp_result["status"], mcp_result.get("error"))
    assert mcp_result["status"] == "succeeded", mcp_result
    mcp_output = mcp_result["steps"][0]["output"]
    print("mcp output:", mcp_output)
    assert "7" in str(mcp_output), mcp_output

    # 6. Agent registration + third-party Agent + multi-agent orchestration
    mock_script = str(Path(__file__).resolve().parent / "mock_agent_server.py")
    mock_process = subprocess.Popen(
        [sys.executable, mock_script, "8020"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_mock_agent()
        http_agent = call(
            "POST",
            "/api/v1/agents",
            token,
            json={
                "name": "Mock HTTP Agent",
                "code": f"mock_agent_{SUFFIX}",
                "agent_type": "third_party",
                "protocol": "http",
                "endpoint_url": "http://127.0.0.1:8020/invoke",
                "description": "echo agent",
                "capabilities": ["echo"],
            },
        )
        second_agent = call(
            "POST",
            "/api/v1/agents",
            token,
            json={
                "name": "Mock HTTP Agent 2",
                "code": f"mock_agent2_{SUFFIX}",
                "agent_type": "third_party",
                "protocol": "http",
                "endpoint_url": "http://127.0.0.1:8020/invoke",
                "description": "echo agent 2",
            },
        )

        invoked = call(
            "POST",
            f"/api/v1/agents/{http_agent['id']}/invoke",
            token,
            json={"input": {"text": "hello"}},
        )
        print("agent invoke:", invoked["output"])
        assert invoked["output"]["received"]["input"]["text"] == "hello", invoked

        internal_agent = call(
            "POST",
            "/api/v1/agents",
            token,
            json={
                "name": "内置审核 Agent",
                "code": f"internal_agent_{SUFFIX}",
                "agent_type": "internal",
                "protocol": "builtin",
                "system_prompt": "你是审核助手。",
                "tools": [python_tool_code],
                "capabilities": ["审核", "计算"],
            },
        )
        assert internal_agent["version"] == 1, internal_agent

        multi = run_fixed_task(
            token,
            employee["id"],
            f"agent_task_{SUFFIX}",
            "多 Agent 编排",
            [
                {
                    "name": "调用 Agent 1",
                    "type": "agent",
                    "agent_code": http_agent["code"],
                    "arguments": {"text": "hello"},
                },
                {
                    "name": "调用 Agent 2",
                    "type": "agent",
                    "agent_code": second_agent["code"],
                    "arguments": {"previous": "{{last.received.input.text}}"},
                },
            ],
            {},
        )
        print("multi-agent task:", multi["status"], multi.get("error"))
        assert multi["status"] == "succeeded", multi
        assert multi["steps"][1]["output"]["received"]["input"]["previous"] == "hello", multi
    finally:
        mock_process.terminate()
        try:
            mock_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_process.kill()

    # 6.5 Knowledge base + graph + knowledge step
    knowledge_base = call(
        "POST",
        "/api/v1/knowledge-bases",
        token,
        json={
            "name": "产品知识库",
            "code": f"kb_{SUFFIX}",
            "domain": "custom",
            "description": "产品与售后知识",
        },
    )
    document = call(
        "POST",
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        token,
        json={
            "title": "退款政策",
            "content": (
                "退款政策：订单签收后 7 天内可以申请无理由退款。"
                "超过 7 天需要人工审核，审核通过后 3 个工作日内到账。"
            ),
            "source": "manual",
        },
    )
    assert document["chunk_count"] >= 1, document

    reindexed = call(
        "POST",
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/reindex",
        token,
        json={},
    )
    print("knowledge reindex:", reindexed)
    assert reindexed["chunks"] >= 1, reindexed
    assert reindexed["model"], reindexed

    search_result = call(
        "POST",
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
        token,
        json={"query": "退款 7 天", "top_k": 3, "mode": "vector"},
    )
    print("knowledge search:", len(search_result["results"]))
    assert search_result["results"], search_result
    assert search_result["results"][0]["vector_score"] > 0, search_result

    triples = call(
        "POST",
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/import-triples",
        token,
        json={
            "triples": [
                {
                    "source": "退款政策",
                    "source_type": "policy",
                    "relation": "属于",
                    "target": "售后服务",
                    "target_type": "category",
                }
            ]
        },
    )
    assert triples["created_entities"] == 2, triples
    graph = call("GET", f"/api/v1/knowledge-bases/{knowledge_base['id']}/graph", token)
    assert graph["nodes"] and graph["edges"], graph

    graph_rag_result = call(
        "POST",
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/graph-search",
        token,
        json={
            "query": "退款政策",
            "top_k": 3,
            "max_hops": 1,
            "answer": False,
        },
    )
    print(
        "graph-rag:",
        len(graph_rag_result["entities"]),
        "entities /",
        len(graph_rag_result["relations"]),
        "relations /",
        len(graph_rag_result["chunks"]),
        "chunks",
    )
    assert graph_rag_result["entities"], graph_rag_result
    assert graph_rag_result["relations"], graph_rag_result
    assert graph_rag_result["chunks"], graph_rag_result
    assert graph_rag_result["context"], graph_rag_result

    rag_task = run_fixed_task(
        token,
        employee["id"],
        f"graph_rag_task_{SUFFIX}",
        "GraphRAG 任务",
        [
            {
                "name": "图谱问答",
                "type": "graph_rag",
                "knowledge_base_id": knowledge_base["id"],
                "query": "退款政策",
                "max_hops": 1,
                "answer": False,
            }
        ],
        {},
    )
    assert rag_task["status"] == "succeeded", rag_task
    assert rag_task["steps"][0]["output"]["entities"], rag_task

    kb_task = run_fixed_task(
        token,
        employee["id"],
        f"kb_task_{SUFFIX}",
        "知识检索任务",
        [
            {
                "name": "检索退款政策",
                "type": "knowledge",
                "knowledge_base_id": knowledge_base["id"],
                "query": "退款",
                "top_k": 3,
            }
        ],
        {},
    )
    assert kb_task["status"] == "succeeded", kb_task
    assert kb_task["steps"][0]["output"]["results"], kb_task

    # 6.6 Risk control
    call(
        "POST",
        "/api/v1/risk/rules",
        token,
        json={
            "name": "敏感词拦截",
            "category": "content",
            "keywords": ["赌博", "违禁"],
            "action": "block",
            "severity": "high",
        },
    )
    risk_check = call(
        "POST",
        "/api/v1/risk/check",
        token,
        json={"content": "这里有赌博相关内容", "category": "content"},
    )
    print("risk decision:", risk_check["decision"], risk_check["score"])
    assert risk_check["decision"] == "block", risk_check
    assert risk_check["score"] > 0, risk_check

    # 6.7 Quality inspection
    call(
        "POST",
        "/api/v1/qa/rules",
        token,
        json={
            "name": "违禁词质检",
            "code": f"qa_forbidden_{SUFFIX}",
            "category": "content",
            "rule_type": "keyword",
            "config": {"keywords": ["违禁", "赌博"]},
            "penalty": 40,
            "blocking": True,
            "enabled": True,
            "description": "命中即阻断",
        },
    )
    qa_check = call(
        "POST",
        "/api/v1/qa/checks",
        token,
        json={
            "title": "质检样例",
            "content": "这段内容包含违禁信息",
            "category": "content",
        },
    )
    print("qa:", qa_check["score"], qa_check["grade"], qa_check["decision"])
    assert qa_check["decision"] == "reject", qa_check
    assert qa_check["score"] < 100, qa_check
    qa_list = call("GET", "/api/v1/qa/checks?page_size=10", token)
    assert qa_list["total"] >= 1, qa_list
    reviewed = call(
        "POST",
        f"/api/v1/qa/checks/{qa_check['id']}/review",
        token,
        json={"decision": "pass", "comment": "人工复核通过"},
    )
    assert reviewed["status"] == "reviewed", reviewed
    assert reviewed["decision"] == "pass", reviewed

    # 6.8 Storyboard CRUD (generation is covered by llm_smoke.py)
    storyboard = call(
        "POST",
        "/api/v1/storyboards",
        token,
        json={
            "title": "冒烟分镜项目",
            "genre": "短剧",
            "style": "写实电影感",
            "script": "夜，咖啡馆。小林与阿杰见面，两人对视。",
        },
    )
    assert storyboard["status"] == "draft", storyboard
    storyboard_list = call("GET", "/api/v1/storyboards?page_size=10", token)
    assert storyboard_list["total"] >= 1, storyboard_list
    storyboard_detail = call("GET", f"/api/v1/storyboards/{storyboard['id']}", token)
    assert storyboard_detail["scenes"] == [], storyboard_detail
    call("DELETE", f"/api/v1/storyboards/{storyboard['id']}", token)

    # 7. Monitoring + alerts
    overview = call("GET", "/api/v1/monitoring/overview?days=1", token)
    print("overview totals:", overview["totals"])
    print("overview rates:", overview["rates"])
    assert overview["totals"]["succeeded"] >= 5, overview
    assert overview["rates"]["success_rate"] > 0, overview
    assert overview["by_employee"], overview
    assert overview["by_task_type"], overview
    assert len(overview["time_series"]) == 1, overview

    workers = call("GET", "/api/v1/monitoring/workers", token)
    print("workers active/total:", workers["active"], workers["total"])
    assert workers["active"] >= 1, workers

    queue = call("GET", "/api/v1/monitoring/queue", token)
    print("queue:", queue)
    assert "pending" in queue and "oldest_pending_age_seconds" in queue, queue

    rule = call(
        "POST",
        "/api/v1/alert-rules",
        token,
        json={
            "name": "失败率告警",
            "metric": "failure_rate",
            "operator": "gt",
            "threshold": 0.0,
            "window_minutes": 60,
            "cooldown_minutes": 0,
        },
    )
    evaluation = call("POST", f"/api/v1/alert-rules/{rule['id']}/evaluate", token)
    print("alert evaluation:", evaluation)
    assert evaluation["triggered"] is True, evaluation
    assert evaluation["event_id"] is not None, evaluation

    events = call("GET", "/api/v1/alert-events?status=open", token)
    assert events["total"] >= 1, events
    event_id = events["items"][0]["id"]
    acked = call("POST", f"/api/v1/alert-events/{event_id}/ack", token)
    assert acked["status"] == "acked", acked

    # 8. Audit logs
    logs = call("GET", "/api/v1/audit-logs?page=1&page_size=100", token)
    print("audit logs:", logs["total"])
    assert logs["total"] >= 20, logs

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
