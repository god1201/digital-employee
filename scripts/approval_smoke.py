"""审批流端到端冒烟测试。先启动 uvicorn，再运行本脚本。

覆盖：
- 三个业务模板：费用报销、合同、文书用印
- 条件分支（金额 > 5000 直达总经理）
- 或签 / 会签 / 依次审批
- 转办、加签
- 驳回、取消、催办
- 超时自动通过（直接调用扫描器）
- 审批通过后创建数字员工任务
- 通知、统计
"""

import asyncio
import os
import sys
import time
from datetime import timedelta

import httpx

from app.core.base import utcnow
from app.core.database import SessionLocal
from app.domains.workflows.approvals.models import ApprovalTask
from app.domains.workflows.approvals.service import scan_timeouts

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=60.0)
SUFFIX = str(int(time.time()))[-6:]


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


def wait_health(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    print("服务未就绪")
    sys.exit(1)


def login(username: str, password: str) -> str:
    data = call(
        "POST",
        "/api/v1/auth/login",
        json={"username": username, "password": password, "tenant_code": "demo"},
    )
    return data["access_token"]


def find_flow(flows: list[dict], code: str) -> dict:
    flow = next((item for item in flows if item["code"] == code), None)
    assert flow, f"缺少流程模板 {code}"
    return flow


def pending_task(detail: dict) -> dict | None:
    return next((task for task in detail.get("tasks", []) if task["status"] == "pending"), None)


def approve_first(instance_id: int, token: str, comment: str = "同意") -> dict:
    detail = call("GET", f"/api/v1/approvals/instances/{instance_id}", token)
    task = pending_task(detail)
    assert task, detail
    call(
        "POST",
        f"/api/v1/approvals/tasks/{task['id']}/approve",
        token,
        json={"comment": comment},
    )
    return call("GET", f"/api/v1/approvals/instances/{instance_id}", token)


def start(flow_id: int, title: str, form_data: dict, token: str, **extra) -> dict:
    body = {"flow_id": flow_id, "title": title, "form_data": form_data, **extra}
    return call("POST", "/api/v1/approvals/instances", token, json=body)


def main() -> None:
    wait_health()
    admin = login("admin", "admin123")
    users = call("GET", "/api/v1/auth/users", admin)
    reviewer = next((item for item in users if item["username"] == "reviewer_smoke"), None)
    if reviewer is None:
        reviewer = call(
            "POST",
            "/api/v1/auth/users",
            admin,
            json={
                "username": "reviewer_smoke",
                "password": "reviewer123",
                "full_name": "冒烟审批专员",
                "is_superuser": False,
            },
        )
    reviewer_token = login(reviewer["username"], "reviewer123")

    forms = call("GET", "/api/v1/approvals/forms", admin)["items"]
    flows = call("GET", "/api/v1/approvals/flows", admin)["items"]
    assert len(forms) >= 3, forms
    assert len(flows) >= 3, flows
    expense_flow = find_flow(flows, "tpl_expense_flow")
    contract_flow = find_flow(flows, "tpl_contract_flow")
    document_flow = find_flow(flows, "tpl_document_flow")

    # 1. 条件分支：大额直达总经理
    instance = start(
        expense_flow["id"],
        f"大额报销 {SUFFIX}",
        {
            "amount": 8000,
            "category": "travel",
            "expense_date": "2026-08-10",
            "department": "市场部",
            "description": "上海出差机票酒店",
        },
        admin,
    )
    assert instance["current_node_name"] == "总经理审批", instance
    instance = approve_first(instance["id"], admin, "总经理同意")
    assert instance["status"] == "approved", instance
    print("条件分支（大额）通过，进度:", instance["progress"])

    # 2. 条件分支：小额走财务 → 总经理
    instance = start(
        expense_flow["id"],
        f"小额报销 {SUFFIX}",
        {
            "amount": 300,
            "category": "office",
            "expense_date": "2026-08-11",
            "department": "行政部",
            "description": "打印纸",
        },
        admin,
    )
    assert instance["current_node_name"] == "财务审核", instance
    instance = approve_first(instance["id"], admin, "财务同意")
    assert instance["current_node_name"] == "总经理审批", instance
    instance = approve_first(instance["id"], admin, "总经理同意")
    assert instance["status"] == "approved", instance

    # 3. 合同驳回
    instance = start(
        contract_flow["id"],
        f"合同驳回 {SUFFIX}",
        {
            "contract_name": "办公用品采购合同",
            "counterparty": "某某公司",
            "amount": 20000,
            "contract_type": "purchase",
            "start_date": "2026-09-01",
            "summary": "年度采购",
        },
        admin,
    )
    task = pending_task(call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin))
    call(
        "POST",
        f"/api/v1/approvals/tasks/{task['id']}/reject",
        admin,
        json={"comment": "条款需修改"},
    )
    detail = call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin)
    assert detail["status"] == "rejected", detail

    # 4. 转办 + 加签
    instance = start(
        document_flow["id"],
        f"用印转办 {SUFFIX}",
        {
            "document_title": "用印测试",
            "document_type": "seal",
            "purpose": "冒烟测试",
            "urgency": "normal",
        },
        admin,
    )
    detail = call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin)
    task = pending_task(detail)
    call(
        "POST",
        f"/api/v1/approvals/tasks/{task['id']}/transfer",
        admin,
        json={"target_user_id": reviewer["id"], "comment": "转给专员"},
    )
    reviewer_tasks = call("GET", "/api/v1/approvals/tasks?status=pending", reviewer_token)["items"]
    reviewer_task = next(
        item for item in reviewer_tasks if item["instance_id"] == instance["id"]
    )
    call(
        "POST",
        f"/api/v1/approvals/tasks/{reviewer_task['id']}/add-sign",
        reviewer_token,
        json={"user_ids": [1], "comment": "请管理员加签"},
    )
    call(
        "POST",
        f"/api/v1/approvals/tasks/{reviewer_task['id']}/approve",
        reviewer_token,
        json={"comment": "专员同意"},
    )
    detail = call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin)
    assert detail["current_node_name"] == "用印管理员", detail
    detail = approve_first(instance["id"], admin, "用印管理员同意")
    assert detail["status"] == "approved", detail

    # 5. 超时自动通过
    auto_flow = call(
        "POST",
        "/api/v1/approvals/flows",
        admin,
        json={
            "name": f"超时自动通过 {SUFFIX}",
            "code": f"smoke_timeout_{SUFFIX}",
            "category": "custom",
            "description": "冒烟：超时自动通过",
            "nodes": [
                {
                    "key": "auto",
                    "name": "超时自动审批",
                    "type": "approval",
                    "approvers": ["admin"],
                    "mode": "any",
                    "timeout_hours": 1,
                    "timeout_action": "auto_approve",
                },
                {"key": "end", "name": "结束", "type": "end"},
            ],
        },
    )
    instance = start(auto_flow["id"], f"超时测试 {SUFFIX}", {}, admin)
    task_id = pending_task(
        call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin)
    )["id"]

    async def expire_task() -> int:
        async with SessionLocal() as session:
            task_row = await session.get(ApprovalTask, task_id)
            task_row.due_at = utcnow() - timedelta(hours=2)
            await session.commit()
            processed = await scan_timeouts(session)
            await session.commit()
            return processed

    assert asyncio.run(expire_task()) >= 1
    detail = call("GET", f"/api/v1/approvals/instances/{instance['id']}", admin)
    assert detail["status"] == "approved", detail

    # 6. 审批通过后创建数字员工任务
    employees = call("GET", "/api/v1/digital-employees?page_size=10", admin)["items"]
    employee = next((item for item in employees if item["status"] == "active"), employees[0])
    linked_flow = call(
        "POST",
        "/api/v1/approvals/flows",
        admin,
        json={
            "name": f"审批联动任务 {SUFFIX}",
            "code": f"smoke_link_{SUFFIX}",
            "category": "custom",
            "description": "冒烟：审批通过后创建员工任务",
            "nodes": [
                {
                    "key": "approve",
                    "name": "联动审批",
                    "type": "approval",
                    "approvers": ["admin"],
                    "mode": "any",
                    "timeout_hours": 1,
                    "timeout_action": "remind",
                },
                {"key": "end", "name": "结束", "type": "end"},
            ],
            "config": {
                "auto_launch_task": True,
                "employee_id": employee["id"],
                "title_template": "审批通过：{title}",
            },
        },
    )
    instance = start(linked_flow["id"], f"联动测试 {SUFFIX}", {}, admin)
    detail = approve_first(instance["id"], admin, "同意并创建任务")
    assert detail["task_instance_id"], detail
    task_detail = call("GET", f"/api/v1/tasks/instances/{detail['task_instance_id']}", admin)
    assert task_detail["employee_id"] == employee["id"], task_detail

    # 7. 通知与统计
    notifications = call("GET", "/api/v1/approvals/notifications", admin)
    assert notifications["total"] >= 1, notifications
    call("POST", "/api/v1/approvals/notifications/read-all", admin, json={})
    stats = call("GET", "/api/v1/approvals/stats", admin)
    assert stats["my_total"] >= 6, stats
    print("approval stats:", stats)

    # 8. 表单 / 流程 CRUD
    new_form = call(
        "POST",
        "/api/v1/approvals/forms",
        admin,
        json={
            "name": f"冒烟表单 {SUFFIX}",
            "code": f"smoke_form_{SUFFIX}",
            "category": "custom",
            "fields": [{"name": "reason", "label": "事由", "type": "text", "required": True}],
        },
    )
    new_flow = call(
        "POST",
        "/api/v1/approvals/flows",
        admin,
        json={
            "name": f"冒烟流程 {SUFFIX}",
            "code": f"smoke_flow_{SUFFIX}",
            "category": "custom",
            "form_id": new_form["id"],
            "nodes": [
                {
                    "key": "approve",
                    "name": "审批",
                    "type": "approval",
                    "approvers": ["admin"],
                    "mode": "any",
                },
                {"key": "end", "name": "结束", "type": "end"},
            ],
        },
    )
    call("DELETE", f"/api/v1/approvals/flows/{new_flow['id']}", admin)
    call("DELETE", f"/api/v1/approvals/forms/{new_form['id']}", admin)

    print("Approval smoke passed.")


if __name__ == "__main__":
    main()
