import hashlib
import hmac
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.domains.identity.models import User

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer JWT")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    if credentials is None:
        raise UnauthorizedError("缺少访问令牌")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("令牌无效或已过期") from exc

    try:
        user_id = int(payload.get("sub", "0"))
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("令牌内容无效") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise ForbiddenError("仅管理员可执行该操作")
    return current_user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def hash_callback_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def callback_token_matches(provided: str | None, expected_hash: str | None) -> bool:
    if not provided or not expected_hash:
        return False
    return hmac.compare_digest(hash_callback_token(provided), expected_hash)


async def get_optional_user(request: Request, db: DbSession) -> User | None:
    credentials = await bearer_scheme(request)
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except UnauthorizedError:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
