from fastapi import APIRouter, Query, Request
from sqlalchemy import exists, func, or_, select

from app.core.base import utcnow
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.identity.models import User
from app.domains.workflows.approvals.models import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalForm,
    ApprovalInstance,
    ApprovalNotification,
    ApprovalTask,
)
from app.domains.workflows.approvals.schemas import (
    ActionOut,
    AddSignRequest,
    DecisionRequest,
    FlowCreate,
    FlowOut,
    FlowUpdate,
    FormCreate,
    FormOut,
    FormUpdate,
    InstanceCreate,
    InstanceOut,
    LaunchTaskRequest,
    NotificationOut,
    TaskOut,
    TransferRequest,
    UserBrief,
)
from app.domains.workflows.approvals.service import (
    add_sign,
    approve_task,
    cancel_instance,
    get_flow,
    get_form,
    get_instance,
    launch_employee_task,
    normalize_fields,
    normalize_nodes,
    reject_task,
    remind_instance,
    start_approval,
    transfer_task,
)

router = APIRouter(prefix="/approvals", tags=["审批流"])


# ---------------------------------------------------------------- helpers


async def _get_task(db: DbSession, tenant_id: int, task_id: int) -> ApprovalTask:
    task = await db.scalar(
        select(ApprovalTask).where(
            ApprovalTask.id == task_id, ApprovalTask.tenant_id == tenant_id
        )
    )
    if task is None:
        raise NotFoundError("审批任务不存在")
    return task


async def _get_notification(
    db: DbSession, tenant_id: int, user_id: int, notification_id: int
) -> ApprovalNotification:
    row = await db.scalar(
        select(ApprovalNotification).where(
            ApprovalNotification.id == notification_id,
            ApprovalNotification.tenant_id == tenant_id,
            ApprovalNotification.user_id == user_id,
        )
    )
    if row is None:
        raise NotFoundError("通知不存在")
    return row


async def _can_view_instance(
    db: DbSession, instance: ApprovalInstance, user: User
) -> bool:
    if user.is_superuser or instance.initiator_id == user.id:
        return True
    task = await db.scalar(
        select(ApprovalTask.id).where(
            ApprovalTask.instance_id == instance.id,
            ApprovalTask.approver_id == user.id,
        )
    )
    return task is not None


def _progress(instance: ApprovalInstance) -> dict:
    nodes = (instance.flow_snapshot or {}).get("nodes") or []
    states = instance.node_states or {}
    total = len(nodes)
    completed = sum(
        1
        for node in nodes
        if (states.get(node.get("key")) or {}).get("status")
        in ("approved", "skipped", "rejected", "cancelled")
    )
    if instance.status != "running":
        completed = total
    return {
        "total": total,
        "completed": completed,
        "percent": round(completed / total * 100) if total else 0,
        "current": instance.current_node_name,
    }


def _task_dict(task: ApprovalTask) -> dict:
    return TaskOut.model_validate(task).model_dump(mode="json")


def _action_dict(action: ApprovalAction) -> dict:
    return ActionOut.model_validate(action).model_dump(mode="json")


def _instance_dict(
    instance: ApprovalInstance,
    *,
    flow_name: str | None = None,
    form_name: str | None = None,
    initiator_name: str | None = None,
    tasks: list[ApprovalTask] | None = None,
    actions: list[ApprovalAction] | None = None,
    my_tasks: list[ApprovalTask] | None = None,
) -> dict:
    data = InstanceOut.model_validate(instance).model_dump(mode="json")
    data["flow_name"] = flow_name or (instance.flow_snapshot or {}).get("name")
    data["form_name"] = form_name or (instance.form_snapshot or {}).get("name")
    data["initiator_name"] = initiator_name
    data["progress"] = _progress(instance)
    data["tasks"] = [_task_dict(task) for task in tasks or []]
    data["actions"] = [_action_dict(action) for action in actions or []]
    data["my_tasks"] = [_task_dict(task) for task in my_tasks or []]
    return data


async def _name_maps(
    db: DbSession, tenant_id: int, instances: list[ApprovalInstance]
) -> tuple[dict, dict, dict]:
    flow_ids = {item.flow_id for item in instances if item.flow_id}
    form_ids = {item.form_id for item in instances if item.form_id}
    user_ids = {item.initiator_id for item in instances if item.initiator_id}
    flows: dict[int, str] = {}
    forms: dict[int, str] = {}
    users: dict[int, str] = {}
    if flow_ids:
        rows = await db.scalars(
            select(ApprovalFlow).where(
                ApprovalFlow.tenant_id == tenant_id,
                ApprovalFlow.id.in_(flow_ids),
            )
        )
        flows = {row.id: row.name for row in rows}
    if form_ids:
        rows = await db.scalars(
            select(ApprovalForm).where(
                ApprovalForm.tenant_id == tenant_id,
                ApprovalForm.id.in_(form_ids),
            )
        )
        forms = {row.id: row.name for row in rows}
    if user_ids:
        rows = await db.scalars(
            select(User).where(User.tenant_id == tenant_id, User.id.in_(user_ids))
        )
        users = {row.id: row.full_name or row.username for row in rows}
    return flows, forms, users


# ---------------------------------------------------------------- users


@router.get("/users", summary="可选审批人列表")
async def list_users(db: DbSession, current_user: CurrentUser):
    rows = list(
        (
            await db.scalars(
                select(User)
                .where(
                    User.tenant_id == current_user.tenant_id,
                    User.is_active.is_(True),
                )
                .order_by(User.id.asc())
            )
        ).all()
    )
    return success(
        [UserBrief.model_validate(row).model_dump(mode="json") for row in rows]
    )


# ---------------------------------------------------------------- forms


@router.get("/forms", summary="审批表单列表")
async def list_forms(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    enabled: bool | None = None,
    q: str | None = None,
):
    conditions = [ApprovalForm.tenant_id == current_user.tenant_id]
    if category:
        conditions.append(ApprovalForm.category == category)
    if enabled is not None:
        conditions.append(ApprovalForm.enabled.is_(enabled))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            ApprovalForm.name.ilike(like) | ApprovalForm.code.ilike(like)
        )
    stmt = select(ApprovalForm).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ApprovalForm.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [FormOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/forms", summary="创建审批表单")
async def create_form(
    payload: FormCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    duplicate = await db.scalar(
        select(ApprovalForm.id).where(
            ApprovalForm.tenant_id == current_user.tenant_id,
            ApprovalForm.code == payload.code,
        )
    )
    if duplicate:
        raise ConflictError("表单编码已存在")
    fields = normalize_fields(payload.fields)
    form = ApprovalForm(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(exclude={"fields"}),
        fields=fields,
    )
    db.add(form)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.form.create",
        resource_type="approval_form",
        resource_id=form.id,
        detail={"name": form.name, "code": form.code, "fields": len(fields)},
        ip_address=client_ip(request),
    )
    return success(FormOut.model_validate(form).model_dump(mode="json"))


@router.patch("/forms/{form_id}", summary="更新审批表单")
async def update_form(
    form_id: int,
    payload: FormUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    form = await get_form(db, current_user.tenant_id, form_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != form.code:
        duplicate = await db.scalar(
            select(ApprovalForm.id).where(
                ApprovalForm.tenant_id == current_user.tenant_id,
                ApprovalForm.code == changes["code"],
                ApprovalForm.id != form.id,
            )
        )
        if duplicate:
            raise ConflictError("表单编码已存在")
    if "fields" in changes:
        changes["fields"] = normalize_fields(changes["fields"])
    for field, value in changes.items():
        setattr(form, field, value)
    form.version = (form.version or 1) + 1
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.form.update",
        resource_type="approval_form",
        resource_id=form.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(FormOut.model_validate(form).model_dump(mode="json"))


@router.delete("/forms/{form_id}", summary="删除审批表单")
async def delete_form(
    form_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    form = await get_form(db, current_user.tenant_id, form_id)
    used_flows = await db.scalar(
        select(func.count())
        .select_from(ApprovalFlow)
        .where(ApprovalFlow.form_id == form.id)
    )
    used_instances = await db.scalar(
        select(func.count())
        .select_from(ApprovalInstance)
        .where(ApprovalInstance.form_id == form.id)
    )
    if used_flows or used_instances:
        raise ConflictError("表单已被流程或审批实例使用，不能删除")
    await db.delete(form)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.form.delete",
        resource_type="approval_form",
        resource_id=form_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


# ---------------------------------------------------------------- flows


@router.get("/flows", summary="审批流程列表")
async def list_flows(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    enabled: bool | None = None,
    q: str | None = None,
):
    conditions = [ApprovalFlow.tenant_id == current_user.tenant_id]
    if category:
        conditions.append(ApprovalFlow.category == category)
    if enabled is not None:
        conditions.append(ApprovalFlow.enabled.is_(enabled))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(ApprovalFlow.name.ilike(like) | ApprovalFlow.code.ilike(like))
    stmt = select(ApprovalFlow).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ApprovalFlow.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    form_ids = {item.form_id for item in items if item.form_id}
    form_names: dict[int, str] = {}
    if form_ids:
        rows = await db.scalars(
            select(ApprovalForm).where(
                ApprovalForm.tenant_id == current_user.tenant_id,
                ApprovalForm.id.in_(form_ids),
            )
        )
        form_names = {row.id: row.name for row in rows}
    payload = []
    for item in items:
        data = FlowOut.model_validate(item).model_dump(mode="json")
        data["form_name"] = form_names.get(item.form_id)
        payload.append(data)
    return paged(payload, total, page, page_size)


@router.post("/flows", summary="创建审批流程")
async def create_flow(
    payload: FlowCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    duplicate = await db.scalar(
        select(ApprovalFlow.id).where(
            ApprovalFlow.tenant_id == current_user.tenant_id,
            ApprovalFlow.code == payload.code,
        )
    )
    if duplicate:
        raise ConflictError("流程编码已存在")
    if payload.form_id is not None:
        await get_form(db, current_user.tenant_id, payload.form_id)
    nodes = normalize_nodes(payload.nodes)
    flow = ApprovalFlow(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(exclude={"nodes"}),
        nodes=nodes,
    )
    db.add(flow)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.flow.create",
        resource_type="approval_flow",
        resource_id=flow.id,
        detail={"name": flow.name, "code": flow.code, "nodes": len(nodes)},
        ip_address=client_ip(request),
    )
    return success(FlowOut.model_validate(flow).model_dump(mode="json"))


@router.patch("/flows/{flow_id}", summary="更新审批流程")
async def update_flow(
    flow_id: int,
    payload: FlowUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    flow = await get_flow(db, current_user.tenant_id, flow_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != flow.code:
        duplicate = await db.scalar(
            select(ApprovalFlow.id).where(
                ApprovalFlow.tenant_id == current_user.tenant_id,
                ApprovalFlow.code == changes["code"],
                ApprovalFlow.id != flow.id,
            )
        )
        if duplicate:
            raise ConflictError("流程编码已存在")
    if changes.get("form_id") is not None:
        await get_form(db, current_user.tenant_id, changes["form_id"])
    if "nodes" in changes:
        changes["nodes"] = normalize_nodes(changes["nodes"])
    for field, value in changes.items():
        setattr(flow, field, value)
    flow.version = (flow.version or 1) + 1
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.flow.update",
        resource_type="approval_flow",
        resource_id=flow.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(FlowOut.model_validate(flow).model_dump(mode="json"))


@router.delete("/flows/{flow_id}", summary="删除审批流程")
async def delete_flow(
    flow_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    flow = await get_flow(db, current_user.tenant_id, flow_id)
    used = await db.scalar(
        select(func.count())
        .select_from(ApprovalInstance)
        .where(ApprovalInstance.flow_id == flow.id)
    )
    if used:
        raise ConflictError("流程已有审批实例，不能删除，可改为停用")
    await db.delete(flow)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.flow.delete",
        resource_type="approval_flow",
        resource_id=flow_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


# ---------------------------------------------------------------- instances


@router.get("/instances", summary="审批实例列表")
async def list_instances(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    scope: str = Query("mine", pattern="^(mine|inbox|all)$"),
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
):
    conditions = [ApprovalInstance.tenant_id == current_user.tenant_id]
    if status:
        conditions.append(ApprovalInstance.status == status)
    if category:
        conditions.append(ApprovalInstance.category == category)
    if q:
        conditions.append(ApprovalInstance.title.ilike(f"%{q.strip()}%"))

    if scope == "mine":
        conditions.append(ApprovalInstance.initiator_id == current_user.id)
    elif scope == "inbox":
        conditions.append(
            exists().where(
                ApprovalTask.instance_id == ApprovalInstance.id,
                ApprovalTask.tenant_id == current_user.tenant_id,
                ApprovalTask.approver_id == current_user.id,
                ApprovalTask.status == "pending",
            )
        )
    elif not current_user.is_superuser:
        conditions.append(
            or_(
                ApprovalInstance.initiator_id == current_user.id,
                exists().where(
                    ApprovalTask.instance_id == ApprovalInstance.id,
                    ApprovalTask.tenant_id == current_user.tenant_id,
                    ApprovalTask.approver_id == current_user.id,
                ),
            )
        )

    stmt = select(ApprovalInstance).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ApprovalInstance.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    flows, forms, users = await _name_maps(db, current_user.tenant_id, items)
    return paged(
        [
            _instance_dict(
                item,
                flow_name=flows.get(item.flow_id),
                form_name=forms.get(item.form_id),
                initiator_name=users.get(item.initiator_id),
            )
            for item in items
        ],
        total,
        page,
        page_size,
    )


@router.post("/instances", summary="发起审批")
async def create_instance(
    payload: InstanceCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    flow = await get_flow(db, current_user.tenant_id, payload.flow_id)
    instance = await start_approval(
        db,
        tenant_id=current_user.tenant_id,
        initiator_id=current_user.id,
        flow=flow,
        title=payload.title,
        form_data=payload.form_data,
        employee_id=payload.employee_id,
        task_instance_id=payload.task_instance_id,
        business_ref=payload.business_ref,
        priority=payload.priority,
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.instance.create",
        resource_type="approval_instance",
        resource_id=instance.id,
        detail={"flow": flow.code, "title": instance.title},
        ip_address=client_ip(request),
    )
    tasks = list(
        (
            await db.scalars(
                select(ApprovalTask).where(ApprovalTask.instance_id == instance.id)
            )
        ).all()
    )
    my_tasks = [
        task
        for task in tasks
        if task.approver_id == current_user.id and task.status == "pending"
    ]
    return success(
        _instance_dict(
            instance,
            flow_name=flow.name,
            form_name=(instance.form_snapshot or {}).get("name"),
            initiator_name=current_user.full_name or current_user.username,
            tasks=tasks,
            my_tasks=my_tasks,
        )
    )


@router.get("/instances/{instance_id}", summary="审批实例详情")
async def get_instance_detail(
    instance_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await get_instance(db, current_user.tenant_id, instance_id)
    if not await _can_view_instance(db, instance, current_user):
        raise ForbiddenError("没有权限查看该审批")
    tasks = list(
        (
            await db.scalars(
                select(ApprovalTask)
                .where(ApprovalTask.instance_id == instance.id)
                .order_by(
                    ApprovalTask.node_key.asc(),
                    ApprovalTask.sequence_order.asc(),
                    ApprovalTask.id.asc(),
                )
            )
        ).all()
    )
    actions = list(
        (
            await db.scalars(
                select(ApprovalAction)
                .where(ApprovalAction.instance_id == instance.id)
                .order_by(ApprovalAction.id.asc())
            )
        ).all()
    )
    my_tasks = [
        task
        for task in tasks
        if task.approver_id == current_user.id and task.status == "pending"
    ]
    flows, forms, users = await _name_maps(db, current_user.tenant_id, [instance])
    return success(
        _instance_dict(
            instance,
            flow_name=flows.get(instance.flow_id),
            form_name=forms.get(instance.form_id),
            initiator_name=users.get(instance.initiator_id),
            tasks=tasks,
            actions=actions,
            my_tasks=my_tasks,
        )
    )


@router.post("/instances/{instance_id}/cancel", summary="取消审批")
async def cancel(
    instance_id: int,
    payload: DecisionRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await get_instance(db, current_user.tenant_id, instance_id)
    if instance.initiator_id != current_user.id and not current_user.is_superuser:
        raise ForbiddenError("只有发起人或管理员可以取消审批")
    await cancel_instance(db, instance.id, current_user.id, payload.comment)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.instance.cancel",
        resource_type="approval_instance",
        resource_id=instance.id,
        detail={"comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success(InstanceOut.model_validate(instance).model_dump(mode="json"))


@router.post("/instances/{instance_id}/remind", summary="催办审批")
async def remind(
    instance_id: int,
    payload: DecisionRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await get_instance(db, current_user.tenant_id, instance_id)
    if instance.initiator_id != current_user.id and not current_user.is_superuser:
        raise ForbiddenError("只有发起人或管理员可以催办")
    count = await remind_instance(db, instance.id, current_user.id, payload.comment)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.instance.remind",
        resource_type="approval_instance",
        resource_id=instance.id,
        detail={"approvers": count},
        ip_address=client_ip(request),
    )
    return success({"notified": count})


@router.post("/instances/{instance_id}/launch-task", summary="审批通过后创建数字员工任务")
async def launch_task(
    instance_id: int,
    payload: LaunchTaskRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    instance = await get_instance(db, current_user.tenant_id, instance_id)
    if instance.initiator_id != current_user.id and not current_user.is_superuser:
        raise ForbiddenError("只有发起人或管理员可以创建关联任务")
    task_id = await launch_employee_task(
        db, instance, payload.employee_id, actor_id=current_user.id
    )
    if task_id is None:
        raise BadRequestError("该流程没有配置数字员工，请在发起时选择员工或配置流程默认员工")
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.instance.launch_task",
        resource_type="approval_instance",
        resource_id=instance.id,
        detail={"task_instance_id": task_id},
        ip_address=client_ip(request),
    )
    return success({"task_instance_id": task_id})


# ---------------------------------------------------------------- tasks


@router.get("/tasks", summary="我的审批任务")
async def list_tasks(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("pending"),
):
    conditions = [
        ApprovalTask.tenant_id == current_user.tenant_id,
        ApprovalTask.approver_id == current_user.id,
    ]
    if status:
        conditions.append(ApprovalTask.status == status)
    stmt = select(ApprovalTask).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    tasks = list(
        (
            await db.scalars(
                stmt.order_by(ApprovalTask.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    instance_ids = {task.instance_id for task in tasks}
    instances: dict[int, ApprovalInstance] = {}
    if instance_ids:
        rows = await db.scalars(
            select(ApprovalInstance).where(
                ApprovalInstance.tenant_id == current_user.tenant_id,
                ApprovalInstance.id.in_(instance_ids),
            )
        )
        instances = {row.id: row for row in rows}
    flows, forms, users = await _name_maps(
        db, current_user.tenant_id, list(instances.values())
    )
    payload = []
    for task in tasks:
        instance = instances.get(task.instance_id)
        data = _task_dict(task)
        data.update(
            {
                "instance_title": instance.title if instance else None,
                "instance_status": instance.status if instance else None,
                "category": instance.category if instance else None,
                "current_node_name": instance.current_node_name if instance else None,
                "flow_name": flows.get(instance.flow_id) if instance else None,
                "initiator_name": users.get(instance.initiator_id) if instance else None,
                "due_at": task.due_at.isoformat() if task.due_at else None,
            }
        )
        payload.append(data)
    return paged(payload, total, page, page_size)


@router.post("/tasks/{task_id}/approve", summary="通过审批")
async def approve(
    task_id: int,
    payload: DecisionRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    task = await _get_task(db, current_user.tenant_id, task_id)
    await approve_task(db, task.id, current_user.id, payload.comment)
    instance = await get_instance(db, current_user.tenant_id, task.instance_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.task.approve",
        resource_type="approval_task",
        resource_id=task.id,
        detail={"instance_id": instance.id, "comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success(
        {"task": _task_dict(task), "instance_status": instance.status, "instance_id": instance.id}
    )


@router.post("/tasks/{task_id}/reject", summary="驳回审批")
async def reject(
    task_id: int,
    payload: DecisionRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    task = await _get_task(db, current_user.tenant_id, task_id)
    await reject_task(db, task.id, current_user.id, payload.comment)
    instance = await get_instance(db, current_user.tenant_id, task.instance_id)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.task.reject",
        resource_type="approval_task",
        resource_id=task.id,
        detail={"instance_id": instance.id, "comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success(
        {"task": _task_dict(task), "instance_status": instance.status, "instance_id": instance.id}
    )


@router.post("/tasks/{task_id}/transfer", summary="转办审批")
async def transfer(
    task_id: int,
    payload: TransferRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    task = await _get_task(db, current_user.tenant_id, task_id)
    await transfer_task(
        db, task.id, current_user.id, payload.target_user_id, payload.comment
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.task.transfer",
        resource_type="approval_task",
        resource_id=task.id,
        detail={"target_user_id": payload.target_user_id, "comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success(_task_dict(task))


@router.post("/tasks/{task_id}/add-sign", summary="加签")
async def add_sign_endpoint(
    task_id: int,
    payload: AddSignRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    task = await _get_task(db, current_user.tenant_id, task_id)
    added = await add_sign(
        db, task.id, current_user.id, payload.user_ids, payload.comment
    )
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="approval.task.add_sign",
        resource_type="approval_task",
        resource_id=task.id,
        detail={"user_ids": payload.user_ids, "comment": payload.comment},
        ip_address=client_ip(request),
    )
    return success([_task_dict(item) for item in added])


# ---------------------------------------------------------------- notifications


@router.get("/notifications", summary="我的审批通知")
async def list_notifications(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
):
    conditions = [
        ApprovalNotification.tenant_id == current_user.tenant_id,
        ApprovalNotification.user_id == current_user.id,
    ]
    if status:
        conditions.append(ApprovalNotification.status == status)
    stmt = select(ApprovalNotification).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ApprovalNotification.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return paged(
        [NotificationOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("/notifications/{notification_id}/read", summary="标记通知已读")
async def read_notification(
    notification_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    row = await _get_notification(
        db, current_user.tenant_id, current_user.id, notification_id
    )
    row.status = "read"
    row.read_at = utcnow()
    await db.flush()
    return success(NotificationOut.model_validate(row).model_dump(mode="json"))


@router.post("/notifications/read-all", summary="全部标记已读")
async def read_all_notifications(db: DbSession, current_user: CurrentUser):
    rows = list(
        (
            await db.scalars(
                select(ApprovalNotification).where(
                    ApprovalNotification.tenant_id == current_user.tenant_id,
                    ApprovalNotification.user_id == current_user.id,
                    ApprovalNotification.status == "unread",
                )
            )
        ).all()
    )
    now = utcnow()
    for row in rows:
        row.status = "read"
        row.read_at = now
    await db.flush()
    return success({"updated": len(rows)})


# ---------------------------------------------------------------- stats


@router.get("/stats", summary="审批工作台统计")
async def stats(db: DbSession, current_user: CurrentUser):
    tenant_id = current_user.tenant_id
    pending_for_me = await db.scalar(
        select(func.count())
        .select_from(ApprovalTask)
        .join(ApprovalInstance, ApprovalInstance.id == ApprovalTask.instance_id)
        .where(
            ApprovalTask.tenant_id == tenant_id,
            ApprovalTask.approver_id == current_user.id,
            ApprovalTask.status == "pending",
            ApprovalInstance.status == "running",
        )
    ) or 0
    overdue = await db.scalar(
        select(func.count())
        .select_from(ApprovalTask)
        .join(ApprovalInstance, ApprovalInstance.id == ApprovalTask.instance_id)
        .where(
            ApprovalTask.tenant_id == tenant_id,
            ApprovalTask.approver_id == current_user.id,
            ApprovalTask.status == "pending",
            ApprovalTask.due_at.is_not(None),
            ApprovalTask.due_at < utcnow(),
            ApprovalInstance.status == "running",
        )
    ) or 0
    unread = await db.scalar(
        select(func.count())
        .select_from(ApprovalNotification)
        .where(
            ApprovalNotification.tenant_id == tenant_id,
            ApprovalNotification.user_id == current_user.id,
            ApprovalNotification.status == "unread",
        )
    ) or 0

    mine = list(
        (
            await db.scalars(
                select(ApprovalInstance).where(
                    ApprovalInstance.tenant_id == tenant_id,
                    ApprovalInstance.initiator_id == current_user.id,
                )
            )
        ).all()
    )
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    durations: list[float] = []
    for item in mine:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_category[item.category] = by_category.get(item.category, 0) + 1
        if item.status == "approved" and item.completed_at and item.created_at:
            durations.append(
                (item.completed_at - item.created_at).total_seconds() / 3600
            )
    return success(
        {
            "pending_for_me": pending_for_me,
            "overdue_for_me": overdue,
            "unread_notifications": unread,
            "my_total": len(mine),
            "my_by_status": by_status,
            "my_by_category": by_category,
            "my_avg_duration_hours": round(sum(durations) / len(durations), 2)
            if durations
            else 0,
        }
    )
