"""审批流默认数据：财务、合同、文书三个业务模板。"""

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.identity.models import Tenant
from app.domains.workflows.approvals.models import ApprovalFlow, ApprovalForm

logger = logging.getLogger(__name__)

ADMIN_APPROVER = ["admin"]

DEFAULT_FORMS = [
    {
        "name": "费用报销单",
        "code": "tpl_expense_form",
        "category": "finance",
        "description": "差旅、餐饮、办公等费用报销；金额超过 5000 元直达总经理。",
        "fields": [
            {
                "name": "amount",
                "label": "报销金额（元）",
                "type": "number",
                "required": True,
                "placeholder": "5000",
            },
            {
                "name": "category",
                "label": "费用类型",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "travel", "label": "差旅"},
                    {"value": "meal", "label": "餐饮"},
                    {"value": "office", "label": "办公"},
                    {"value": "other", "label": "其他"},
                ],
            },
            {
                "name": "expense_date",
                "label": "发生日期",
                "type": "date",
                "required": True,
            },
            {
                "name": "department",
                "label": "所属部门",
                "type": "text",
                "required": True,
                "placeholder": "市场部",
            },
            {
                "name": "description",
                "label": "费用说明",
                "type": "textarea",
                "required": True,
                "placeholder": "说明费用用途、行程与票据情况",
            },
            {
                "name": "invoice_url",
                "label": "发票链接",
                "type": "url",
                "required": False,
                "placeholder": "https://...",
            },
        ],
    },
    {
        "name": "合同审批单",
        "code": "tpl_contract_form",
        "category": "contract",
        "description": "采购、销售、合作协议审批；法务 → 财务 → 总经理三级会签。",
        "fields": [
            {
                "name": "contract_name",
                "label": "合同名称",
                "type": "text",
                "required": True,
                "placeholder": "年度办公用品采购合同",
            },
            {
                "name": "counterparty",
                "label": "合同对方",
                "type": "text",
                "required": True,
            },
            {
                "name": "amount",
                "label": "合同金额（元）",
                "type": "number",
                "required": True,
            },
            {
                "name": "contract_type",
                "label": "合同类型",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "purchase", "label": "采购合同"},
                    {"value": "sales", "label": "销售合同"},
                    {"value": "cooperation", "label": "合作协议"},
                    {"value": "other", "label": "其他"},
                ],
            },
            {
                "name": "start_date",
                "label": "生效日期",
                "type": "date",
                "required": True,
            },
            {
                "name": "end_date",
                "label": "到期日期",
                "type": "date",
                "required": False,
            },
            {
                "name": "summary",
                "label": "合同要点",
                "type": "textarea",
                "required": True,
                "placeholder": "标的、付款方式、违约责任等",
            },
            {
                "name": "attachment_url",
                "label": "合同附件链接",
                "type": "url",
                "required": False,
            },
        ],
    },
    {
        "name": "文书用印申请",
        "code": "tpl_document_form",
        "category": "document",
        "description": "通知、函件、报告及用印申请；部门负责人 → 用印管理员。",
        "fields": [
            {
                "name": "document_title",
                "label": "文书标题",
                "type": "text",
                "required": True,
                "placeholder": "关于国庆放假安排的通知",
            },
            {
                "name": "document_type",
                "label": "文书类型",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "notice", "label": "通知"},
                    {"value": "letter", "label": "函件"},
                    {"value": "report", "label": "报告"},
                    {"value": "seal", "label": "用印申请"},
                ],
            },
            {
                "name": "purpose",
                "label": "用途说明",
                "type": "textarea",
                "required": True,
            },
            {
                "name": "urgency",
                "label": "紧急程度",
                "type": "select",
                "required": True,
                "options": [
                    {"value": "low", "label": "普通"},
                    {"value": "normal", "label": "较急"},
                    {"value": "high", "label": "紧急"},
                ],
            },
            {
                "name": "attachment_url",
                "label": "文书附件链接",
                "type": "url",
                "required": False,
            },
        ],
    },
]

DEFAULT_FLOWS = [
    {
        "name": "费用报销审批",
        "code": "tpl_expense_flow",
        "category": "finance",
        "form_code": "tpl_expense_form",
        "description": "金额 > 5000 元先由总经理审批，否则财务审核后再由总经理审批。",
        "config": {"auto_launch_task": False, "title_template": "审批通过：{title}"},
        "nodes": [
            {
                "key": "c1",
                "name": "金额判断",
                "type": "condition",
                "field": "amount",
                "operator": "gt",
                "value": 5000,
                "on_true": "boss",
                "on_false": "finance",
            },
            {
                "key": "finance",
                "name": "财务审核",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {
                "key": "boss",
                "name": "总经理审批",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {"key": "end", "name": "结束", "type": "end"},
        ],
    },
    {
        "name": "合同审批",
        "code": "tpl_contract_flow",
        "category": "contract",
        "form_code": "tpl_contract_form",
        "description": "法务审核 → 财务审核 → 总经理审批，三级会签。",
        "config": {"auto_launch_task": False, "title_template": "审批通过：{title}"},
        "nodes": [
            {
                "key": "legal",
                "name": "法务审核",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {
                "key": "finance",
                "name": "财务审核",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {
                "key": "boss",
                "name": "总经理审批",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {"key": "end", "name": "结束", "type": "end"},
        ],
    },
    {
        "name": "文书用印审批",
        "code": "tpl_document_flow",
        "category": "document",
        "form_code": "tpl_document_form",
        "description": "部门负责人 → 用印管理员；负责人节点超时先提醒。",
        "config": {"auto_launch_task": False, "title_template": "审批通过：{title}"},
        "nodes": [
            {
                "key": "leader",
                "name": "部门负责人审批",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "any",
                "timeout_hours": 8,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {
                "key": "seal",
                "name": "用印管理员",
                "type": "approval",
                "approvers": ADMIN_APPROVER,
                "mode": "all",
                "timeout_hours": 24,
                "timeout_action": "remind",
                "allow_transfer": True,
                "allow_add_sign": True,
            },
            {"key": "end", "name": "结束", "type": "end"},
        ],
    },
]


async def seed_approval_templates() -> None:
    """按租户幂等初始化表单与流程模板。"""
    async with SessionLocal() as session:
        tenant_ids = list((await session.scalars(select(Tenant.id))).all())
        if not tenant_ids:
            return

        created_forms = 0
        created_flows = 0
        for tenant_id in tenant_ids:
            existing_forms = {
                form.code: form
                for form in (
                    await session.scalars(
                        select(ApprovalForm).where(ApprovalForm.tenant_id == tenant_id)
                    )
                ).all()
            }
            for item in DEFAULT_FORMS:
                if item["code"] in existing_forms:
                    continue
                form = ApprovalForm(tenant_id=tenant_id, **item)
                session.add(form)
                existing_forms[item["code"]] = form
                created_forms += 1
            await session.flush()

            existing_flow_codes = set(
                (
                    await session.scalars(
                        select(ApprovalFlow.code).where(
                            ApprovalFlow.tenant_id == tenant_id
                        )
                    )
                ).all()
            )
            for item in DEFAULT_FLOWS:
                if item["code"] in existing_flow_codes:
                    continue
                form = existing_forms.get(item["form_code"])
                data = {key: value for key, value in item.items() if key != "form_code"}
                session.add(
                    ApprovalFlow(
                        tenant_id=tenant_id,
                        form_id=form.id if form else None,
                        **data,
                    )
                )
                created_flows += 1

        await session.commit()

    if created_forms or created_flows:
        logger.info(
            "审批模板初始化完成：%s 个表单，%s 个流程",
            created_forms,
            created_flows,
        )
