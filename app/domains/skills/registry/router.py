from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.response import paged, success
from app.core.utils import client_ip
from app.domains.governance.audit.service import record_audit
from app.domains.skills.registry.models import ApiRegistry
from app.domains.skills.registry.schemas import (
    ApiRegistryCreate,
    ApiRegistryOut,
    ApiRegistryUpdate,
    OpenAPIImportRequest,
    OpenAPIImportResult,
)
from app.domains.skills.tools.models import Tool

router = APIRouter(prefix="/api-registries", tags=["接口登记"])

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
WRITE_METHODS = {"post", "put", "patch", "delete"}


async def _get_registry(db: DbSession, tenant_id: int, api_id: int) -> ApiRegistry:
    api = await db.scalar(
        select(ApiRegistry).where(
            ApiRegistry.id == api_id,
            ApiRegistry.tenant_id == tenant_id,
        )
    )
    if api is None:
        raise NotFoundError("接口登记不存在")
    return api


def _extract_request_schema(operation: dict) -> dict:
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        for media in (request_body.get("content") or {}).values():
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return media["schema"]
    parameters = operation.get("parameters")
    if isinstance(parameters, list) and parameters:
        return {"parameters": parameters}
    return {}


def _extract_response_schema(operation: dict) -> dict:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return {}
    for code in ("200", "201", 200, 201):
        response = responses.get(code)
        if not isinstance(response, dict):
            continue
        for media in (response.get("content") or {}).values():
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return media["schema"]
        schema = response.get("schema")
        if isinstance(schema, dict):
            return schema
    return {}


def _risk_for(method: str) -> str:
    if method == "delete":
        return "high"
    if method in WRITE_METHODS:
        return "medium"
    return "low"


@router.get("", summary="接口目录")
async def list_registries(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    system_code: str | None = None,
    method: str | None = None,
    risk_level: str | None = None,
    keyword: str | None = None,
):
    conditions = [ApiRegistry.tenant_id == current_user.tenant_id]
    if system_code:
        conditions.append(ApiRegistry.system_code == system_code)
    if method:
        conditions.append(ApiRegistry.method == method.upper())
    if risk_level:
        conditions.append(ApiRegistry.risk_level == risk_level)
    if keyword:
        conditions.append(
            or_(
                ApiRegistry.name.ilike(f"%{keyword}%"),
                ApiRegistry.path.ilike(f"%{keyword}%"),
            )
        )

    stmt = select(ApiRegistry).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        (
            await db.scalars(
                stmt.order_by(ApiRegistry.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
    )
    return paged(
        [ApiRegistryOut.model_validate(item).model_dump(mode="json") for item in items],
        total,
        page,
        page_size,
    )


@router.post("", summary="登记接口")
async def create_registry(
    payload: ApiRegistryCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    exists = await db.scalar(
        select(ApiRegistry.id).where(
            ApiRegistry.tenant_id == current_user.tenant_id,
            ApiRegistry.system_code == payload.system_code,
            ApiRegistry.method == payload.method,
            ApiRegistry.path == payload.path,
        )
    )
    if exists:
        raise ConflictError("该接口已登记")

    api = ApiRegistry(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(api)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="api_registry.create",
        resource_type="api_registry",
        resource_id=api.id,
        detail={"method": api.method, "path": api.path, "risk": api.risk_level},
        ip_address=client_ip(request),
    )
    return success(ApiRegistryOut.model_validate(api).model_dump(mode="json"))


@router.post("/import-openapi", summary="导入 OpenAPI 文档")
async def import_openapi(
    payload: OpenAPIImportRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    paths = payload.spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise BadRequestError("spec.paths 为空或格式不正确")

    created = updated = skipped = 0
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for raw_method, operation in item.items():
            method = raw_method.lower()
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            method_upper = method.upper()
            existing = await db.scalar(
                select(ApiRegistry).where(
                    ApiRegistry.tenant_id == current_user.tenant_id,
                    ApiRegistry.system_code == payload.system_code,
                    ApiRegistry.method == method_upper,
                    ApiRegistry.path == path,
                )
            )
            name = (
                operation.get("summary") or operation.get("operationId") or f"{method_upper} {path}"
            )
            values = {
                "system_name": payload.system_name,
                "system_code": payload.system_code,
                "name": str(name)[:255],
                "method": method_upper,
                "path": path,
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "risk_level": _risk_for(method),
                "request_schema": _extract_request_schema(operation),
                "response_schema": _extract_response_schema(operation),
                "tags": operation.get("tags") or [],
                "source": "openapi",
            }
            if existing:
                if not payload.overwrite:
                    skipped += 1
                    continue
                for field, value in values.items():
                    setattr(existing, field, value)
                updated += 1
            else:
                db.add(
                    ApiRegistry(
                        tenant_id=current_user.tenant_id,
                        created_by=current_user.id,
                        **values,
                    )
                )
                created += 1

    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="api_registry.import_openapi",
        resource_type="api_registry",
        detail={
            "system_code": payload.system_code,
            "created": created,
            "updated": updated,
            "skipped": skipped,
        },
        ip_address=client_ip(request),
    )
    result = OpenAPIImportResult(created=created, updated=updated, skipped=skipped)
    return success(result.model_dump(mode="json"))


@router.get("/{api_id}", summary="接口详情")
async def get_registry(
    api_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    api = await _get_registry(db, current_user.tenant_id, api_id)
    return success(ApiRegistryOut.model_validate(api).model_dump(mode="json"))


@router.patch("/{api_id}", summary="更新接口登记")
async def update_registry(
    api_id: int,
    payload: ApiRegistryUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    api = await _get_registry(db, current_user.tenant_id, api_id)
    changes = payload.model_dump(exclude_unset=True)
    if "method" in changes and isinstance(changes["method"], str):
        changes["method"] = changes["method"].upper()
    for field, value in changes.items():
        setattr(api, field, value)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="api_registry.update",
        resource_type="api_registry",
        resource_id=api.id,
        detail={"fields": sorted(changes.keys())},
        ip_address=client_ip(request),
    )
    return success(ApiRegistryOut.model_validate(api).model_dump(mode="json"))


@router.delete("/{api_id}", summary="删除接口登记")
async def delete_registry(
    api_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    api = await _get_registry(db, current_user.tenant_id, api_id)
    await db.delete(api)
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="api_registry.delete",
        resource_type="api_registry",
        resource_id=api_id,
        ip_address=client_ip(request),
    )
    return success(None, "已删除")


@router.post("/{api_id}/to-tool", summary="将登记接口转换为工具")
async def registry_to_tool(
    api_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
):
    api = await _get_registry(db, current_user.tenant_id, api_id)
    tool_code = f"api_{api.id}"
    existing = await db.scalar(
        select(Tool).where(
            Tool.tenant_id == current_user.tenant_id,
            Tool.code == tool_code,
        )
    )
    if existing:
        return success({"tool_id": existing.id, "code": existing.code, "created": False})

    tool = Tool(
        tenant_id=current_user.tenant_id,
        name=api.name,
        code=tool_code,
        tool_type="http",
        description=api.summary or api.description or f"{api.method} {api.path}",
        parameters_schema=api.request_schema,
        config={
            "api_registry_id": api.id,
            "system_code": api.system_code,
            "method": api.method,
            "path": api.path,
        },
        risk_level=api.risk_level,
        enabled=True,
        source="custom",
        api_registry_id=api.id,
        created_by=current_user.id,
    )
    db.add(tool)
    await db.flush()
    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="api_registry.to_tool",
        resource_type="tool",
        resource_id=tool.id,
        detail={"api_registry_id": api.id, "code": tool.code},
        ip_address=client_ip(request),
    )
    return success({"tool_id": tool.id, "code": tool.code, "created": True})
