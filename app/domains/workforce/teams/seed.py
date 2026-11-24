"""内置角色预设与团队模板种子数据。"""

import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.domains.workforce.teams.models import RolePreset, TeamTemplate

logger = logging.getLogger(__name__)

ROLE_SEEDS = [
    {
        "code": "it_guard",
        "name": "IT值守员",
        "description": "工单分诊、密码重置、常见 IT 问题处理",
        "default_skills": ["ticket.triage", "password.reset"],
        "tool_groups": ["ServiceNow", "AD", "知识库"],
        "approval_threshold": "medium",
        "sandbox": "docker",
    },
    {
        "code": "hr_assistant",
        "name": "HR助理",
        "description": "入职、离职、合同与考勤提醒",
        "default_skills": ["onboarding.pack", "offboarding.flow"],
        "tool_groups": ["HRIS", "飞书", "OA"],
        "approval_threshold": "high",
        "sandbox": "readonly",
    },
    {
        "code": "finance_auditor",
        "name": "财务审计员",
        "description": "发票、预算、付款比对与异常标记",
        "default_skills": ["invoice.audit", "payment.check"],
        "tool_groups": ["SAP", "邮箱", "报表"],
        "approval_threshold": "dual",
        "sandbox": "docker",
    },
    {
        "code": "knowledge_operator",
        "name": "知识运营员",
        "description": "知识源接入、EKG 维护、冲突治理",
        "default_skills": ["knowledge.sync", "ekg.curate"],
        "tool_groups": ["Confluence", "语雀", "pgvector"],
        "approval_threshold": "medium",
        "sandbox": "vm",
    },
    {
        "code": "support_agent",
        "name": "客服值守",
        "description": "7x24 值守、知识回答、人工接管",
        "default_skills": ["knowledge.search", "ticket.reply"],
        "tool_groups": ["CRM", "知识库", "工单"],
        "approval_threshold": "low",
        "sandbox": "readonly",
    },
    {
        "code": "content_planner",
        "name": "内容策划",
        "description": "选题、剧本与分镜规划",
        "default_skills": ["script.plan", "storyboard.generate"],
        "tool_groups": ["知识库", "DeepSeek", "分镜"],
        "approval_threshold": "medium",
        "sandbox": "none",
    },
    {
        "code": "copywriter",
        "name": "文案生成",
        "description": "文案、标题、口播稿与改写",
        "default_skills": ["llm.write", "copy.polish"],
        "tool_groups": ["DeepSeek", "知识库"],
        "approval_threshold": "low",
        "sandbox": "none",
    },
    {
        "code": "reviewer",
        "name": "审核员",
        "description": "内容审核、质检与风险处置",
        "default_skills": ["qa.check", "risk.check"],
        "tool_groups": ["质检", "风控", "DeepSeek"],
        "approval_threshold": "high",
        "sandbox": "none",
    },
    {
        "code": "analyst",
        "name": "数据分析",
        "description": "报表、指标与异常分析",
        "default_skills": ["report.generate", "metric.analyze"],
        "tool_groups": ["报表", "数据库", "DeepSeek"],
        "approval_threshold": "medium",
        "sandbox": "vm",
    },
    {
        "code": "qa_engineer",
        "name": "测试工程师",
        "description": "用例、回归、缺陷复现",
        "default_skills": ["test.run", "bug.report"],
        "tool_groups": ["Git", "CI", "JMeter"],
        "approval_threshold": "low",
        "sandbox": "docker",
    },
    {
        "code": "pm",
        "name": "产品经理",
        "description": "需求拆解、排期与验收",
        "default_skills": ["requirement.plan", "acceptance.check"],
        "tool_groups": ["飞书", "知识库"],
        "approval_threshold": "medium",
        "sandbox": "none",
    },
    {
        "code": "developer",
        "name": "开发工程师",
        "description": "编码、Code Review 与缺陷修复",
        "default_skills": ["code.write", "code.review"],
        "tool_groups": ["Git", "CI/CD", "Docker"],
        "approval_threshold": "medium",
        "sandbox": "docker",
    },
]

TEMPLATE_SEEDS = [
    {
        "code": "ai_team",
        "name": "AI 团队",
        "description": "内容策划、文案生成、审核与数据分析的 AI 内容生产线",
        "category": "AI 内容",
        "role_codes": ["content_planner", "copywriter", "reviewer", "analyst"],
        "tags": ["AI", "内容", "审核", "DeepSeek"],
        "topology": {
            "mode": "supervisor",
            "edges": [
                {"from": "content_planner", "to": "copywriter"},
                {"from": "copywriter", "to": "reviewer"},
                {"from": "content_planner", "to": "analyst"},
            ],
        },
    },
    {
        "code": "support_team",
        "name": "客服团队",
        "description": "7x24 值守、知识回答、风险内容转人工",
        "category": "客户服务",
        "role_codes": ["support_agent", "knowledge_operator", "reviewer"],
        "tags": ["7x24", "IM", "低风险"],
        "topology": {
            "mode": "supervisor",
            "edges": [
                {"from": "support_agent", "to": "knowledge_operator"},
                {"from": "support_agent", "to": "reviewer"},
            ],
        },
    },
    {
        "code": "dev_team",
        "name": "研发团队",
        "description": "需求拆解、开发、测试与沙盒执行",
        "category": "研发",
        "role_codes": ["pm", "developer", "qa_engineer"],
        "tags": ["PM", "Git", "CI/CD"],
        "topology": {
            "mode": "pipeline",
            "edges": [
                {"from": "pm", "to": "developer"},
                {"from": "developer", "to": "qa_engineer"},
            ],
        },
    },
    {
        "code": "knowledge_team",
        "name": "知识运营团队",
        "description": "知识接入、冲突治理、审核与指标分析",
        "category": "知识运营",
        "role_codes": ["knowledge_operator", "reviewer", "analyst"],
        "tags": ["知识接入", "EKG", "审计"],
        "topology": {
            "mode": "pipeline",
            "edges": [
                {"from": "knowledge_operator", "to": "reviewer"},
                {"from": "reviewer", "to": "analyst"},
            ],
        },
    },
    {
        "code": "enterprise_team",
        "name": "企业级团队",
        "description": "覆盖 IT / HR / 财务 / 知识 / 审核的强审批团队",
        "category": "企业通用",
        "role_codes": [
            "it_guard",
            "hr_assistant",
            "finance_auditor",
            "knowledge_operator",
            "reviewer",
        ],
        "tags": ["IT", "HR", "财务", "安全"],
        "topology": {
            "mode": "supervisor",
            "edges": [
                {"from": "knowledge_operator", "to": "it_guard"},
                {"from": "knowledge_operator", "to": "hr_assistant"},
                {"from": "knowledge_operator", "to": "finance_auditor"},
                {"from": "reviewer", "to": "knowledge_operator"},
            ],
        },
    },
]


def _template_roles(template: dict, presets: dict[str, dict]) -> list[dict]:
    reports_to: dict[str, str] = {}
    for edge in (template.get("topology") or {}).get("edges", []):
        reports_to[edge["to"]] = edge["from"]

    roles = []
    for code in template["role_codes"]:
        preset = presets[code]
        roles.append(
            {
                "code": code,
                "name": preset["name"],
                "description": preset["description"],
                "skills": preset["default_skills"],
                "tools": preset["tool_groups"],
                "approval_threshold": preset["approval_threshold"],
                "sandbox": preset["sandbox"],
                "model_name": settings.llm_model,
                "reports_to": reports_to.get(code),
            }
        )
    return roles


async def seed_team_templates() -> None:
    """幂等写入平台内置角色与团队模板。"""
    presets_by_code = {seed["code"]: seed for seed in ROLE_SEEDS}

    async with SessionLocal() as session:
        existing_presets = set(
            (
                await session.scalars(
                    select(RolePreset.code).where(RolePreset.is_builtin.is_(True))
                )
            ).all()
        )
        for seed in ROLE_SEEDS:
            if seed["code"] in existing_presets:
                continue
            session.add(
                RolePreset(
                    tenant_id=None,
                    is_builtin=True,
                    status="active",
                    **seed,
                )
            )

        existing_templates = set(
            (
                await session.scalars(
                    select(TeamTemplate.code).where(TeamTemplate.is_builtin.is_(True))
                )
            ).all()
        )
        for template in TEMPLATE_SEEDS:
            if template["code"] in existing_templates:
                continue
            session.add(
                TeamTemplate(
                    tenant_id=None,
                    code=template["code"],
                    name=template["name"],
                    description=template["description"],
                    category=template["category"],
                    roles=_template_roles(template, presets_by_code),
                    topology=template["topology"],
                    tags=template["tags"],
                    is_builtin=True,
                    enabled=True,
                )
            )

        await session.commit()
        logger.info(
            "团队模板种子检查完成：%s 个内置角色，%s 个内置模板",
            len(existing_presets) or len(ROLE_SEEDS),
            len(existing_templates) or len(TEMPLATE_SEEDS),
        )
