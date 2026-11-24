"""关键学习接口的 PostgreSQL 集成测试。

默认跳过，避免单元测试依赖外部数据库。需要真实库时：

    set DE_INTEGRATION_TESTS=1
    .venv\\Scripts\\python.exe -m pytest tests/test_db_integration.py -q

测试在单个事务内创建临时租户/员工/任务，结束后 rollback，不污染开发库。
"""

import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.domains.models  # noqa: F401  注册全部模型，保证外键可解析
from app.core.base import utcnow

pytestmark = pytest.mark.skipif(
    os.getenv("DE_INTEGRATION_TESTS") != "1",
    reason="设置 DE_INTEGRATION_TESTS=1 才运行数据库集成测试",
)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """每个测试结束释放连接池，避免不同事件循环复用 asyncpg 连接。"""
    yield
    from app.core.database import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_trend_and_weekly_review_roundtrip() -> None:
    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.learning.models import FailureAttribution, WeeklyReview
    from app.domains.learning.scheduler import run_weekly_review_batch
    from app.domains.learning.trials import build_profile, build_trend
    from app.domains.workflows.tasks.models import TaskInstance, TaskStep
    from app.domains.workforce.employees.models import DigitalEmployee

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"集成测试 {suffix}", code=f"itest_{suffix}")
            db.add(tenant)
            await db.flush()

            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"集成员工 {suffix}",
                code=f"itest_emp_{suffix}",
                position="测试",
                status="active",
                model_provider="openai",
                model_name="gpt-4o-mini",
                system_prompt="你是测试员工。",
                config={"active_learning_budget": 3},
            )
            db.add(employee)
            await db.flush()

            now = utcnow()
            instance = TaskInstance(
                tenant_id=tenant.id,
                employee_id=employee.id,
                title=f"集成任务 {suffix}",
                task_type="fixed",
                status="failed",
                input={"hello": "world"},
                output={},
                plan=[{"name": "规划", "type": "llm"}],
                error="规划结果为空",
                trace_id=uuid.uuid4().hex,
                finished_at=now,
            )
            db.add(instance)
            await db.flush()
            db.add(
                TaskStep(
                    instance_id=instance.id,
                    step_index=0,
                    name="规划",
                    status="failed",
                    step_type="llm",
                    input={"prompt": "plan"},
                    output={},
                    error="规划结果为空",
                )
            )
            db.add(
                FailureAttribution(
                    tenant_id=tenant.id,
                    employee_id=employee.id,
                    instance_id=instance.id,
                    category="planning_error",
                    confidence=0.85,
                    signals=["集成测试"],
                    suggestion="补 SOP 节点",
                    routed_action="add_sop_step",
                    source="rule",
                    status="new",
                )
            )
            await db.flush()

            profile = await build_profile(db, employee)
            assert profile["total_tasks"] == 1
            assert profile["task_counts"]["failed"] == 1
            assert len(profile["capability_radar"]) >= 5
            assert all(
                0.0 <= float(item["value"]) <= 1.0
                for item in profile["capability_radar"]
            )

            trend = await build_trend(db, employee, days=7)
            assert len(trend["series"]) == 7
            assert trend["series"][-1]["total"] == 1
            assert trend["series"][-1]["failed"] == 1

            week_start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            result = await run_weekly_review_batch(
                db,
                tenant_id=tenant.id,
                week_start=week_start,
                force=True,
            )
            assert result["generated"] == 1
            review = await db.scalar(
                select(WeeklyReview).where(WeeklyReview.tenant_id == tenant.id)
            )
            assert review is not None
            assert review.metrics["total_tasks"] == 1
            assert review.employee_id == employee.id
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_chat_contract_ask_confirm_and_deny(monkeypatch) -> None:
    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.skills.agents.models import Agent
    from app.domains.skills.tools.models import Tool
    from app.domains.workforce.contracts.models import JobContract
    from app.domains.workforce.conversations import service as conv_service
    from app.domains.workforce.conversations.schemas import ConversationCreate
    from app.domains.workforce.conversations.service import (
        create_conversation,
        send_message,
    )
    from app.domains.workforce.employees.models import DigitalEmployee

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"对话集成 {suffix}", code=f"ichat_{suffix}")
            db.add(tenant)
            await db.flush()

            tool = Tool(
                tenant_id=tenant.id,
                name="危险工具",
                code=f"danger_{suffix}",
                tool_type="python",
                description="测试用工具",
                parameters_schema={},
                config={
                    "code": "def run(args):\n    return {'executed': True}\n"
                },
                risk_level="high",
                enabled=True,
                source="custom",
            )
            db.add(tool)
            await db.flush()

            async def make_employee(role: str):
                agent = Agent(
                    tenant_id=tenant.id,
                    name=f"对话 Agent {role}",
                    code=f"chat_agent_{role}_{suffix}",
                    agent_type="internal",
                    protocol="builtin",
                    model_name="fake-model",
                    system_prompt="你是测试员工。",
                    tools=[tool.code],
                    capabilities=[],
                    config={"max_steps": 3},
                    status="active",
                )
                db.add(agent)
                await db.flush()
                employee = DigitalEmployee(
                    tenant_id=tenant.id,
                    name=f"对话员工 {role}",
                    code=f"chat_emp_{role}_{suffix}",
                    position="测试",
                    agent_id=agent.id,
                    model_name="fake-model",
                    system_prompt="你是测试员工。",
                    config={},
                )
                db.add(employee)
                await db.flush()
                return employee

            async def fake_chat(*args, **kwargs):
                return responses.pop(0)

            # 1) must_ask -> pending -> 用户确认后执行
            employee = await make_employee("ask")
            db.add(
                JobContract(
                    tenant_id=tenant.id,
                    employee_id=employee.id,
                    role="测试",
                    can_do=[],
                    cannot_do=[],
                    must_ask=["危险工具"],
                    kpi={},
                    escalation_path=[],
                    autonomy_level="L3",
                    autonomy_overrides={},
                    red_lines={},
                    status="active",
                )
            )
            await db.flush()
            conversation, _members = await create_conversation(
                db,
                tenant.id,
                ConversationCreate(mode="direct", employee_id=employee.id),
            )
            monkeypatch.setattr(conv_service, "is_configured", lambda: True)
            monkeypatch.setattr(conv_service, "chat_with_tools", fake_chat)
            responses = [
                (
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": tool.code,
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    10,
                ),
                ({"content": "需要你确认后执行。"}, 5),
            ]
            first = await send_message(db, conversation, "执行危险工具")
            reply = first["replies"][0]
            assert reply["tool_calls"][0]["decision"] == "ask", reply
            assert reply["message_metadata"]["pending_tools"], reply

            responses = [({"content": "已执行。"}, 5)]
            second = await send_message(db, conversation, "确认")
            confirmed = second["replies"][0]
            assert confirmed["message_metadata"]["confirmed_tools"][0][
                "success"
            ] is True, confirmed

            # 2) read_only -> deny，不执行
            blocked = await make_employee("deny")
            db.add(
                JobContract(
                    tenant_id=tenant.id,
                    employee_id=blocked.id,
                    role="测试",
                    can_do=[],
                    cannot_do=[],
                    must_ask=[],
                    kpi={},
                    escalation_path=[],
                    autonomy_level="L3",
                    autonomy_overrides={},
                    red_lines={"read_only": True},
                    status="active",
                )
            )
            await db.flush()
            blocked_conversation, _ = await create_conversation(
                db,
                tenant.id,
                ConversationCreate(mode="direct", employee_id=blocked.id),
            )
            responses = [
                (
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-2",
                                "function": {
                                    "name": tool.code,
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    8,
                ),
                ({"content": "该操作被岗位契约拦截。"}, 4),
            ]
            denied = await send_message(
                db, blocked_conversation, "执行危险工具"
            )
            assert denied["replies"][0]["tool_calls"][0]["decision"] == "deny", (
                denied
            )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_job_template_auto_binds_knowledge_bases() -> None:
    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.knowledge.models import KnowledgeBase
    from app.domains.workforce.employees.models import DigitalEmployee
    from app.domains.workforce.templates.models import JobTemplate
    from app.domains.workforce.templates.schemas import ApplyTemplateRequest
    from app.domains.workforce.templates.service import apply_template

    suffix = uuid.uuid4().hex[:8]
    missing_id = 999999999
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"模板集成 {suffix}", code=f"itpl_{suffix}")
            db.add(tenant)
            await db.flush()
            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"模板员工 {suffix}",
                code=f"itpl_emp_{suffix}",
                status="active",
                system_prompt="你是测试员工。",
                config={},
            )
            knowledge_base = KnowledgeBase(
                tenant_id=tenant.id,
                name=f"测试知识库 {suffix}",
                code=f"itpl_kb_{suffix}",
                status="active",
            )
            db.add_all([employee, knowledge_base])
            await db.flush()
            template = JobTemplate(
                tenant_id=tenant.id,
                code=f"itpl_tpl_{suffix}",
                name=f"测试模板 {suffix}",
                skill_codes=[],
                tool_codes=[],
                knowledge_base_ids=[knowledge_base.id, missing_id],
                persona={},
                contract={},
                enabled=True,
                is_builtin=False,
            )
            db.add(template)
            await db.flush()

            result = await apply_template(
                db,
                tenant.id,
                employee,
                ApplyTemplateRequest(
                    template_code=template.code,
                    install_skills=False,
                    upsert_persona=False,
                    create_contract_draft=False,
                    bind_knowledge_bases=True,
                ),
            )
            assert result["knowledge_bases"]["bound"] == [knowledge_base.id]
            assert result["knowledge_bases"]["missing"] == [missing_id]
            assert result["knowledge_bases"]["names"] == [knowledge_base.name]
            assert employee.config["knowledge_base_ids"] == [knowledge_base.id]
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_agent_reverse_lookup_of_bound_employees() -> None:
    """Agent 列表带使用统计，且可按 Agent 反查绑定的数字员工。"""
    from types import SimpleNamespace

    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.skills.agents.models import Agent
    from app.domains.skills.agents.router import list_agent_employees, list_agents
    from app.domains.workforce.employees.models import DigitalEmployee

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"反查测试 {suffix}", code=f"iagent_{suffix}")
            db.add(tenant)
            await db.flush()

            agent = Agent(
                tenant_id=tenant.id,
                name=f"反查 Agent {suffix}",
                code=f"lookup_agent_{suffix}",
                agent_type="internal",
                protocol="builtin",
                model_name="fake-model",
                status="active",
            )
            idle_agent = Agent(
                tenant_id=tenant.id,
                name=f"空闲 Agent {suffix}",
                code=f"idle_agent_{suffix}",
                agent_type="internal",
                protocol="builtin",
                model_name="fake-model",
                status="active",
            )
            db.add_all([agent, idle_agent])
            await db.flush()

            active_employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"在岗员工 {suffix}",
                code=f"lookup_active_{suffix}",
                position="测试",
                status="active",
                agent_id=agent.id,
                config={},
            )
            disabled_employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"停用员工 {suffix}",
                code=f"lookup_disabled_{suffix}",
                position="测试",
                status="disabled",
                agent_id=agent.id,
                config={},
            )
            db.add_all([active_employee, disabled_employee])
            await db.flush()

            user = SimpleNamespace(id=1, tenant_id=tenant.id)

            listed = await list_agents(
                db=db,
                current_user=user,
                page=1,
                page_size=100,
                keyword=suffix,
                agent_type=None,
                protocol=None,
                status=None,
            )
            items = {item["id"]: item for item in listed["data"]["items"]}
            target = items[agent.id]
            assert target["employee_count"] == 2
            assert target["active_employee_count"] == 1
            assert set(target["employee_names"]) == {
                active_employee.name,
                disabled_employee.name,
            }
            assert items[idle_agent.id]["employee_count"] == 0

            reverse = await list_agent_employees(
                agent.id,
                db=db,
                current_user=user,
                page=1,
                page_size=50,
                status=None,
            )
            assert reverse["data"]["total"] == 2
            assert {item["id"] for item in reverse["data"]["items"]} == {
                active_employee.id,
                disabled_employee.id,
            }
            assert all(
                item["agent_name"] == agent.name for item in reverse["data"]["items"]
            )

            only_active = await list_agent_employees(
                agent.id,
                db=db,
                current_user=user,
                page=1,
                page_size=50,
                status="active",
            )
            assert only_active["data"]["total"] == 1
            assert only_active["data"]["items"][0]["id"] == active_employee.id
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_project_overview_stats_and_conversation_link() -> None:
    """项目列表聚合统计，以及任务/会话关联与反关联。"""
    from types import SimpleNamespace

    from app.core.database import SessionLocal
    from app.core.exceptions import NotFoundError
    from app.domains.identity.models import Tenant
    from app.domains.workflows.tasks.models import TaskInstance, TaskStep
    from app.domains.workforce.conversations.models import ChatMessage, Conversation
    from app.domains.workforce.employees.models import DigitalEmployee
    from app.domains.workforce.projects.router import list_projects_endpoint
    from app.domains.workforce.projects.schemas import ProjectCreate
    from app.domains.workforce.projects.service import (
        add_member,
        create_project,
        link_conversation,
        link_task,
        project_detail,
        unlink_conversation,
    )

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"项目测试 {suffix}", code=f"iproj_{suffix}")
            db.add(tenant)
            await db.flush()

            owner = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"项目负责人 {suffix}",
                code=f"proj_owner_{suffix}",
                position="负责人",
                status="active",
                config={},
            )
            member = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"项目成员 {suffix}",
                code=f"proj_member_{suffix}",
                position="执行",
                status="active",
                config={},
            )
            db.add_all([owner, member])
            await db.flush()

            project = await create_project(
                db,
                tenant.id,
                ProjectCreate(
                    name=f"项目 {suffix}",
                    code=f"proj_{suffix}",
                    description="项目看板集成测试",
                    owner_employee_id=owner.id,
                    token_budget=10000,
                ),
            )
            await add_member(db, project, member.id, role="member")

            task = TaskInstance(
                tenant_id=tenant.id,
                employee_id=member.id,
                title=f"项目任务 {suffix}",
                task_type="free",
                status="succeeded",
                input={},
                output={},
                plan=[],
            )
            db.add(task)
            await db.flush()
            db.add(
                TaskStep(
                    instance_id=task.id,
                    step_index=0,
                    name="对话",
                    status="succeeded",
                    step_type="llm",
                    input={},
                    output={},
                    tokens=120,
                    cost=0.0012,
                )
            )

            conversation = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"项目会话 {suffix}",
                status="active",
            )
            db.add(conversation)
            await db.flush()
            db.add(
                ChatMessage(
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    employee_id=member.id,
                    role="assistant",
                    content="完成",
                    tokens=30,
                    cost=0.0003,
                )
            )
            await db.flush()

            await link_task(db, project, task.id)
            await link_conversation(db, project, conversation.id)
            await db.flush()

            user = SimpleNamespace(id=1, tenant_id=tenant.id)
            listed = await list_projects_endpoint(
                db=db, current_user=user, status="active"
            )
            item = next(
                row for row in listed["data"] if row["id"] == project.id
            )
            assert item["owner_name"] == owner.name
            assert item["member_count"] == 2
            assert item["task_count"] == 1
            assert item["conversation_count"] == 1
            assert item["token_usage"]["tokens"] == 150
            assert item["token_usage"]["task_tokens"] == 120
            assert item["token_usage"]["chat_tokens"] == 30
            assert item["token_usage"]["budget"] == 10000

            detail = await project_detail(db, project)
            assert detail["members"][0]["employee_id"] == owner.id
            assert detail["tasks"][0]["id"] == task.id
            assert detail["conversations"][0]["id"] == conversation.id
            assert detail["token_usage"]["tokens"] == 150

            await unlink_conversation(db, project, conversation.id)
            await db.flush()
            assert conversation.project_id is None
            with pytest.raises(NotFoundError):
                await unlink_conversation(db, project, conversation.id)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_pending_tool_decisions_approve_and_reject() -> None:
    """待确认工具可逐条批准/拒绝，未处理项保留在消息元数据中。"""
    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.skills.tools.models import Tool
    from app.domains.workforce.conversations.models import ChatMessage, Conversation
    from app.domains.workforce.conversations.service import decide_pending_tools
    from app.domains.workforce.employees.models import DigitalEmployee

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"审批测试 {suffix}", code=f"itool_{suffix}")
            db.add(tenant)
            await db.flush()

            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"审批员工 {suffix}",
                code=f"tool_emp_{suffix}",
                position="测试",
                status="active",
                config={},
            )
            tool = Tool(
                tenant_id=tenant.id,
                name="审批用工具",
                code=f"approve_tool_{suffix}",
                tool_type="python",
                description="返回入参",
                parameters_schema={},
                config={
                    "code": "def run(args):\n    return {'echo': args.get('value')}\n"
                },
                risk_level="low",
                enabled=True,
                source="custom",
            )
            db.add_all([employee, tool])
            await db.flush()

            conversation = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"审批会话 {suffix}",
                status="active",
            )
            db.add(conversation)
            await db.flush()

            pending = [
                {"tool": tool.code, "arguments": {"value": 1}, "reason": "需请示"},
                {"tool": tool.code, "arguments": {"value": 2}, "reason": "需请示"},
                {"tool": tool.code, "arguments": {"value": 3}, "reason": "需请示"},
            ]
            message = ChatMessage(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                employee_id=employee.id,
                role="assistant",
                content="需要确认后执行",
                tool_calls=[],
                tokens=0,
                cost=0.0,
                status="sent",
                message_metadata={"pending_tools": pending},
            )
            db.add(message)
            await db.flush()

            result = await decide_pending_tools(
                db,
                conversation,
                message.id,
                [
                    {"index": 0, "approved": True},
                    {"index": 1, "approved": False},
                ],
            )
            assert [item["decision"] for item in result["results"]] == [
                "confirmed",
                "rejected",
            ]
            assert result["results"][0]["output"]["result"] == {"echo": 1}
            assert len(result["remaining"]) == 1
            assert result["remaining"][0]["arguments"] == {"value": 3}
            assert message.message_metadata["pending_tools"] == result["remaining"]

            reply = await db.get(ChatMessage, result["message"]["id"])
            assert reply is not None
            assert "已执行" in reply.content
            assert "已拒绝" in reply.content
            assert reply.message_metadata["kind"] == "tool_decision"

            final = await decide_pending_tools(
                db,
                conversation,
                message.id,
                [{"index": 0, "approved": True}],
            )
            assert final["results"][0]["output"]["result"] == {"echo": 3}
            assert final["remaining"] == []
            assert message.message_metadata["pending_tools"] == []
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_token_usage_filters_and_csv_export() -> None:
    """Token 明细可按项目/工具/来源筛选，并导出带公式转义的 CSV。"""
    import csv
    import io

    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.workflows.tasks.models import TaskInstance, TaskStep
    from app.domains.workforce.conversations.models import ChatMessage, Conversation
    from app.domains.workforce.employees.analytics import token_usage, token_usage_csv
    from app.domains.workforce.employees.models import DigitalEmployee
    from app.domains.workforce.projects.models import Project

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"Token 测试 {suffix}", code=f"itoken_{suffix}")
            db.add(tenant)
            await db.flush()

            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"Token 员工 {suffix}",
                code=f"token_emp_{suffix}",
                status="active",
                model_name="fake-model",
                config={},
            )
            project_a = Project(
                tenant_id=tenant.id,
                name=f"项目A {suffix}",
                code=f"token_pa_{suffix}",
            )
            project_b = Project(
                tenant_id=tenant.id,
                name=f"项目B {suffix}",
                code=f"token_pb_{suffix}",
            )
            db.add_all([employee, project_a, project_b])
            await db.flush()

            task_a = TaskInstance(
                tenant_id=tenant.id,
                employee_id=employee.id,
                project_id=project_a.id,
                title="=SUM(A1)",
                task_type="free",
                status="succeeded",
                input={},
                output={},
                plan=[],
            )
            task_b = TaskInstance(
                tenant_id=tenant.id,
                employee_id=employee.id,
                project_id=project_b.id,
                title=f"任务B {suffix}",
                task_type="free",
                status="succeeded",
                input={},
                output={},
                plan=[],
            )
            conversation = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"会话A {suffix}",
                status="active",
                project_id=project_a.id,
            )
            db.add_all([task_a, task_b, conversation])
            await db.flush()

            db.add_all(
                [
                    TaskStep(
                        instance_id=task_a.id,
                        step_index=0,
                        name="调用工具",
                        step_type="tool",
                        tool_code="tool_x",
                        tokens=100,
                        cost=0.01,
                    ),
                    TaskStep(
                        instance_id=task_b.id,
                        step_index=0,
                        name="调用工具",
                        step_type="tool",
                        tool_code="tool_y",
                        tokens=50,
                        cost=0.005,
                    ),
                    ChatMessage(
                        tenant_id=tenant.id,
                        conversation_id=conversation.id,
                        employee_id=employee.id,
                        role="assistant",
                        content="完成",
                        tool_calls=[{"tool": "tool_x"}],
                        tokens=25,
                        cost=0.0025,
                        message_metadata={"model": "fake-model"},
                    ),
                ]
            )
            await db.flush()

            overall = await token_usage(db, employee, days=30)
            assert overall["total_tokens"] == 175
            assert overall["filtered_total"] == 3
            assert {item["id"] for item in overall["project_options"]} == {
                project_a.id,
                project_b.id,
            }
            assert overall["tool_options"] == ["tool_x", "tool_y"]

            by_project = await token_usage(
                db, employee, days=30, project_id=project_a.id
            )
            assert by_project["total_tokens"] == 125
            assert by_project["filtered_total"] == 2
            assert by_project["by_source"] == {"task": 100, "chat": 25}

            by_tool = await token_usage(
                db, employee, days=30, tool_code="tool_x"
            )
            assert by_tool["total_tokens"] == 125

            by_chat = await token_usage(db, employee, days=30, source="chat")
            assert by_chat["total_tokens"] == 25
            assert by_chat["filtered_total"] == 1

            csv_text = await token_usage_csv(
                db, employee, days=30, project_id=project_a.id
            )
            assert csv_text.startswith("\ufeff")
            rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
            assert rows[0][0] == "时间"
            assert "项目" in rows[0]
            assert len(rows) == 3
            assert any("'=SUM(A1)" in row for row in rows[1:])
            assert all("tool_y" not in ",".join(row) for row in rows[1:])
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_chat_context_references_and_task_creation() -> None:
    """对话 @文件/@会话 生成上下文，且可把消息直接创建为任务。"""
    from app.core.database import SessionLocal
    from app.core.exceptions import BadRequestError
    from app.domains.identity.models import Tenant
    from app.domains.knowledge.models import KnowledgeBase, KnowledgeDocument
    from app.domains.workforce.conversations.models import (
        ChatMessage,
        Conversation,
        ConversationMember,
    )
    from app.domains.workforce.conversations.service import (
        _build_context,
        create_task_from_conversation,
    )
    from app.domains.workforce.employees.models import DigitalEmployee

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"上下文测试 {suffix}", code=f"ictx_{suffix}")
            db.add(tenant)
            await db.flush()

            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"上下文员工 {suffix}",
                code=f"ctx_emp_{suffix}",
                status="active",
                config={},
            )
            second = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"上下文员工二 {suffix}",
                code=f"ctx_emp2_{suffix}",
                status="active",
                config={},
            )
            base = KnowledgeBase(
                tenant_id=tenant.id,
                name=f"知识库 {suffix}",
                code=f"ctx_kb_{suffix}",
                status="active",
            )
            db.add_all([employee, second, base])
            await db.flush()

            document = KnowledgeDocument(
                tenant_id=tenant.id,
                base_id=base.id,
                title=f"回款制度 {suffix}",
                content="逾期 30 天需发送催收函。",
                chunk_count=1,
                status="active",
            )
            conversation = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"主会话 {suffix}",
                status="active",
            )
            other = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"历史会话 {suffix}",
                status="active",
            )
            db.add_all([document, conversation, other])
            await db.flush()
            db.add_all(
                [
                    ConversationMember(
                        tenant_id=tenant.id,
                        conversation_id=conversation.id,
                        employee_id=employee.id,
                        role="owner",
                    ),
                    ChatMessage(
                        tenant_id=tenant.id,
                        conversation_id=other.id,
                        employee_id=employee.id,
                        role="user",
                        content="客户 A 已回款 5000",
                        tokens=0,
                        cost=0.0,
                    ),
                    ChatMessage(
                        tenant_id=tenant.id,
                        conversation_id=other.id,
                        employee_id=employee.id,
                        role="assistant",
                        content="已记录，待对账。",
                        tokens=3,
                        cost=0.0,
                    ),
                ]
            )
            await db.flush()

            context, metadata = await _build_context(
                db, conversation, [document.id], [other.id]
            )
            assert context is not None
            assert "回款制度" in context
            assert "逾期 30 天" in context
            assert "客户 A 已回款 5000" in context
            assert metadata["context_documents"][0]["id"] == document.id
            assert metadata["context_conversations"][0]["id"] == other.id
            # 自身会话不作为上下文
            _, meta_self = await _build_context(
                db, conversation, [], [conversation.id]
            )
            assert meta_self["context_conversations"] == []

            created = await create_task_from_conversation(
                db,
                conversation,
                "核对客户 A 回款\n并生成催收待办",
                employee_id=employee.id,
            )
            assert created["task"]["title"] == "核对客户 A 回款"
            assert created["task"]["employee_id"] == employee.id
            assert created["task"]["input"]["conversation_id"] == conversation.id
            assert created["task"]["input"]["instruction"].startswith("核对客户 A 回款")
            assert created["message"]["message_metadata"]["kind"] == "task_created"
            assert (
                created["message"]["message_metadata"]["task_id"]
                == created["task"]["id"]
            )
            assert conversation.last_message_at is not None

            with_context = await create_task_from_conversation(
                db,
                conversation,
                "生成催收函",
                employee_id=employee.id,
                context_document_ids=[document.id],
            )
            assert "回款制度" in with_context["task"]["input"]["context"]
            assert (
                with_context["message"]["message_metadata"]["context_documents"][0][
                    "id"
                ]
                == document.id
            )

            group = Conversation(
                tenant_id=tenant.id,
                mode="group",
                title=f"群聊 {suffix}",
                status="active",
            )
            db.add(group)
            await db.flush()
            db.add_all(
                [
                    ConversationMember(
                        tenant_id=tenant.id,
                        conversation_id=group.id,
                        employee_id=employee.id,
                        role="owner",
                    ),
                    ConversationMember(
                        tenant_id=tenant.id,
                        conversation_id=group.id,
                        employee_id=second.id,
                        role="member",
                    ),
                ]
            )
            await db.flush()
            with pytest.raises(BadRequestError):
                await create_task_from_conversation(
                    db, group, "未指定员工的任务"
                )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_stream_message_events_and_attachments(monkeypatch) -> None:
    """流式事件顺序、增量回调，以及附件文本进入任务上下文。"""
    from app.core.database import SessionLocal
    from app.domains.identity.models import Tenant
    from app.domains.workforce.conversations import service as conv_service
    from app.domains.workforce.conversations.models import (
        ChatAttachment,
        ChatMessage,
        Conversation,
        ConversationMember,
    )
    from app.domains.workforce.conversations.service import (
        create_task_from_conversation,
        stream_message,
    )
    from app.domains.workforce.conversations.storage import extract_text
    from app.domains.workforce.employees.models import DigitalEmployee

    async def fake_run_turn(
        db,
        conversation,
        employee,
        agent,
        content,
        member_names,
        *,
        user_id=None,
        context_block=None,
        delta_callback=None,
    ):
        if delta_callback is not None:
            await delta_callback("你")
            await delta_callback("好")
        message = ChatMessage(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            employee_id=employee.id,
            role="assistant",
            content="你好",
            tool_calls=[],
            tokens=2,
            cost=0.0,
            status="sent",
            message_metadata={"model": "fake"},
        )
        db.add(message)
        await db.flush()
        return message

    monkeypatch.setattr(conv_service, "_run_turn", fake_run_turn)
    assert extract_text(b"hello", "txt") == "hello"
    assert extract_text(b"hello", "exe") == ""

    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as db:
        try:
            tenant = Tenant(name=f"流式测试 {suffix}", code=f"istream_{suffix}")
            db.add(tenant)
            await db.flush()
            employee = DigitalEmployee(
                tenant_id=tenant.id,
                name=f"流式员工 {suffix}",
                code=f"stream_emp_{suffix}",
                status="active",
                config={},
            )
            conversation = Conversation(
                tenant_id=tenant.id,
                mode="direct",
                title=f"流式会话 {suffix}",
                status="active",
            )
            db.add_all([employee, conversation])
            await db.flush()
            db.add(
                ConversationMember(
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    employee_id=employee.id,
                    role="owner",
                )
            )
            attachment = ChatAttachment(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                file_name="政策.txt",
                mime_type="text/plain",
                size_bytes=6,
                storage_path="test/policy.txt",
                text_excerpt="附件要求：逾期 30 天催收。",
            )
            db.add(attachment)
            await db.flush()

            events = [
                event
                async for event in stream_message(
                    db,
                    conversation,
                    "请处理",
                    attachment_ids=[attachment.id],
                    user_id=1,
                    commit=False,
                )
            ]
            types = [event["type"] for event in events]
            assert types == [
                "user_message",
                "reply_start",
                "delta",
                "delta",
                "reply_done",
                "done",
            ]
            assert events[2]["content"] == "你"
            assert events[4]["message"]["content"] == "你好"
            assert events[0]["message"]["message_metadata"]["attachments"][0][
                "id"
            ] == attachment.id
            assert conversation.last_message_at is not None
            await db.flush()
            assert attachment.message_id == events[0]["message"]["id"]

            task = await create_task_from_conversation(
                db,
                conversation,
                "按附件要求催收",
                employee_id=employee.id,
                attachment_ids=[attachment.id],
            )
            assert "逾期 30 天催收" in task["task"]["input"]["context"]
            assert (
                task["message"]["message_metadata"]["attachments"][0]["file_name"]
                == "政策.txt"
            )
        finally:
            await db.rollback()
