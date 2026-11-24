"""AIGC 生成服务适配层。

支持四类 Provider：

- ``mock``         内置占位实现，无需外部服务即可跑通生成/审核/素材全链路
- ``openai_image`` OpenAI 兼容的图片生成接口（``/images/generations``）
- ``comfyui``      ComfyUI 工作流：提交 prompt → 轮询 history → 下载输出
- ``http_generic`` 配置驱动的通用 HTTP 适配器，可对接即梦/可灵/Runway 等异步任务 API

新增服务只需实现 ``BaseProvider.generate`` 并在 ``PROVIDER_REGISTRY`` 注册。
"""

import asyncio
import base64
import copy
import hashlib
import html
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.domains.workflows.aigc.storage import (
    extension_for_mime,
    mime_for_path,
    resolve_relative,
)

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
SIZE_RE = re.compile(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$")

SUPPORTED_JOB_TYPES = ("text_to_image", "text_to_video", "image_to_video")
JOB_TYPE_LABELS = {
    "text_to_image": "文生图",
    "text_to_video": "文生视频",
    "image_to_video": "图生视频",
}

DEFAULT_SUPPORTED_TYPES = {
    "mock": list(SUPPORTED_JOB_TYPES),
    "openai_image": ["text_to_image"],
    "comfyui": list(SUPPORTED_JOB_TYPES),
    "http_generic": list(SUPPORTED_JOB_TYPES),
}


class ProviderError(Exception):
    """生成服务调用失败。"""


@dataclass
class GeneratedMedia:
    data: bytes | None = None
    url: str | None = None
    mime_type: str = "application/octet-stream"
    extension: str = "bin"
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    cost: float = 0.0
    metadata: dict = field(default_factory=dict)


def render_placeholders(text: str, values: dict) -> str:
    """渲染 ``{{name}}`` 占位符；缺失变量保留原样，便于前端提示。"""

    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = values.get(key, match.group(0))
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, text or "")


def missing_placeholders(text: str) -> list[str]:
    return sorted({match.group(1) for match in PLACEHOLDER_RE.finditer(text or "")})


def clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def parse_size(params: dict) -> tuple[int, int]:
    match = SIZE_RE.match(str(params.get("size") or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    width = clamp_int(params.get("width"), 256, 4096, 1024)
    height = clamp_int(params.get("height"), 256, 4096, 1024)
    return width, height


def units_for(provider, job_type: str, params: dict) -> float:
    unit = (provider.cost_unit or "image").lower()
    if unit == "image":
        return float(clamp_int(params.get("count"), 1, 8, 1))
    if unit == "second":
        try:
            return max(1.0, float(params.get("duration") or 5))
        except (TypeError, ValueError):
            return 5.0
    return 1.0


def estimate_cost(provider, job_type: str, params: dict) -> float:
    return round(float(provider.cost_per_unit or 0.0) * units_for(provider, job_type, params), 4)


def build_provider(row):
    provider_cls = PROVIDER_REGISTRY.get(row.provider_type or "mock")
    if provider_cls is None:
        raise ProviderError(f"不支持的生成服务类型: {row.provider_type}")
    api_key = ""
    if row.api_key_encrypted:
        try:
            api_key = decrypt_secret(row.api_key_encrypted)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
    return provider_cls(row, api_key=api_key)


def _check_supported(provider, job_type: str) -> None:
    supported = provider.row.supported_types or DEFAULT_SUPPORTED_TYPES.get(
        provider.row.provider_type, list(SUPPORTED_JOB_TYPES)
    )
    if job_type not in supported:
        label = JOB_TYPE_LABELS.get(job_type, job_type)
        raise ProviderError(f"生成服务「{provider.row.name}」不支持{label}")


async def _download_media(client: httpx.AsyncClient, url: str, headers: dict | None = None):
    if not url:
        raise ProviderError("生成服务没有返回媒体地址")
    try:
        async with client.stream("GET", url, headers=headers or {}) as response:
            if response.status_code >= 400:
                raise ProviderError(f"下载生成结果失败: HTTP {response.status_code}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > settings.aigc_download_max_bytes:
                    raise ProviderError("生成结果超过允许的最大体积")
                chunks.append(chunk)
            mime = (response.headers.get("content-type") or "").split(";")[0].strip()
    except httpx.TimeoutException as exc:
        raise ProviderError(f"下载生成结果超时: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"下载生成结果失败: {exc}") from exc
    mime = mime or mime_for_path(url)
    return b"".join(chunks), mime


def _request_error_text(response: httpx.Response) -> str:
    text = (response.text or "").strip().replace("\n", " ")
    return text[:300]


class BaseProvider:
    def __init__(self, row, api_key: str = "") -> None:
        self.row = row
        self.api_key = api_key
        self.config = row.config or {}

    @property
    def timeout(self) -> float:
        return float(self.row.timeout_seconds or settings.aigc_request_timeout_seconds)

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.config.get("headers") or {})
        headers.update(extra or {})
        return headers

    async def generate(
        self,
        *,
        job_type: str,
        prompt: str,
        negative_prompt: str,
        params: dict,
        input_asset: dict | None = None,
    ) -> list[GeneratedMedia]:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """无需外部服务的内置生成器：输出带提示词的可视化 SVG 占位素材。"""

    async def generate(
        self,
        *,
        job_type: str,
        prompt: str,
        negative_prompt: str,
        params: dict,
        input_asset: dict | None = None,
    ) -> list[GeneratedMedia]:
        _check_supported(self, job_type)
        if job_type == "image_to_video" and not input_asset:
            raise ProviderError("图生视频需要先上传一张输入图片")

        width, height = parse_size(params)
        duration = clamp_int(params.get("duration"), 1, 30, 5)
        count = 1 if job_type != "text_to_image" else clamp_int(params.get("count"), 1, 4, 1)
        results: list[GeneratedMedia] = []

        for index in range(count):
            svg = self._svg(
                job_type=job_type,
                prompt=prompt,
                width=width,
                height=height,
                duration=duration,
                index=index,
                input_asset=input_asset,
            )
            results.append(
                GeneratedMedia(
                    data=svg.encode("utf-8"),
                    mime_type="image/svg+xml",
                    extension="svg",
                    width=width,
                    height=height if job_type != "text_to_video" else 540,
                    duration_seconds=float(duration) if job_type != "text_to_image" else None,
                    cost=estimate_cost(self.row, job_type, params),
                    metadata={
                        "mock": True,
                        "job_type": job_type,
                        "index": index,
                        "note": "内置 Mock 素材，仅用于流程演示",
                    },
                )
            )
        return results

    def _svg(
        self,
        *,
        job_type: str,
        prompt: str,
        width: int,
        height: int,
        duration: int,
        index: int,
        input_asset: dict | None,
    ) -> str:
        digest = hashlib.sha256(f"{prompt}:{index}".encode()).hexdigest()
        hue = int(digest[:4], 16) % 360
        hue2 = (hue + 48) % 360
        label = JOB_TYPE_LABELS.get(job_type, job_type)
        is_video = job_type != "text_to_image"
        view_width = width
        view_height = 540 if is_video else height
        lines = self._wrap(prompt or "（空提示词）", 40)[:8]
        text_lines = "".join(
            f'<text x="64" y="{300 + line_no * 42}" fill="#e9eef5" '
            f'font-family="Segoe UI, Microsoft YaHei, sans-serif" font-size="28" '
            f'opacity="{1 - line_no * 0.06}">{html.escape(line)}</text>'
            for line_no, line in enumerate(lines)
        )
        background_image = ""
        if input_asset and input_asset.get("public_url"):
            background_image = (
                f'<image href="{html.escape(input_asset["public_url"], quote=True)}" '
                f'x="0" y="0" width="{view_width}" height="{view_height}" '
                'preserveAspectRatio="xMidYMid slice" opacity="0.45"/>'
            )

        motion = ""
        if is_video:
            motion = f"""
    <circle cx="120" cy="140" r="54" fill="hsl({hue2} 85% 62% / .55)">
      <animate attributeName="cx" values="120;{view_width - 120};120"
               dur="{max(3, duration)}s" repeatCount="indefinite"/>
    </circle>
    <rect x="0" y="{view_height - 8}" width="{view_width}" height="8" fill="hsl({hue} 90% 65%)">
      <animate attributeName="width" values="0;{view_width}" dur="{max(2, duration)}s"
               repeatCount="indefinite"/>
    </rect>"""

        dimensions = f'width="{view_width}" height="{view_height}"'
        return f"""<svg xmlns="http://www.w3.org/2000/svg" {dimensions}
     viewBox="0 0 {view_width} {view_height}" role="img">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl({hue} 42% 12%)"/>
      <stop offset="1" stop-color="hsl({hue2} 55% 24%)"/>
    </linearGradient>
    <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
      <path d="M48 0H0V48" fill="none" stroke="#ffffff" stroke-opacity="0.08"/>
    </pattern>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)"/>
  {background_image}
  <rect width="100%" height="100%" fill="url(#grid)"/>
  <g opacity="0.9">
    <circle cx="{view_width - 150}" cy="110" r="120" fill="hsl({hue2} 80% 60% / .28)"/>
    <circle cx="{view_width - 210}" cy="170" r="60" fill="hsl({hue} 90% 70% / .22)"/>
  </g>{motion}
  <text x="64" y="96" fill="hsl({hue2} 90% 72%)"
        font-family="Segoe UI, Microsoft YaHei, sans-serif" font-size="22"
        letter-spacing="4">MOCK · {label}</text>
  <text x="64" y="148" fill="#ffffff"
        font-family="Segoe UI, Microsoft YaHei, sans-serif" font-size="42"
        font-weight="600">DIGITAL EMPLOYEE AIGC</text>
  {text_lines}
  <text x="64" y="{view_height - 48}" fill="#9fb0c4"
        font-family="Segoe UI, Microsoft YaHei, sans-serif" font-size="20">
    {view_width}×{view_height}{f" · {duration}s" if is_video else ""} · SVG placeholder
  </text>
</svg>"""

    @staticmethod
    def _wrap(text: str, size: int) -> list[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        return [cleaned[start : start + size] for start in range(0, len(cleaned), size)]


class OpenAIImageProvider(BaseProvider):
    """OpenAI 兼容图片生成：POST {base_url}/images/generations。"""

    async def generate(
        self,
        *,
        job_type: str,
        prompt: str,
        negative_prompt: str,
        params: dict,
        input_asset: dict | None = None,
    ) -> list[GeneratedMedia]:
        _check_supported(self, job_type)
        base_url = (self.row.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/images/generations"
        count = clamp_int(params.get("count"), 1, 4, 1)
        width, height = parse_size(params)
        body = {
            "model": self.row.model or "gpt-image-1",
            "prompt": prompt,
            "n": count,
            "size": f"{width}x{height}",
        }
        if negative_prompt and self.config.get("support_negative_prompt"):
            body["negative_prompt"] = negative_prompt
        body.update(self.config.get("extra_body") or {})

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                response = await client.post(url, headers=self._headers(), json=body)
                if response.status_code >= 400:
                    raise ProviderError(
                        f"图片生成服务返回 HTTP {response.status_code}: "
                        f"{_request_error_text(response)}"
                    )
                payload = response.json()
                items = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(items, list) or not items:
                    raise ProviderError("图片生成服务没有返回结果")

                cost = estimate_cost(self.row, job_type, params) / max(1, len(items))
                results: list[GeneratedMedia] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("b64_json"):
                        data = base64.b64decode(item["b64_json"])
                        mime = "image/png"
                    elif item.get("url"):
                        data, mime = await _download_media(client, str(item["url"]))
                    else:
                        continue
                    results.append(
                        GeneratedMedia(
                            data=data,
                            mime_type=mime,
                            extension=extension_for_mime(mime, "png"),
                            width=width,
                            height=height,
                            cost=round(cost, 4),
                            metadata={"job_type": job_type},
                        )
                    )
                if not results:
                    raise ProviderError("图片生成服务返回的结果无法解析")
                return results
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(f"图片生成服务请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"图片生成服务连接失败: {exc}") from exc


class ComfyUIProvider(BaseProvider):
    """ComfyUI 工作流：提交 workflow → 轮询 history → 下载输出文件。"""

    async def generate(
        self,
        *,
        job_type: str,
        prompt: str,
        negative_prompt: str,
        params: dict,
        input_asset: dict | None = None,
    ) -> list[GeneratedMedia]:
        _check_supported(self, job_type)
        base_url = (self.row.base_url or "").rstrip("/")
        if not base_url:
            raise ProviderError("ComfyUI 生成服务缺少 base_url")

        workflow = self.config.get("workflow")
        if not isinstance(workflow, dict) or not workflow:
            raise ProviderError("ComfyUI 生成服务缺少 workflow 配置")
        workflow = copy.deepcopy(workflow)

        prompt_node = str(self.config.get("prompt_node_id") or "")
        if prompt_node:
            self._set_input(
                workflow, prompt_node, self.config.get("prompt_input", "text"), prompt
            )
        negative_node = str(self.config.get("negative_node_id") or "")
        if negative_node and negative_prompt:
            self._set_input(
                workflow,
                negative_node,
                self.config.get("negative_input", "text"),
                negative_prompt,
            )

        client_id = uuid4().hex
        poll_interval = max(0.5, float(self.config.get("poll_interval") or 1.0))
        deadline = time.monotonic() + self.timeout

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                if job_type == "image_to_video":
                    image_node = str(self.config.get("input_image_node_id") or "")
                    if not image_node:
                        raise ProviderError("ComfyUI 图生视频需要配置 input_image_node_id")
                    image_name = await self._upload_input(client, base_url, input_asset)
                    self._set_input(
                        workflow,
                        image_node,
                        self.config.get("input_image_input", "image"),
                        image_name,
                    )

                response = await client.post(
                    f"{base_url}/prompt",
                    headers=self._headers({"Content-Type": "application/json"}),
                    json={"prompt": workflow, "client_id": client_id},
                )
                if response.status_code >= 400:
                    raise ProviderError(
                        f"ComfyUI 提交任务失败 HTTP {response.status_code}: "
                        f"{_request_error_text(response)}"
                    )
                payload = response.json()
                prompt_id = payload.get("prompt_id") if isinstance(payload, dict) else None
                if not prompt_id:
                    raise ProviderError("ComfyUI 没有返回 prompt_id")

                outputs: dict | None = None
                while time.monotonic() < deadline:
                    history = await client.get(
                        f"{base_url}/history/{prompt_id}", headers=self._headers()
                    )
                    if history.status_code < 400:
                        data = history.json()
                        entry = data.get(prompt_id) if isinstance(data, dict) else None
                        if isinstance(entry, dict):
                            status = entry.get("status") or {}
                            if str(status.get("status_str") or "").lower() == "error":
                                raise ProviderError("ComfyUI 工作流执行失败")
                            outputs = entry.get("outputs") or None
                            if outputs:
                                break
                    await asyncio.sleep(poll_interval)

                if not outputs:
                    raise ProviderError("ComfyUI 生成超时，未获取到输出")
                return await self._collect_outputs(client, base_url, outputs, job_type, params)
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(f"ComfyUI 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"ComfyUI 连接失败: {exc}") from exc

    @staticmethod
    def _set_input(workflow: dict, node_id: str, input_name: str, value) -> None:
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise ProviderError(f"ComfyUI workflow 中不存在节点 {node_id}")
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            raise ProviderError(f"ComfyUI 节点 {node_id} 的 inputs 配置无效")
        inputs[input_name] = value

    async def _upload_input(
        self, client: httpx.AsyncClient, base_url: str, input_asset: dict | None
    ) -> str:
        if not input_asset:
            raise ProviderError("图生视频需要输入图片")
        path = resolve_relative(input_asset.get("storage_path"))
        if path is None or not path.is_file():
            raise ProviderError("图生视频的输入图片不存在")
        files = {
            "image": (
                input_asset.get("file_name") or path.name,
                path.read_bytes(),
                input_asset.get("mime_type") or "image/png",
            )
        }
        response = await client.post(
            f"{base_url}/upload/image",
            headers=self._headers({"Accept": "application/json"}),
            files=files,
            data={"overwrite": "true"},
        )
        if response.status_code >= 400:
            raise ProviderError(
                f"ComfyUI 上传输入图片失败 HTTP {response.status_code}: "
                f"{_request_error_text(response)}"
            )
        payload = response.json()
        name = payload.get("name") if isinstance(payload, dict) else None
        if not name:
            raise ProviderError("ComfyUI 上传输入图片没有返回文件名")
        subfolder = payload.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else str(name)

    async def _collect_outputs(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        outputs: dict,
        job_type: str,
        params: dict,
    ) -> list[GeneratedMedia]:
        results: list[GeneratedMedia] = []
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            for key in ("images", "gifs", "videos"):
                for item in output.get(key) or []:
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue
                    query = (
                        f"filename={quote(str(item['filename']))}"
                        f"&subfolder={quote(str(item.get('subfolder') or ''))}"
                        f"&type={quote(str(item.get('type') or 'output'))}"
                    )
                    data, mime = await _download_media(client, f"{base_url}/view?{query}")
                    results.append(
                        GeneratedMedia(
                            data=data,
                            mime_type=mime,
                            extension=extension_for_mime(
                                mime, Path(str(item["filename"])).suffix.lstrip(".") or "bin"
                            ),
                            duration_seconds=(
                                float(params.get("duration") or 0) or None
                                if job_type != "text_to_image"
                                else None
                            ),
                            cost=0.0,
                            metadata={"comfyui_node": item.get("node"), "job_type": job_type},
                        )
                    )
        if not results:
            raise ProviderError("ComfyUI 输出中没有可下载的媒体文件")
        # 一次工作流只计一次成本，避免多输出文件重复计费
        results[0].cost = estimate_cost(self.row, job_type, params)
        return results


class HttpGenericProvider(BaseProvider):
    """配置驱动的通用 HTTP 适配器。

    ``config`` 示例::

        {
          "create": {"method": "POST", "path": "/v1/generate",
                     "body": {"prompt": "{{prompt}}", "duration": "{{duration}}"}},
          "result_url_path": "data.url",
          "task_id_path": "data.task_id",
          "poll": {"method": "GET", "path": "/v1/tasks/{{task_id}}",
                   "status_path": "data.status",
                   "result_url_path": "data.video_url"}
        }
    """

    async def generate(
        self,
        *,
        job_type: str,
        prompt: str,
        negative_prompt: str,
        params: dict,
        input_asset: dict | None = None,
    ) -> list[GeneratedMedia]:
        _check_supported(self, job_type)
        base_url = (self.row.base_url or "").rstrip("/")
        if not base_url:
            raise ProviderError("通用 HTTP 生成服务缺少 base_url")
        create = self.config.get("create") or {}
        if not isinstance(create, dict):
            raise ProviderError("通用 HTTP 生成服务的 create 配置无效")

        context = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "job_type": job_type,
            "model": self.row.model or "",
            "duration": params.get("duration", 5),
            "size": params.get("size", "1024x1024"),
            "count": params.get("count", 1),
            "seed": params.get("seed", ""),
            "width": params.get("width", ""),
            "height": params.get("height", ""),
            "input_image_url": (input_asset or {}).get("public_url", ""),
        }
        create = _render_obj(create, context)
        method = str(create.get("method") or "POST").upper()
        url = _join_url(base_url, str(create.get("path") or ""))
        headers = self._headers(create.get("headers") or {})
        body = create.get("body")
        query = create.get("params")

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=query,
                    json=body if method not in ("GET", "DELETE") else None,
                )
                if response.status_code >= 400:
                    raise ProviderError(
                        f"生成服务返回 HTTP {response.status_code}: "
                        f"{_request_error_text(response)}"
                    )

                content_type = (response.headers.get("content-type") or "").lower()
                if content_type.startswith(("image/", "video/")):
                    data = response.content
                    mime = content_type.split(";")[0]
                    return [self._media(data, mime, job_type, params, {})]

                payload = _safe_json(response)
                if payload is None:
                    raise ProviderError("生成服务返回了无法解析的响应")

                result_url = _json_path(payload, create.get("result_url_path"))
                task_id = _json_path(payload, create.get("task_id_path"))
                if isinstance(result_url, list):
                    result_url = result_url[0] if result_url else None
                if isinstance(result_url, str) and result_url:
                    data, mime = await _download_media(client, result_url)
                    return [self._media(data, mime, job_type, params, {"remote_url": result_url})]

                if not task_id:
                    raise ProviderError(
                        "生成服务响应缺少结果地址或任务 ID，请检查 result_url_path/task_id_path"
                    )

                result_url = await self._poll(client, base_url, task_id, context)
                data, mime = await _download_media(client, result_url)
                return [
                    self._media(
                        data,
                        mime,
                        job_type,
                        params,
                        {"remote_url": result_url, "task_id": str(task_id)},
                    )
                ]
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(f"生成服务请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"生成服务连接失败: {exc}") from exc

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        task_id,
        context: dict,
    ) -> str:
        poll = self.config.get("poll") or {}
        if not isinstance(poll, dict) or not poll:
            raise ProviderError("生成服务返回了任务 ID，但没有配置 poll 轮询")
        poll = _render_obj(poll, {**context, "task_id": task_id})
        method = str(poll.get("method") or "GET").upper()
        url = _join_url(base_url, str(poll.get("path") or ""))
        headers = self._headers(poll.get("headers") or {})
        interval = max(0.5, float(poll.get("interval") or 2.0))
        success_values = [str(item).lower() for item in poll.get("success_values") or
                          ["succeeded", "success", "completed", "done"]]
        failure_values = [str(item).lower() for item in poll.get("failure_values") or
                          ["failed", "error", "cancelled"]]
        deadline = time.monotonic() + self.timeout

        while time.monotonic() < deadline:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=poll.get("params"),
                json=poll.get("body") if method not in ("GET", "DELETE") else None,
            )
            if response.status_code >= 400:
                raise ProviderError(
                    f"生成任务轮询失败 HTTP {response.status_code}: "
                    f"{_request_error_text(response)}"
                )
            payload = _safe_json(response)
            if payload is None:
                raise ProviderError("生成任务轮询返回了无法解析的响应")
            status = str(_json_path(payload, poll.get("status_path", "status")) or "").lower()
            if status in failure_values:
                message = _json_path(payload, poll.get("message_path", "message")) or status
                raise ProviderError(f"生成任务失败: {message}")
            if status in success_values:
                result_url = _json_path(payload, poll.get("result_url_path"))
                if isinstance(result_url, list):
                    result_url = result_url[0] if result_url else None
                if not result_url:
                    raise ProviderError("生成任务已完成，但没有返回结果地址")
                return str(result_url)
            await asyncio.sleep(interval)

        raise ProviderError("生成任务轮询超时")

    def _media(
        self, data: bytes, mime: str, job_type: str, params: dict, metadata: dict
    ) -> GeneratedMedia:
        return GeneratedMedia(
            data=data,
            mime_type=mime,
            extension=extension_for_mime(mime, "bin"),
            duration_seconds=(
                float(params.get("duration") or 0) or None
                if job_type != "text_to_image"
                else None
            ),
            cost=estimate_cost(self.row, job_type, params),
            metadata={**metadata, "job_type": job_type},
        )


def _join_url(base_url: str, path: str) -> str:
    if not path:
        return base_url
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(f"{base_url}/", path.lstrip("/"))


def _safe_json(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return None


def _json_path(data, path: str | None):
    if not path:
        return None
    current = data
    for part in str(path).split("."):
        if not part:
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _render_obj(value, context: dict):
    if isinstance(value, dict):
        return {key: _render_obj(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_obj(item, context) for item in value]
    if isinstance(value, str):
        match = PLACEHOLDER_RE.fullmatch(value.strip())
        if match:
            return context.get(match.group(1))
        return PLACEHOLDER_RE.sub(
            lambda item: str(context.get(item.group(1), item.group(0))), value
        )
    return value


PROVIDER_REGISTRY = {
    "mock": MockProvider,
    "openai_image": OpenAIImageProvider,
    "comfyui": ComfyUIProvider,
    "http_generic": HttpGenericProvider,
}


async def test_provider_connection(row) -> dict:
    """轻量连通性检测，不触发真实生成。"""
    started = time.monotonic()
    if (row.provider_type or "mock") == "mock":
        return {
            "ok": True,
            "message": "内置 Mock 生成服务可用",
            "status_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    base_url = (row.base_url or "").rstrip("/")
    if not base_url:
        return {
            "ok": False,
            "message": "缺少 base_url",
            "status_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    try:
        provider = build_provider(row)
    except ProviderError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "status_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    probe_url = base_url
    if row.provider_type == "comfyui":
        probe_url = f"{base_url}/system_stats"
    elif row.provider_type == "openai_image":
        probe_url = f"{base_url}/models"

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(probe_url, headers=provider._headers())
    except httpx.TimeoutException as exc:
        return {
            "ok": False,
            "message": f"连接超时: {exc}",
            "status_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "message": f"连接失败: {exc}",
            "status_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    latency = int((time.monotonic() - started) * 1000)
    status = response.status_code
    if status < 400:
        ok, message = True, f"服务可达（HTTP {status}）"
    elif status in (401, 403):
        ok, message = False, f"服务可达但鉴权失败（HTTP {status}）"
    elif status == 404 and row.provider_type == "http_generic":
        ok, message = True, "服务可达（根路径 404）"
    else:
        ok, message = False, f"服务返回 HTTP {status}"
    return {"ok": ok, "message": message, "status_code": status, "latency_ms": latency}
