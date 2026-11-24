from datetime import datetime

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class RegisterRequest(BaseModel):
    tenant_name: str = Field(default="默认租户", max_length=128)
    tenant_code: str = Field(default="default", max_length=64)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_code: str | None = Field(default=None, description="多租户下建议传入")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=128)
    is_superuser: bool = False


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None
    is_superuser: bool | None = None


class UserOut(ORMModel):
    id: int
    tenant_id: int
    username: str
    email: str | None = None
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
