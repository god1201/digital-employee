import asyncio
import json
import logging
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret
from app.domains.governance.access.models import Authorization
from app.domains.governance.access.service import evaluate_access
from app.domains.skills.mcp.client import MCPError, call_remote_tool
from app.domains.skills.mcp.models import MCPServer
from app.domains.skills.tools.models import Tool

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 200_000
_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

_PYTHON_WRAPPER = """
import importlib.util
import json
import sys


def main() -> None:
    tool_path = sys.argv[1]
    spec = importlib.util.spec_from_file_location("digital_employee_tool", tool_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载工具代码")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = getattr(module, "run", None)
    if not callable(entry):
        raise RuntimeError("工具代码必须定义 run(args: dict) 函数")
    args = json.load(sys.stdin)
    result = entry(args)
    json.dump({"ok": True, "result": result}, sys.stdout, default=str)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout)
        sys.exit(1)
"""


class ToolExecutionError(Exception):
    """工具执行失败，消息可直接展示给运维人员。"""


@dataclass
class ToolExecutionResult:
    success: bool
    output: dict
    error: str | None = None
    latency_ms: int = 0


def _resolve_path(path: str, context: dict):
    current = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def render_templates(value, context: dict):
    """递归渲染 {{input.xxx}} / {{last.xxx}} 等占位符，保留原始类型。"""
    if isinstance(value, dict):
        return {key: render_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render_templates(item, context) for item in value]
    if not isinstance(value, str):
        return value

    full_match = _TEMPLATE_RE.fullmatch(value.strip())
    if full_match:
        resolved = _resolve_path(full_match.group(1), context)
        return resolved if resolved is not None else value

    def replace(match: re.Match) -> str:
        resolved = _resolve_path(match.group(1), context)
        return "" if resolved is None else str(resolved)

    return _TEMPLATE_RE.sub(replace, value)


def _clamp_timeout(value, default: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return default
    return max(1.0, min(timeout, 120.0))


async def _resolve_authorization(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    system_code: str | None,
) -> Authorization | None:
    if not system_code:
        return None
    return await db.scalar(
        select(Authorization)
        .where(
            Authorization.tenant_id == tenant_id,
            Authorization.system_code == system_code,
            Authorization.status == "active",
            or_(
                Authorization.employee_id == employee_id,
                Authorization.employee_id.is_(None),
            ),
        )
        .order_by(Authorization.employee_id.is_(None), Authorization.id.desc())
    )


def _inject_credential(headers: dict, authorization: Authorization, config: dict) -> None:
    if not authorization.credential_encrypted:
        return
    credential = decrypt_secret(authorization.credential_encrypted)

    if authorization.access_type == "api_key":
        header_name = str(config.get("api_key_header") or "X-API-Key")
        headers.setdefault(header_name, credential)
    elif authorization.access_type in {"token", "oauth2"}:
        headers.setdefault("Authorization", f"Bearer {credential}")
    elif authorization.access_type == "cookie":
        headers.setdefault("Cookie", credential)
    elif authorization.access_type == "login":
        raise ToolExecutionError("login 类型授权暂不支持直接调用，请改用 token 或 api_key")


async def _execute_http(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    tool: Tool,
    arguments: dict,
) -> dict:
    config = tool.config or {}
    system_code = config.get("system_code")
    raw_url = config.get("url") or config.get("path")
    if not raw_url:
        raise ToolExecutionError("HTTP 工具缺少 config.url 或 config.path")

    context = {"args": arguments, "arguments": arguments}
    url = str(render_templates(raw_url, context))
    authorization = await _resolve_authorization(db, tenant_id, employee_id, system_code)

    if not url.startswith(("http://", "https://")):
        if authorization is None or not authorization.base_url:
            raise ToolExecutionError("相对路径需要授权记录提供 base_url")
        url = authorization.base_url.rstrip("/") + "/" + url.lstrip("/")

    method = str(config.get("method") or "GET").upper()
    request_path = urlsplit(url).path or "/"
    decision = await evaluate_access(
        db,
        tenant_id,
        employee_id=employee_id,
        method=method,
        path=request_path,
        system_code=system_code,
    )
    if not decision.allowed:
        raise ToolExecutionError(f"访问被拒绝：{decision.reason}")

    headers = dict(config.get("headers") or {})
    if authorization is not None:
        _inject_credential(headers, authorization, config)

    timeout = _clamp_timeout(config.get("timeout"), 15.0)
    use_query = method in {"GET", "HEAD", "DELETE", "OPTIONS"}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.request(
            method,
            url,
            params=arguments if use_query else None,
            json=None if use_query else arguments,
            headers=headers,
        )

    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:MAX_OUTPUT_CHARS]
    else:
        payload = response.text[:MAX_OUTPUT_CHARS]

    if response.status_code >= 400:
        raise ToolExecutionError(f"HTTP {response.status_code}: {str(payload)[:500]}")

    return {"status_code": response.status_code, "body": payload}


async def _execute_python(tool: Tool, arguments: dict) -> dict:
    config = tool.config or {}
    code = config.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ToolExecutionError("Python 工具缺少 config.code")

    timeout = _clamp_timeout(config.get("timeout"), 10.0)

    with tempfile.TemporaryDirectory(prefix="de_tool_") as tmp:
        tool_path = Path(tmp) / "tool_module.py"
        wrapper_path = Path(tmp) / "runner.py"
        tool_path.write_text(code, encoding="utf-8")
        wrapper_path.write_text(_PYTHON_WRAPPER, encoding="utf-8")

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(wrapper_path),
            str(tool_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(arguments, ensure_ascii=True).encode("utf-8")),
                timeout=timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ToolExecutionError(f"Python 工具执行超时（{timeout:g}s）") from exc

    if len(stdout) > MAX_OUTPUT_CHARS:
        raise ToolExecutionError(f"Python 工具输出过大（>{MAX_OUTPUT_CHARS} 字符）")

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        error_text = stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {error_text[:500]}" if error_text else ""
        raise ToolExecutionError(f"Python 工具无输出{suffix}")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"Python 工具输出不是合法 JSON: {text[:500]}") from exc

    if not payload.get("ok"):
        raise ToolExecutionError(f"Python 工具执行失败: {payload.get('error') or '未知错误'}")
    return {"result": payload.get("result")}


async def _execute_mcp(
    db: AsyncSession,
    tenant_id: int,
    tool: Tool,
    arguments: dict,
) -> dict:
    config = tool.config or {}
    server_id = config.get("mcp_server_id")
    remote_tool = config.get("mcp_tool")
    if not server_id or not remote_tool:
        raise ToolExecutionError("MCP 工具缺少 mcp_server_id / mcp_tool 配置")

    try:
        server_id_int = int(server_id)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("MCP 工具配置无效: mcp_server_id 必须是整数") from exc

    server = await db.scalar(
        select(MCPServer).where(
            MCPServer.id == server_id_int,
            MCPServer.tenant_id == tenant_id,
        )
    )
    if server is None:
        raise ToolExecutionError("MCP Server 不存在或已删除")

    try:
        return await call_remote_tool(server, str(remote_tool), arguments)
    except MCPError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def execute_tool(
    db: AsyncSession,
    *,
    tenant_id: int,
    employee_id: int,
    tool_code: str | None = None,
    tool: Tool | None = None,
    arguments: dict | None = None,
) -> ToolExecutionResult:
    """执行工具，并在 HTTP 调用前强制做准入检查。"""
    started = time.perf_counter()
    args = arguments or {}

    try:
        if tool is None:
            if not tool_code:
                raise ToolExecutionError("缺少工具编码")
            tool = await db.scalar(
                select(Tool).where(
                    Tool.tenant_id == tenant_id,
                    Tool.code == tool_code,
                    Tool.enabled.is_(True),
                )
            )
            if tool is None:
                raise ToolExecutionError(f"工具不存在或已停用: {tool_code}")

        if tool.tool_type == "http":
            output = await _execute_http(db, tenant_id, employee_id, tool, args)
        elif tool.tool_type == "python":
            output = await _execute_python(tool, args)
        elif tool.tool_type == "mcp":
            output = await _execute_mcp(db, tenant_id, tool, args)
        else:
            raise ToolExecutionError(f"不支持的工具类型: {tool.tool_type}")

        return ToolExecutionResult(
            success=True,
            output=output,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except ToolExecutionError as exc:
        return ToolExecutionResult(
            success=False,
            output={},
            error=str(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("工具执行异常: %s", tool_code or "")
        return ToolExecutionResult(
            success=False,
            output={},
            error=f"工具执行异常: {exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
