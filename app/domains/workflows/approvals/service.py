"""审批流引擎。

流程节点按顺序执行，`condition` 节点按表单字段跳转，`approval` 节点支持
或签（any）、会签（all）、依次审批（sequence），并提供转办、加签、催办、
超时提醒/自动通过/自动驳回/升级以及审批通过后创建数字员工任务。
"""

import json
import logging
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.base import utcnow
from app.core.config import settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.domains.identity.models import User
from app.domains.workflows.approvals.models import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalForm,
    ApprovalInstance,
    ApprovalNotification,
    ApprovalTask,
)
from app.domains.workflows.tasks.models import TaskInstance
from app.domains.workforce.employees.models import DigitalEmployee

logger = logging.getLogger(__name__)

FORM_FIELD_TYPES = {
    "text",
    "textarea",
    "number",
    "date",
    "select",
    "user",
    "users",
    "file",
    "url",
    "json",
}
NODE_TYPES = {"approval", "condition", "cc", "end"}
APPROVER_MODES = {"any", "all", "sequence"}
TIMEOUT_ACTIONS = {"remind", "auto_approve", "auto_reject", "escalate"}
OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "exists"}
SPECIAL_APPROVERS = {"initiator", "admin"}

ACTION_LABELS = {
    "submit": "提交审批",
    "node_enter": "进入节点",
    "approve": "通过",
    "reject": "驳回",
    "transfer": "转办",
    "add_sign": "加签",
    "remind": "催办",
    "timeout_remind": "超时提醒",
    "timeout_approve": "超时自动通过",
    "timeout_reject": "超时自动驳回",
    "timeout_escalate": "超时升级",
    "cancel": "取消",
    "complete": "流程结束",
    "launch_task": "创建数字员工任务",
}


class ApprovalEngineError(Exception):
    """流程执行中的结构性错误。"""


# ---------------------------------------------------------------- validation


def normalize_fields(raw_fields) -> list[dict]:
    if raw_fields is None:
        return []
    if not isinstance(raw_fields, list):
        raise BadRequestError("表单字段必须是数组")
    fields: list[dict] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_fields, start=1):
        if not isinstance(raw, dict):
            raise BadRequestError(f"第 {index} 个表单字段格式不正确")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise BadRequestError(f"第 {index} 个表单字段缺少 name")
        if name in names:
            raise BadRequestError(f"表单字段 name 重复: {name}")
        names.add(name)
        field_type = str(raw.get("type") or "text").lower()
        if field_type not in FORM_FIELD_TYPES:
            raise BadRequestError(f"不支持的字段类型: {field_type}")
        field = {
            "name": name,
            "label": str(raw.get("label") or name)[:128],
            "type": field_type,
            "required": bool(raw.get("required", False)),
            "placeholder": str(raw.get("placeholder") or ""),
            "help": str(raw.get("help") or ""),
        }
        if raw.get("default") not in (None, ""):
            field["default"] = raw["default"]
        if field_type == "select":
            options = raw.get("options") or []
            if not isinstance(options, list) or not options:
                raise BadRequestError(f"字段「{field['label']}」缺少选项")
            normalized_options = []
            for option in options:
                if isinstance(option, dict):
                    value = str(option.get("value", "")).strip()
                    label = str(option.get("label") or value)
                else:
                    value = str(option).strip()
                    label = value
                if not value:
                    continue
                normalized_options.append({"value": value, "label": label})
            if not normalized_options:
                raise BadRequestError(f"字段「{field['label']}」缺少有效选项")
            field["options"] = normalized_options
        fields.append(field)
    return fields


def normalize_approvers(raw_approvers) -> list[int | str]:
    if raw_approvers is None:
        return []
    if not isinstance(raw_approvers, list):
        raise BadRequestError("审批人必须是数组")
    approvers: list[int | str] = []
    for item in raw_approvers:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            approvers.append(item)
        elif isinstance(item, str):
            value = item.strip()
            if value in SPECIAL_APPROVERS:
                approvers.append(value)
            elif value.isdigit():
                approvers.append(int(value))
        elif isinstance(item, float) and item.is_integer():
            approvers.append(int(item))
    deduped: list[int | str] = []
    for item in approvers:
        if item not in deduped:
            deduped.append(item)
    if len(deduped) > 50:
        raise BadRequestError("单个节点的审批人不能超过 50 个")
    return deduped


def normalize_nodes(raw_nodes) -> list[dict]:
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise BadRequestError("流程至少需要一个节点")
    nodes: list[dict] = []
    keys: set[str] = set()
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            raise BadRequestError(f"第 {index} 个流程节点格式不正确")
        node_type = str(raw.get("type") or "approval").lower()
        if node_type not in NODE_TYPES:
            raise BadRequestError(f"不支持的节点类型: {node_type}")
        key = str(raw.get("key") or f"n{index}").strip()
        if not key:
            raise BadRequestError(f"第 {index} 个节点缺少 key")
        if key in keys:
            raise BadRequestError(f"节点 key 重复: {key}")
        keys.add(key)
        node: dict = {
            "key": key,
            "name": str(raw.get("name") or f"节点 {index}")[:128],
            "type": node_type,
        }
        if node_type == "approval":
            approvers = normalize_approvers(raw.get("approvers"))
            if not approvers:
                raise BadRequestError(f"审批节点「{node['name']}」缺少审批人")
            mode = str(raw.get("mode") or "any").lower()
            if mode not in APPROVER_MODES:
                raise BadRequestError(f"节点「{node['name']}」的审批模式无效")
            try:
                timeout_hours = int(raw.get("timeout_hours") or 0)
            except (TypeError, ValueError) as exc:
                raise BadRequestError(f"节点「{node['name']}」的超时时间无效") from exc
            timeout_action = str(raw.get("timeout_action") or "remind").lower()
            if timeout_action not in TIMEOUT_ACTIONS:
                raise BadRequestError(f"节点「{node['name']}」的超时动作无效")
            escalate_to = normalize_approvers(raw.get("escalate_to"))
            if timeout_action == "escalate" and not escalate_to:
                raise BadRequestError(f"节点「{node['name']}」配置了超时升级，但没有升级审批人")
            node.update(
                {
                    "approvers": approvers,
                    "mode": mode,
                    "timeout_hours": max(0, min(timeout_hours, 720)),
                    "timeout_action": timeout_action,
                    "escalate_to": escalate_to,
                    "cc": normalize_approvers(raw.get("cc")),
                    "allow_transfer": bool(raw.get("allow_transfer", True)),
                    "allow_add_sign": bool(raw.get("allow_add_sign", True)),
                }
            )
        elif node_type == "condition":
            field = str(raw.get("field") or "").strip()
            if not field:
                raise BadRequestError(f"条件节点「{node['name']}」缺少判断字段")
            operator = str(raw.get("operator") or "eq").lower()
            if operator not in OPERATORS:
                raise BadRequestError(f"条件节点「{node['name']}」的判断符无效")
            node.update(
                {
                    "field": field,
                    "operator": operator,
                    "value": raw.get("value"),
                    "on_true": str(raw.get("on_true") or "").strip() or None,
                    "on_false": str(raw.get("on_false") or "").strip() or None,
                }
            )
            if not node["on_true"] and not node["on_false"]:
                raise BadRequestError(f"条件节点「{node['name']}」缺少跳转目标")
        elif node_type == "cc":
            cc = normalize_approvers(raw.get("cc"))
            if not cc:
                raise BadRequestError(f"抄送节点「{node['name']}」缺少抄送人")
            node["cc"] = cc
        nodes.append(node)

    key_set = {node["key"] for node in nodes}
    for node in nodes:
        if node["type"] == "condition":
            for target in (node.get("on_true"), node.get("on_false")):
                if target and target not in key_set:
                    raise BadRequestError(
                        f"条件节点「{node['name']}」跳转目标不存在: {target}"
                    )
    return nodes


def validate_form_data(fields: list[dict], data: dict | None) -> dict:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BadRequestError("form_data 必须是 JSON 对象")
    result: dict = {}
    for field in fields:
        name = field["name"]
        label = field.get("label") or name
        field_type = field.get("type") or "text"
        value = data.get(name)
        if value is None or value == "" or value == []:
            if field.get("required"):
                raise BadRequestError(f"字段「{label}」必填")
            continue
        try:
            if field_type == "number":
                number = float(value)
                value = int(number) if number.is_integer() else number
            elif field_type == "date":
                value = str(value)[:10]
                date.fromisoformat(value)
            elif field_type == "select":
                allowed = {str(option["value"]) for option in field.get("options") or []}
                if str(value) not in allowed:
                    raise BadRequestError(f"字段「{label}」的选项无效")
                value = str(value)
            elif field_type == "user":
                value = int(value)
            elif field_type == "users":
                if not isinstance(value, list):
                    raise ValueError
                value = [int(item) for item in value]
            elif field_type == "json":
                if not isinstance(value, (dict, list)):
                    raise ValueError
            else:
                value = str(value).strip()
                if field.get("required") and not value:
                    raise BadRequestError(f"字段「{label}」必填")
        except BadRequestError:
            raise
        except (TypeError, ValueError) as exc:
            raise BadRequestError(f"字段「{label}」格式不正确") from exc
        result[name] = value
    return result


async def _validate_user_values(
    db: AsyncSession, tenant_id: int, fields: list[dict], data: dict
) -> None:
    user_ids: set[int] = set()
    for field in fields:
        value = data.get(field["name"])
        if field.get("type") == "user" and isinstance(value, int):
            user_ids.add(value)
        elif field.get("type") == "users" and isinstance(value, list):
            user_ids.update(int(item) for item in value)
    if not user_ids:
        return
    rows = list(
        (
            await db.scalars(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.id.in_(user_ids),
                    User.is_active.is_(True),
                )
            )
        ).all()
    )
    if len(rows) != len(user_ids):
        raise BadRequestError("表单中包含不存在或已停用的用户")


# ---------------------------------------------------------------- lookups


async def get_form(db: AsyncSession, tenant_id: int, form_id: int) -> ApprovalForm:
    form = await db.scalar(
        select(ApprovalForm).where(
            ApprovalForm.id == form_id, ApprovalForm.tenant_id == tenant_id
        )
    )
    if form is None:
        raise NotFoundError("审批表单不存在")
    return form


async def get_flow(db: AsyncSession, tenant_id: int, flow_id: int) -> ApprovalFlow:
    flow = await db.scalar(
        select(ApprovalFlow).where(
            ApprovalFlow.id == flow_id, ApprovalFlow.tenant_id == tenant_id
        )
    )
    if flow is None:
        raise NotFoundError("审批流程不存在")
    return flow


async def get_instance(
    db: AsyncSession, tenant_id: int, instance_id: int
) -> ApprovalInstance:
    instance = await db.scalar(
        select(ApprovalInstance).where(
            ApprovalInstance.id == instance_id,
            ApprovalInstance.tenant_id == tenant_id,
        )
    )
    if instance is None:
        raise NotFoundError("审批实例不存在")
    return instance


async def resolve_approvers(
    db: AsyncSession,
    tenant_id: int,
    specs: list[int | str] | None,
    initiator_id: int | None = None,
) -> list[int]:
    resolved: list[int] = []

    def add(user_id: int | None) -> None:
        if user_id and user_id not in resolved:
            resolved.append(user_id)

    for spec in specs or []:
        if spec == "initiator":
            add(initiator_id)
            continue
        if spec == "admin":
            admins = await db.scalars(
                select(User.id).where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                    User.is_superuser.is_(True),
                )
            )
            for user_id in admins:
                add(user_id)
            continue
        try:
            user_id = int(spec)
        except (TypeError, ValueError):
            continue
        user = await db.scalar(
            select(User.id).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            )
        )
        add(user)
    return resolved


# ---------------------------------------------------------------- actions log


async def record_action(
    db: AsyncSession,
    instance: ApprovalInstance,
    action: str,
    *,
    actor_id: int | None = None,
    node_key: str | None = None,
    task_id: int | None = None,
    target_user_id: int | None = None,
    comment: str = "",
    detail: dict | None = None,
) -> ApprovalAction:
    row = ApprovalAction(
        tenant_id=instance.tenant_id,
        instance_id=instance.id,
        node_key=node_key,
        task_id=task_id,
        action=action,
        actor_id=actor_id,
        target_user_id=target_user_id,
        comment=comment,
        detail=detail or {},
    )
    db.add(row)
    await db.flush()
    return row


async def notify_users(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_ids: list[int],
    instance: ApprovalInstance,
    title: str,
    content: str,
    level: str = "info",
    task_id: int | None = None,
) -> None:
    for user_id in dict.fromkeys(user_ids):
        if not user_id:
            continue
        db.add(
            ApprovalNotification(
                tenant_id=tenant_id,
                user_id=user_id,
                instance_id=instance.id,
                task_id=task_id,
                title=title[:255],
                content=content,
                level=level,
            )
        )
    await db.flush()


# ---------------------------------------------------------------- conditions


def _get_path(data, path: str):
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _as_number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(node: dict, data: dict) -> bool:
    value = _get_path(data, node.get("field") or "")
    target = node.get("value")
    operator = node.get("operator") or "eq"

    if operator == "exists":
        return value not in (None, "", [], {})
    if value is None:
        return False
    if operator == "in":
        if isinstance(target, list):
            return any(str(value) == str(item) for item in target)
        return False
    if operator == "not_in":
        if isinstance(target, list):
            return all(str(value) != str(item) for item in target)
        return True
    if operator == "contains":
        if isinstance(value, list):
            return target in value
        return str(target) in str(value)

    left_number, right_number = _as_number(value), _as_number(target)
    if operator in {"gt", "gte", "lt", "lte"}:
        if left_number is None or right_number is None:
            return False
        if operator == "gt":
            return left_number > right_number
        if operator == "gte":
            return left_number >= right_number
        if operator == "lt":
            return left_number < right_number
        return left_number <= right_number
    if operator == "eq":
        if left_number is not None and right_number is not None:
            return left_number == right_number
        return str(value) == str(target)
    if operator == "ne":
        if left_number is not None and right_number is not None:
            return left_number != right_number
        return str(value) != str(target)
    return False


# ---------------------------------------------------------------- task helpers


def _node_map(instance: ApprovalInstance) -> dict[str, dict]:
    nodes = (instance.flow_snapshot or {}).get("nodes") or []
    return {node["key"]: node for node in nodes if isinstance(node, dict) and node.get("key")}


def _node_index(instance: ApprovalInstance) -> dict[str, int]:
    nodes = (instance.flow_snapshot or {}).get("nodes") or []
    return {node["key"]: index for index, node in enumerate(nodes)}


def _state_map(instance: ApprovalInstance) -> dict:
    """确保拿到的是实例自身的 dict；空 JSON 的 falsy 值不能走 ``or {}``。"""
    if not isinstance(instance.node_states, dict):
        instance.node_states = {}
    return instance.node_states


def _touch_node_states(instance: ApprovalInstance) -> None:
    """JSON 列默认不跟踪嵌套修改；重新赋值触发 SQLAlchemy 持久化。"""
    instance.node_states = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in _state_map(instance).items()
    }
    flag_modified(instance, "node_states")


async def _node_tasks(
    db: AsyncSession, instance_id: int, node_key: str
) -> list[ApprovalTask]:
    return list(
        (
            await db.scalars(
                select(ApprovalTask).where(
                    ApprovalTask.instance_id == instance_id,
                    ApprovalTask.node_key == node_key,
                )
            )
        ).all()
    )


async def _start_approval_node(
    db: AsyncSession,
    instance: ApprovalInstance,
    node: dict,
    state: dict,
) -> None:
    approvers = await resolve_approvers(
        db, instance.tenant_id, node.get("approvers"), instance.initiator_id
    )
    if not approvers:
        raise ApprovalEngineError(f"节点「{node['name']}」没有可用审批人")

    mode = node.get("mode") or "any"
    timeout_hours = int(node.get("timeout_hours") or 0)
    due_at = utcnow() + timedelta(hours=timeout_hours) if timeout_hours else None
    tasks: list[ApprovalTask] = []
    for order, approver_id in enumerate(approvers):
        status = "pending" if mode != "sequence" or order == 0 else "waiting"
        task = ApprovalTask(
            tenant_id=instance.tenant_id,
            instance_id=instance.id,
            node_key=node["key"],
            node_name=node["name"],
            approver_id=approver_id,
            mode=mode,
            sequence_order=order,
            status=status,
            due_at=due_at if status == "pending" else None,
        )
        db.add(task)
        tasks.append(task)
    await db.flush()

    state.update(
        {
            "status": "pending",
            "mode": mode,
            "approvers": approvers,
            "timeout_hours": timeout_hours,
            "timeout_action": node.get("timeout_action") or "remind",
            "started_at": utcnow().isoformat(),
        }
    )
    _touch_node_states(instance)
    instance.current_node_key = node["key"]
    instance.current_node_name = node["name"]
    instance.due_at = due_at

    for task in tasks:
        if task.status != "pending":
            continue
        await notify_users(
            db,
            tenant_id=instance.tenant_id,
            user_ids=[task.approver_id],
            instance=instance,
            title=f"待审批：{instance.title}",
            content=f"流程节点「{node['name']}」等待你处理。",
            level="warning",
            task_id=task.id,
        )
    await record_action(
        db,
        instance,
        "node_enter",
        node_key=node["key"],
        detail={"approvers": approvers, "mode": mode},
    )


async def _activate_next_sequence_task(
    db: AsyncSession, instance: ApprovalInstance, node: dict, current_task: ApprovalTask
) -> bool:
    tasks = await _node_tasks(db, instance.id, node["key"])
    waiting = sorted(
        (task for task in tasks if task.status == "waiting"), key=lambda task: task.sequence_order
    )
    if not waiting:
        return False
    next_task = waiting[0]
    next_task.status = "pending"
    timeout_hours = int(node.get("timeout_hours") or 0)
    next_task.due_at = utcnow() + timedelta(hours=timeout_hours) if timeout_hours else None
    instance.due_at = next_task.due_at
    await notify_users(
        db,
        tenant_id=instance.tenant_id,
        user_ids=[next_task.approver_id],
        instance=instance,
        title=f"待审批：{instance.title}",
        content=f"流程节点「{node['name']}」已轮到你了。",
        level="warning",
        task_id=next_task.id,
    )
    return True


async def _complete_node(db: AsyncSession, instance: ApprovalInstance, node: dict) -> None:
    state = _state_map(instance).setdefault(node["key"], {})
    state["status"] = "approved"
    state["finished_at"] = utcnow().isoformat()
    _touch_node_states(instance)
    await advance_instance(db, instance)


# ---------------------------------------------------------------- engine


async def advance_instance(
    db: AsyncSession, instance: ApprovalInstance, start_index: int | None = None
) -> None:
    """从当前节点之后继续推进，直到等待审批人或流程结束。"""
    nodes = (instance.flow_snapshot or {}).get("nodes") or []
    index_by_key = _node_index(instance)
    if start_index is None:
        current = instance.current_node_key
        start_index = index_by_key.get(current, -1) + 1 if current else 0

    visited: set[str] = set()
    index = start_index
    while 0 <= index < len(nodes):
        node = nodes[index]
        key = node["key"]
        if key in visited:
            raise ApprovalEngineError("流程条件跳转形成了环")
        visited.add(key)
        state = _state_map(instance).setdefault(key, {})
        state.setdefault("status", "pending")
        instance.current_node_key = key
        instance.current_node_name = node["name"]

        node_type = node["type"]
        if node_type == "condition":
            matched = evaluate_condition(node, instance.form_data or {})
            target = node.get("on_true") if matched else node.get("on_false")
            state.update(
                {
                    "status": "skipped",
                    "result": matched,
                    "target": target,
                    "finished_at": utcnow().isoformat(),
                }
            )
            _touch_node_states(instance)
            if target:
                if target not in index_by_key:
                    raise ApprovalEngineError(f"条件跳转目标不存在: {target}")
                index = index_by_key[target]
                continue
            index += 1
            continue

        if node_type == "cc":
            cc_users = await resolve_approvers(
                db, instance.tenant_id, node.get("cc"), instance.initiator_id
            )
            await notify_users(
                db,
                tenant_id=instance.tenant_id,
                user_ids=cc_users,
                instance=instance,
                title=f"抄送：{instance.title}",
                content=f"流程节点「{node['name']}」抄送给你知悉。",
            )
            state.update(
                {"status": "skipped", "finished_at": utcnow().isoformat(), "cc": cc_users}
            )
            _touch_node_states(instance)
            index += 1
            continue

        if node_type == "end":
            state.update({"status": "approved", "finished_at": utcnow().isoformat()})
            _touch_node_states(instance)
            await complete_instance(db, instance, "approved")
            return

        if node_type == "approval":
            await _start_approval_node(db, instance, node, state)
            return

        raise ApprovalEngineError(f"不支持的节点类型: {node_type}")

    await complete_instance(db, instance, "approved")


def _format_title(template: str, instance: ApprovalInstance) -> str:
    values = {"title": instance.title, **{k: v for k, v in (instance.form_data or {}).items()}}
    try:
        return template.format(**values)[:255]
    except (KeyError, ValueError, IndexError):
        return f"审批通过：{instance.title}"[:255]


async def launch_employee_task(
    db: AsyncSession,
    instance: ApprovalInstance,
    employee_id: int | None = None,
    actor_id: int | None = None,
) -> int | None:
    """审批通过后创建数字员工任务（自由任务），进入现有任务队列。"""
    if instance.status != "approved":
        raise BadRequestError("只有审批通过的实例才能创建任务")
    if instance.task_instance_id:
        return instance.task_instance_id

    config = (instance.flow_snapshot or {}).get("config") or {}
    target_employee_id = employee_id or instance.employee_id or config.get("employee_id")
    if not target_employee_id:
        return None

    employee = await db.get(DigitalEmployee, int(target_employee_id))
    if employee is None or employee.tenant_id != instance.tenant_id:
        raise NotFoundError("数字员工不存在")

    title = _format_title(
        str(config.get("title_template") or "审批通过：{title}"), instance
    )
    task = TaskInstance(
        tenant_id=instance.tenant_id,
        definition_id=None,
        employee_id=employee.id,
        title=title,
        task_type=str(config.get("task_type") or "free"),
        status="pending",
        input={
            "approval_instance_id": instance.id,
            "approval_title": instance.title,
            "form_data": instance.form_data,
            "flow_name": (instance.flow_snapshot or {}).get("name"),
            "request": (
                f"审批已通过：{instance.title}。"
                f"表单数据：{json.dumps(instance.form_data, ensure_ascii=False)}"
            ),
        },
        output={},
        next_step_index=0,
        attempt=0,
        max_attempts=settings.task_max_attempts,
        priority=instance.priority,
        trace_id=uuid4().hex,
        created_by=actor_id or instance.initiator_id,
    )
    db.add(task)
    await db.flush()

    instance.task_instance_id = task.id
    instance.result = {**(instance.result or {}), "task_instance_id": task.id}
    await record_action(
        db,
        instance,
        "launch_task",
        actor_id=actor_id,
        detail={"task_instance_id": task.id, "employee_id": employee.id},
    )
    return task.id


async def complete_instance(
    db: AsyncSession,
    instance: ApprovalInstance,
    status: str,
    *,
    actor_id: int | None = None,
    reason: str = "",
) -> None:
    if instance.status != "running":
        return
    instance.status = status
    instance.completed_at = utcnow()
    instance.due_at = None
    instance.current_node_key = None
    instance.current_node_name = "已结束"
    state = _state_map(instance).setdefault("__end__", {})
    state.update({"status": status, "finished_at": utcnow().isoformat()})
    _touch_node_states(instance)

    tasks = list(
        (
            await db.scalars(
                select(ApprovalTask).where(ApprovalTask.instance_id == instance.id)
            )
        ).all()
    )
    for task in tasks:
        if task.status in ("pending", "waiting"):
            task.status = "cancelled"

    await record_action(
        db,
        instance,
        "complete",
        actor_id=actor_id,
        comment=reason,
        detail={"status": status},
    )
    labels = {"approved": "审批通过", "rejected": "审批驳回", "cancelled": "审批取消"}
    level = {"approved": "success", "rejected": "warning", "cancelled": "info"}.get(
        status, "info"
    )
    await notify_users(
        db,
        tenant_id=instance.tenant_id,
        user_ids=[instance.initiator_id],
        instance=instance,
        title=f"{labels.get(status, '审批结束')}：{instance.title}",
        content=reason or f"流程已{labels.get(status, '结束')}。",
        level=level,
    )

    config = (instance.flow_snapshot or {}).get("config") or {}
    should_launch = instance.employee_id or config.get("auto_launch_task")
    if status == "approved" and should_launch:
        try:
            await launch_employee_task(db, instance, actor_id=actor_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("审批 %s 通过后创建数字员工任务失败", instance.id)
            instance.error = f"创建数字员工任务失败: {exc}"


async def start_approval(
    db: AsyncSession,
    *,
    tenant_id: int,
    initiator_id: int,
    flow: ApprovalFlow,
    title: str,
    form_data: dict | None = None,
    employee_id: int | None = None,
    task_instance_id: int | None = None,
    business_ref: str | None = None,
    priority: int = 100,
) -> ApprovalInstance:
    if not flow.enabled:
        raise BadRequestError("审批流程已停用")
    form: ApprovalForm | None = None
    if flow.form_id:
        form = await get_form(db, tenant_id, flow.form_id)
        if not form.enabled:
            raise BadRequestError("审批表单已停用")

    nodes = normalize_nodes(flow.nodes)
    if form is not None:
        fields = normalize_fields(form.fields)
        clean_data = validate_form_data(fields, form_data)
        await _validate_user_values(db, tenant_id, fields, clean_data)
    else:
        fields = []
        clean_data = dict(form_data or {})

    if employee_id is not None:
        employee = await db.get(DigitalEmployee, int(employee_id))
        if employee is None or employee.tenant_id != tenant_id:
            raise NotFoundError("数字员工不存在")
    if task_instance_id is not None:
        task = await db.get(TaskInstance, int(task_instance_id))
        if task is None or task.tenant_id != tenant_id:
            raise NotFoundError("关联任务不存在")

    for node in nodes:
        if node["type"] != "approval":
            continue
        approvers = await resolve_approvers(db, tenant_id, node["approvers"], initiator_id)
        if not approvers:
            raise BadRequestError(f"节点「{node['name']}」没有可用审批人")

    instance = ApprovalInstance(
        tenant_id=tenant_id,
        flow_id=flow.id,
        form_id=form.id if form else None,
        title=title.strip()[:255],
        category=flow.category,
        status="running",
        form_data=clean_data,
        form_snapshot={
            "id": form.id if form else None,
            "name": form.name if form else "无表单",
            "code": form.code if form else None,
            "fields": fields,
        },
        flow_snapshot={
            "id": flow.id,
            "name": flow.name,
            "code": flow.code,
            "category": flow.category,
            "version": flow.version,
            "nodes": nodes,
            "config": dict(flow.config or {}),
        },
        node_states={},
        initiator_id=initiator_id,
        employee_id=employee_id,
        task_instance_id=task_instance_id,
        business_ref=business_ref,
        priority=priority,
    )
    db.add(instance)
    await db.flush()
    await record_action(
        db,
        instance,
        "submit",
        actor_id=initiator_id,
        comment="提交审批",
        detail={"flow_code": flow.code, "title": instance.title},
    )
    await advance_instance(db, instance)
    return instance


# ---------------------------------------------------------------- decisions


async def _load_task(db: AsyncSession, tenant_id: int, task_id: int) -> ApprovalTask:
    task = await db.scalar(
        select(ApprovalTask).where(
            ApprovalTask.id == task_id, ApprovalTask.tenant_id == tenant_id
        )
    )
    if task is None:
        raise NotFoundError("审批任务不存在")
    return task


def _ensure_task_action_allowed(
    task: ApprovalTask, instance: ApprovalInstance, user_id: int, source: str
) -> None:
    if source == "user" and task.approver_id != user_id:
        raise ForbiddenError("这不是你的审批任务")
    if task.status != "pending":
        raise BadRequestError("该审批任务已处理")
    if instance.status != "running":
        raise BadRequestError("审批流程已结束")


async def _reset_instance_due(db: AsyncSession, instance: ApprovalInstance) -> None:
    rows = await db.scalars(
        select(ApprovalTask.due_at).where(
            ApprovalTask.instance_id == instance.id,
            ApprovalTask.status == "pending",
            ApprovalTask.due_at.is_not(None),
        )
    )
    due_dates = [row for row in rows if row is not None]
    instance.due_at = min(due_dates) if due_dates else None


async def approve_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    comment: str = "",
    *,
    source: str = "user",
) -> ApprovalTask:
    task = await _load_task_any(db, task_id)
    instance = await get_instance(db, task.tenant_id, task.instance_id)
    _ensure_task_action_allowed(task, instance, user_id, source)

    node = _node_map(instance).get(task.node_key)
    if node is None:
        raise ApprovalEngineError(f"节点不存在: {task.node_key}")

    task.status = "approved"
    task.comment = comment
    task.acted_at = utcnow()
    task.acted_by = None if source != "user" else user_id
    task.action_source = source
    action_name = "timeout_approve" if source == "timeout" else "approve"
    await record_action(
        db,
        instance,
        action_name,
        actor_id=None if source != "user" else user_id,
        node_key=task.node_key,
        task_id=task.id,
        comment=comment,
    )

    mode = task.mode
    if mode == "any":
        tasks = await _node_tasks(db, instance.id, task.node_key)
        for item in tasks:
            if item.id != task.id and item.status in ("pending", "waiting"):
                item.status = "cancelled"
        await _complete_node(db, instance, node)
    elif mode == "sequence":
        if not await _activate_next_sequence_task(db, instance, node, task):
            await _complete_node(db, instance, node)
        else:
            await _reset_instance_due(db, instance)
    else:  # all 会签
        tasks = await _node_tasks(db, instance.id, task.node_key)
        if all(item.status == "approved" for item in tasks if item.status != "cancelled"):
            await _complete_node(db, instance, node)
        else:
            await _reset_instance_due(db, instance)

    await db.flush()
    return task


async def _load_task_any(db: AsyncSession, task_id: int) -> ApprovalTask:
    task = await db.get(ApprovalTask, task_id)
    if task is None:
        raise NotFoundError("审批任务不存在")
    return task


async def reject_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    comment: str = "",
    *,
    source: str = "user",
) -> ApprovalTask:
    task = await _load_task_any(db, task_id)
    instance = await get_instance(db, task.tenant_id, task.instance_id)
    _ensure_task_action_allowed(task, instance, user_id, source)

    task.status = "rejected"
    task.comment = comment
    task.acted_at = utcnow()
    task.acted_by = None if source != "user" else user_id
    task.action_source = source
    action_name = "timeout_reject" if source == "timeout" else "reject"
    await record_action(
        db,
        instance,
        action_name,
        actor_id=None if source != "user" else user_id,
        node_key=task.node_key,
        task_id=task.id,
        comment=comment,
    )
    state = _state_map(instance).setdefault(task.node_key, {})
    state.update({"status": "rejected", "finished_at": utcnow().isoformat()})
    _touch_node_states(instance)
    reason = f"节点「{task.node_name}」被驳回"
    if comment:
        reason = f"{reason}：{comment}"
    await complete_instance(
        db,
        instance,
        "rejected",
        actor_id=None if source != "user" else user_id,
        reason=reason,
    )
    await db.flush()
    return task


async def transfer_task(
    db: AsyncSession,
    task_id: int,
    actor_id: int,
    target_user_id: int,
    comment: str = "",
    *,
    source: str = "user",
) -> ApprovalTask:
    task = await _load_task_any(db, task_id)
    instance = await get_instance(db, task.tenant_id, task.instance_id)
    _ensure_task_action_allowed(task, instance, actor_id, source)

    target = await db.scalar(
        select(User).where(
            User.id == target_user_id,
            User.tenant_id == task.tenant_id,
            User.is_active.is_(True),
        )
    )
    if target is None:
        raise NotFoundError("转办目标用户不存在或已停用")
    if target.id == task.approver_id:
        raise BadRequestError("不能转办给当前审批人")

    previous = task.approver_id
    task.approver_id = target.id
    task.delegated_from = task.delegated_from or previous
    await record_action(
        db,
        instance,
        "transfer",
        actor_id=None if source != "user" else actor_id,
        node_key=task.node_key,
        task_id=task.id,
        target_user_id=target.id,
        comment=comment,
        detail={"from": previous, "to": target.id},
    )
    await notify_users(
        db,
        tenant_id=instance.tenant_id,
        user_ids=[target.id],
        instance=instance,
        title=f"转办待审批：{instance.title}",
        content=f"节点「{task.node_name}」已转办给你。",
        level="warning",
        task_id=task.id,
    )
    await db.flush()
    return task


async def add_sign(
    db: AsyncSession,
    task_id: int,
    actor_id: int,
    user_ids: list[int],
    comment: str = "",
) -> list[ApprovalTask]:
    task = await _load_task_any(db, task_id)
    instance = await get_instance(db, task.tenant_id, task.instance_id)
    if instance.status != "running":
        raise BadRequestError("审批流程已结束")

    node = _node_map(instance).get(task.node_key)
    if node is None:
        raise ApprovalEngineError(f"节点不存在: {task.node_key}")
    if node.get("type") != "approval":
        raise BadRequestError("只有审批节点可以加签")
    if not node.get("allow_add_sign", True):
        raise BadRequestError("该节点不允许加签")

    existing = await _node_tasks(db, instance.id, task.node_key)
    actor_task = next(
        (
            item
            for item in existing
            if item.approver_id == actor_id
            and item.status in ("pending", "approved")
        ),
        None,
    )
    actor_is_admin = await db.scalar(
        select(User.is_superuser).where(User.id == actor_id)
    )
    if actor_task is None and not actor_is_admin:
        raise ForbiddenError("只有当前节点审批人可以加签")

    existing_users = {item.approver_id for item in existing}
    targets = list(
        (
            await db.scalars(
                select(User).where(
                    User.id.in_(user_ids),
                    User.tenant_id == instance.tenant_id,
                    User.is_active.is_(True),
                )
            )
        ).all()
    )
    target_ids = [user.id for user in targets if user.id not in existing_users]
    if not target_ids:
        raise BadRequestError("加签用户不存在、已停用或已在当前节点")

    mode = node.get("mode") or "any"
    max_order = max((item.sequence_order for item in existing), default=-1)
    has_pending = any(item.status == "pending" for item in existing)
    added: list[ApprovalTask] = []
    timeout_hours = int(node.get("timeout_hours") or 0)
    for offset, target_id in enumerate(target_ids, start=1):
        status = "waiting" if mode == "sequence" and has_pending else "pending"
        new_task = ApprovalTask(
            tenant_id=instance.tenant_id,
            instance_id=instance.id,
            node_key=task.node_key,
            node_name=task.node_name,
            approver_id=target_id,
            mode=mode,
            sequence_order=max_order + offset,
            status=status,
            is_added=True,
            added_by=actor_id,
            due_at=utcnow() + timedelta(hours=timeout_hours) if timeout_hours else None,
        )
        db.add(new_task)
        added.append(new_task)
    await db.flush()

    await record_action(
        db,
        instance,
        "add_sign",
        actor_id=actor_id,
        node_key=task.node_key,
        task_id=task.id,
        comment=comment,
        detail={"user_ids": target_ids, "is_added": True},
    )
    for new_task in added:
        if new_task.status == "pending":
            await notify_users(
                db,
                tenant_id=instance.tenant_id,
                user_ids=[new_task.approver_id],
                instance=instance,
                title=f"待审批（加签）：{instance.title}",
                content=f"节点「{new_task.node_name}」加签给你处理。",
                level="warning",
                task_id=new_task.id,
            )
    await _reset_instance_due(db, instance)
    await db.flush()
    return added


async def remind_instance(
    db: AsyncSession,
    instance_id: int,
    actor_id: int,
    comment: str = "",
) -> int:
    instance = await _load_instance_any(db, instance_id)
    if instance.status != "running":
        raise BadRequestError("审批流程已结束")
    tasks = list(
        (
            await db.scalars(
                select(ApprovalTask).where(
                    ApprovalTask.instance_id == instance.id,
                    ApprovalTask.status == "pending",
                )
            )
        ).all()
    )
    if not tasks:
        raise BadRequestError("当前没有待处理的审批人")
    await notify_users(
        db,
        tenant_id=instance.tenant_id,
        user_ids=[task.approver_id for task in tasks],
        instance=instance,
        title=f"审批催办：{instance.title}",
        content=comment or "发起人催办了该审批，请尽快处理。",
        level="warning",
    )
    instance.last_reminded_at = utcnow()
    await record_action(
        db,
        instance,
        "remind",
        actor_id=actor_id,
        comment=comment,
        detail={"task_ids": [task.id for task in tasks]},
    )
    await db.flush()
    return len(tasks)


async def _load_instance_any(db: AsyncSession, instance_id: int) -> ApprovalInstance:
    instance = await db.get(ApprovalInstance, instance_id)
    if instance is None:
        raise NotFoundError("审批实例不存在")
    return instance


async def cancel_instance(
    db: AsyncSession,
    instance_id: int,
    actor_id: int,
    comment: str = "",
) -> ApprovalInstance:
    instance = await _load_instance_any(db, instance_id)
    if instance.status != "running":
        raise BadRequestError("审批流程已结束")
    await record_action(
        db,
        instance,
        "cancel",
        actor_id=actor_id,
        comment=comment,
    )
    await complete_instance(
        db, instance, "cancelled", actor_id=actor_id, reason=comment or "发起人取消审批"
    )
    await db.flush()
    return instance


# ---------------------------------------------------------------- timeout scan


async def scan_timeouts(db: AsyncSession, batch: int = 100) -> int:
    now = utcnow()
    tasks = list(
        (
            await db.scalars(
                select(ApprovalTask)
                .where(
                    ApprovalTask.status == "pending",
                    ApprovalTask.due_at.is_not(None),
                    ApprovalTask.due_at <= now,
                )
                .order_by(ApprovalTask.due_at.asc())
                .limit(batch)
            )
        ).all()
    )
    processed = 0
    for task in tasks:
        instance = await db.get(ApprovalInstance, task.instance_id)
        if instance is None or instance.status != "running":
            continue
        node = _node_map(instance).get(task.node_key)
        if node is None:
            continue
        action = node.get("timeout_action") or "remind"
        timeout_hours = int(node.get("timeout_hours") or 0)

        if action == "remind":
            if task.reminded_at is not None:
                continue
            await notify_users(
                db,
                tenant_id=instance.tenant_id,
                user_ids=[task.approver_id],
                instance=instance,
                title=f"审批超时提醒：{instance.title}",
                content=f"节点「{task.node_name}」已超过 {timeout_hours} 小时未处理。",
                level="warning",
                task_id=task.id,
            )
            task.reminded_at = now
            if timeout_hours:
                task.due_at = now + timedelta(hours=timeout_hours)
            else:
                task.due_at = None
            await record_action(
                db,
                instance,
                "timeout_remind",
                node_key=task.node_key,
                task_id=task.id,
                detail={"approver_id": task.approver_id},
            )
            processed += 1
        elif action == "auto_approve":
            await approve_task(db, task.id, 0, "超时自动通过", source="timeout")
            processed += 1
        elif action == "auto_reject":
            await reject_task(db, task.id, 0, "超时自动驳回", source="timeout")
            processed += 1
        elif action == "escalate":
            targets = await resolve_approvers(
                db,
                instance.tenant_id,
                node.get("escalate_to"),
                instance.initiator_id,
            )
            target_id = next((item for item in targets if item != task.approver_id), None)
            if target_id:
                await transfer_task(
                    db,
                    task.id,
                    0,
                    target_id,
                    "超时升级转办",
                    source="timeout",
                )
                await record_action(
                    db,
                    instance,
                    "timeout_escalate",
                    node_key=task.node_key,
                    task_id=task.id,
                    target_user_id=target_id,
                )
                processed += 1
        await db.flush()
    return processed
