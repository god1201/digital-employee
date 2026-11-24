"""平台内置技能包种子。"""

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.skills.marketplace.models import SkillPackage

logger = logging.getLogger(__name__)

SKILL_SEEDS = [
    {
        "code": "lang.reply_style",
        "name": "话术生成",
        "category": "language",
        "description": "根据客户上下文生成专业、克制、结论先行的回复",
        "algorithm": "风格约束 Prompt + Few-shot",
        "prompt_template": "生成回复时结论先行，使用公司口径，只输出结构化结果，不做承诺。",
        "permissions": {"read_only": True, "risk_level": "low"},
        "common_combos": ["lang.emotion", "lang.summarize"],
        "tags": ["话术", "客服", "销售"],
    },
    {
        "code": "lang.emotion",
        "name": "情绪识别",
        "category": "language",
        "description": "识别客户情绪与升级风险，输出情绪标签和安抚建议",
        "algorithm": "文本分类 + 规则兜底",
        "prompt_template": "先判断客户情绪（平静/不满/愤怒），再给出安抚建议，不直接回复客户。",
        "permissions": {"read_only": True, "risk_level": "low"},
        "common_combos": ["lang.reply_style"],
        "tags": ["情绪", "客服"],
    },
    {
        "code": "lang.summarize",
        "name": "摘要压缩",
        "category": "language",
        "description": "把长对话、工单、会议纪要压缩为结论与待办",
        "algorithm": "长上下文摘要",
        "prompt_template": "输出结论、关键事实、待办三部分，不超过 5 条。",
        "permissions": {"read_only": True, "risk_level": "low"},
        "common_combos": ["lang.reply_style"],
        "tags": ["摘要", "纪要"],
    },
    {
        "code": "data.sql_query",
        "name": "SQL 查询",
        "category": "data",
        "description": "把自然语言问题转换为只读 SQL 并执行",
        "algorithm": "NL2SQL + 只读校验",
        "prompt_template": "只生成 SELECT 查询；涉及金额、条数时附带口径说明。",
        "tool_codes": ["sql_query"],
        "permissions": {
            "read_only": True,
            "risk_level": "medium",
            "data_scopes": ["warehouse"],
        },
        "common_combos": ["data.report", "data.anomaly"],
        "tags": ["SQL", "数据分析"],
    },
    {
        "code": "data.report",
        "name": "报表生成",
        "category": "data",
        "description": "基于查询结果生成日报/周报与指标看板",
        "algorithm": "模板渲染 + 指标计算",
        "prompt_template": "输出指标表与异常说明；表格不超过 5 列。",
        "tool_codes": ["report_export"],
        "dependencies": [{"code": "data.sql_query", "min_version": 1}],
        "permissions": {"read_only": True, "risk_level": "medium"},
        "common_combos": ["data.sql_query", "data.anomaly"],
        "tags": ["报表", "指标"],
    },
    {
        "code": "data.anomaly",
        "name": "异常检测",
        "category": "data",
        "description": "对指标序列做异常识别并给出可能原因",
        "algorithm": "统计阈值 + 归因规则",
        "prompt_template": "列出异常点、偏离幅度、可能原因与建议动作。",
        "dependencies": [{"code": "data.sql_query", "min_version": 1}],
        "permissions": {"read_only": True, "risk_level": "medium"},
        "common_combos": ["data.sql_query", "data.report"],
        "tags": ["异常", "监控"],
    },
    {
        "code": "process.ticket",
        "name": "工单流转",
        "category": "process",
        "description": "创建、分派、流转与关闭工单",
        "algorithm": "流程状态机",
        "prompt_template": "每个动作输出工单号、动作、下一责任人；关闭前必须校验解决说明。",
        "tool_codes": ["ticket_update"],
        "permissions": {"read_only": False, "risk_level": "medium"},
        "common_combos": ["process.remind"],
        "tags": ["工单", "流程"],
    },
    {
        "code": "process.remind",
        "name": "催办提醒",
        "category": "process",
        "description": "按 SLA 生成催办消息并发送提醒",
        "algorithm": "SLA 扫描 + 消息模板",
        "prompt_template": "催办消息包含事项、截止时间、影响与升级路径。",
        "tool_codes": ["notification_send"],
        "dependencies": [{"code": "process.ticket", "min_version": 1}],
        "permissions": {
            "read_only": False,
            "risk_level": "medium",
            "data_scopes": ["contacts"],
        },
        "common_combos": ["process.ticket"],
        "tags": ["催办", "SLA"],
    },
    {
        "code": "process.schedule",
        "name": "日程调度",
        "category": "process",
        "description": "会议室、日程与差旅安排",
        "algorithm": "约束求解 + 冲突检测",
        "prompt_template": "排期前检查冲突；输出时段、参与人、地点与备用方案。",
        "tool_codes": ["calendar_api"],
        "permissions": {"read_only": False, "risk_level": "low"},
        "tags": ["日程", "会议"],
    },
    {
        "code": "audit.doc_parse",
        "name": "文档解析",
        "category": "audit",
        "description": "解析合同、票据、报表等文档结构与关键字段",
        "algorithm": "OCR + 版面分析",
        "prompt_template": "输出文档类型、关键字段、缺失字段与置信度。",
        "tool_codes": ["doc_parser"],
        "permissions": {
            "read_only": True,
            "risk_level": "medium",
            "data_scopes": ["documents"],
        },
        "common_combos": ["audit.contract", "audit.invoice"],
        "tags": ["OCR", "文档"],
    },
    {
        "code": "audit.invoice",
        "name": "票据核验",
        "category": "audit",
        "description": "发票真伪、金额与报销规则核对",
        "algorithm": "票据 OCR + 规则比对",
        "prompt_template": "输出核验结论、差异项与建议动作；金额超阈值必须转人工。",
        "tool_codes": ["doc_parser", "invoice_check"],
        "dependencies": [{"code": "audit.doc_parse", "min_version": 1}],
        "permissions": {
            "read_only": True,
            "risk_level": "high",
            "amount_threshold": 50000,
            "data_scopes": ["finance"],
        },
        "common_combos": ["audit.doc_parse"],
        "tags": ["发票", "财务"],
    },
    {
        "code": "audit.contract",
        "name": "合同比对",
        "category": "audit",
        "description": "合同条款抽取与风险条款库比对",
        "algorithm": "条款抽取 + 风险 RAG",
        "prompt_template": "输出风险条款、等级、依据条款与建议修改；仅辅助，不出具法律意见。",
        "tool_codes": ["doc_parser", "contract_search"],
        "dependencies": [{"code": "audit.doc_parse", "min_version": 1}],
        "permissions": {
            "read_only": True,
            "risk_level": "high",
            "data_scopes": ["contracts"],
        },
        "common_combos": ["audit.doc_parse", "audit.compliance"],
        "tags": ["合同", "法务"],
    },
    {
        "code": "audit.compliance",
        "name": "合规扫描",
        "category": "audit",
        "description": "对文案、合同与流程做合规扫描",
        "algorithm": "敏感词 + 合规规则库",
        "prompt_template": "输出命中规则、风险等级与处置建议；合规类问题不得自行放行。",
        "dependencies": [{"code": "audit.contract", "min_version": 1}],
        "permissions": {
            "read_only": True,
            "risk_level": "high",
            "data_scopes": ["contracts", "content"],
        },
        "common_combos": ["audit.contract"],
        "tags": ["合规", "风控"],
    },
    {
        "code": "learn.feedback",
        "name": "反馈采集",
        "category": "learning",
        "description": "采集人工接管、评分与业务结果回执",
        "algorithm": "事件埋点 + 归因",
        "prompt_template": "记录原输出、终稿、修改理由与影响范围，不修改岗位契约。",
        "permissions": {"read_only": True, "risk_level": "low"},
        "common_combos": ["learn.ask"],
        "tags": ["学习", "反馈"],
    },
    {
        "code": "learn.ask",
        "name": "主动提问",
        "category": "learning",
        "description": "在不确定或 must_ask 场景下结构化提问",
        "algorithm": "置信度阈值 + 选项化问法",
        "prompt_template": "问题必须选项化，附默认建议；每天提问次数受预算限制。",
        "dependencies": [{"code": "learn.feedback", "min_version": 1}],
        "permissions": {"read_only": True, "risk_level": "low"},
        "common_combos": ["learn.feedback"],
        "tags": ["主动学习", "澄清"],
    },
]


async def seed_skill_packages() -> None:
    """幂等写入平台内置技能包。"""
    async with SessionLocal() as session:
        existing = set(
            (
                await session.scalars(
                    select(SkillPackage.code).where(SkillPackage.is_builtin.is_(True))
                )
            ).all()
        )
        added = 0
        for seed in SKILL_SEEDS:
            if seed["code"] in existing:
                continue
            session.add(
                SkillPackage(
                    tenant_id=None,
                    version=1,
                    status="published",
                    is_builtin=True,
                    **seed,
                )
            )
            added += 1
        await session.commit()
        logger.info(
            "技能包种子检查完成：新增 %s 个，内置共 %s 个",
            added,
            len(existing) + added,
        )
