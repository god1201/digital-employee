"""多模态解析：本地文本/CSV/JSON + 可选 HTTP OCR/ASR/PDF Provider。"""

import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestError

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
PDF_EXTS = {".pdf"}
TABLE_EXTS = {".csv", ".tsv"}


def detect_kind(filename: str, content_type: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower()
    content = (content_type or "").lower()
    if ext in IMAGE_EXTS or content.startswith("image/"):
        return "image"
    if ext in AUDIO_EXTS or content.startswith("audio/"):
        return "audio"
    if ext in PDF_EXTS or content == "application/pdf":
        return "pdf"
    if ext in TABLE_EXTS or content in {"text/csv", "text/tab-separated-values"}:
        return "table"
    return "text"


def parse_table(text: str, filename: str = "") -> list[list[str]]:
    delimiter = "\t" if filename.lower().endswith(".tsv") else ","
    rows: list[list[str]] = []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for index, row in enumerate(reader):
        if index >= 200:
            break
        rows.append([str(cell)[:500] for cell in row])
    return rows


def local_extract(filename: str, content_type: str | None, data: bytes) -> dict:
    kind = detect_kind(filename, content_type)
    if kind in {"image", "audio", "pdf"}:
        raise BadRequestError(
            f"{kind} 文件需要配置 MULTIMODAL_PROVIDER_URL 才能解析"
        )
    text = data.decode("utf-8", errors="replace")
    tables: list[list[str]] = []
    meta: dict = {"size": len(data)}
    if kind == "table":
        tables = parse_table(text, filename)
        meta["rows"] = len(tables)
    elif kind == "text" and filename.lower().endswith(".json"):
        try:
            parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
            meta["json"] = True
        except json.JSONDecodeError:
            meta["json"] = False
    return {
        "kind": kind,
        "text": text,
        "tables": tables,
        "provider": "local",
        "meta": meta,
    }


async def provider_extract(
    filename: str,
    content_type: str | None,
    data: bytes,
) -> dict:
    url = settings.multimodal_provider_url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BadRequestError("MULTIMODAL_PROVIDER_URL 必须是 http(s) 地址")
    kind = detect_kind(filename, content_type)
    headers = {}
    if settings.multimodal_provider_api_key:
        headers["Authorization"] = f"Bearer {settings.multimodal_provider_api_key}"
    files = {
        "file": (filename or "upload.bin", data, content_type or "application/octet-stream")
    }
    try:
        async with httpx.AsyncClient(timeout=settings.multimodal_timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                files=files,
                data={"kind": kind},
            )
    except httpx.HTTPError as exc:
        raise BadRequestError(f"多模态 Provider 不可达: {exc}") from exc
    if response.status_code >= 400:
        raise BadRequestError(
            f"多模态 Provider 返回 {response.status_code}: {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise BadRequestError("多模态 Provider 未返回 JSON") from exc
    text = str(payload.get("text") or "")
    if not text:
        raise BadRequestError("多模态 Provider 未返回 text")
    return {
        "kind": kind,
        "text": text,
        "tables": payload.get("tables") or [],
        "provider": "http",
        "meta": payload.get("meta") or {},
    }


async def extract(
    filename: str, content_type: str | None, data: bytes
) -> dict:
    if len(data) > settings.multimodal_max_bytes:
        raise BadRequestError(
            f"文件超过上限 {settings.multimodal_max_bytes} 字节"
        )
    kind = detect_kind(filename, content_type)
    if kind in {"image", "audio", "pdf"}:
        if not settings.multimodal_provider_url:
            raise BadRequestError(
                f"{kind} 文件需要配置 MULTIMODAL_PROVIDER_URL"
            )
        return await provider_extract(filename, content_type, data)
    return local_extract(filename, content_type, data)
