from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core.deps import CurrentAdmin, CurrentUser, DbSession
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.core.response import success
from app.core.security import create_access_token, hash_password, verify_password
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.identity.models import Tenant, User
from app.domains.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", summary="初始化管理员账号（仅首次）")
async def register(payload: RegisterRequest, db: DbSession):
    user_count = await db.scalar(select(func.count()).select_from(User))
    if user_count:
        raise ForbiddenError("系统已初始化，请由管理员创建账号")

    tenant = Tenant(name=payload.tenant_name, code=payload.tenant_code)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_superuser=True,
    )
    db.add(user)
    await db.flush()
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.post("/login", summary="账号密码登录")
async def login(payload: LoginRequest, db: DbSession):
    stmt = select(User).where(User.username == payload.username, User.is_active.is_(True))
    if payload.tenant_code:
        stmt = stmt.join(Tenant, Tenant.id == User.tenant_id).where(
            Tenant.code == payload.tenant_code
        )
    users = list((await db.scalars(stmt)).all())
    if not users:
        raise UnauthorizedError("用户名或密码错误")
    if len(users) > 1:
        raise BadRequestError("存在同名账号，请传入 tenant_code")

    user = users[0]
    if not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("用户名或密码错误")

    user.last_login_at = datetime.now(UTC)
    token = create_access_token(
        str(user.id),
        {"tenant_id": user.tenant_id, "username": user.username},
    )
    response = TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )
    return success(response.model_dump(mode="json"))


@router.get("/me", summary="当前登录用户")
async def me(current_user: CurrentUser):
    return success(UserOut.model_validate(current_user).model_dump(mode="json"))


@router.get("/users", summary="租户用户列表")
async def list_users(db: DbSession, current_user: CurrentUser):
    users = list(
        (
            await db.scalars(
                select(User)
                .where(User.tenant_id == current_user.tenant_id)
                .order_by(User.id.asc())
            )
        ).all()
    )
    return success([UserOut.model_validate(user).model_dump(mode="json") for user in users])


@router.post("/users", summary="创建租户用户（管理员）")
async def create_user(
    payload: UserCreate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    duplicate = await db.scalar(
        select(User.id).where(
            User.tenant_id == current_admin.tenant_id,
            User.username == payload.username,
        )
    )
    if duplicate:
        raise ConflictError("用户名已存在")
    user = User(
        tenant_id=current_admin.tenant_id,
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_superuser=payload.is_superuser,
    )
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        detail={"username": user.username, "is_superuser": user.is_superuser},
        ip_address=client_ip(request),
    )
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.patch("/users/{user_id}", summary="更新租户用户（管理员）")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: DbSession,
    current_admin: CurrentAdmin,
):
    user = await db.scalar(
        select(User).where(
            User.id == user_id, User.tenant_id == current_admin.tenant_id
        )
    )
    if user is None:
        raise NotFoundError("用户不存在")
    changes = payload.model_dump(exclude_unset=True)
    if "password" in changes:
        password = changes.pop("password")
        if password:
            user.hashed_password = hash_password(password)
    for field, value in changes.items():
        setattr(user, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_admin.tenant_id,
        user_id=current_admin.id,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(UserOut.model_validate(user).model_dump(mode="json"))
