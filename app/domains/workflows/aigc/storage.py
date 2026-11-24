"""AIGC 素材本地存储。

文件按 ``{tenant_id}/{YYYYMM}/{uuid}.{ext}`` 落盘，通过 ``/media`` 静态目录对外提供。
生产环境可替换为对象存储；这里保持一个清晰的本地实现。
"""

import mimetypes
from pathlib import Path
from uuid import uuid4

from app.core.base import utcnow
from app.core.config import settings

MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/avif": "avif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-m4v": "m4v",
    "video/mpeg": "mpeg",
}

EXTENSION_MIMES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "avif": "image/avif",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "m4v": "video/x-m4v",
    "mpeg": "video/mpeg",
    "mpg": "video/mpeg",
}

IMAGE_MIMES = {mime for mime in MIME_EXTENSIONS if mime.startswith("image/")}


def storage_root() -> Path:
    root = Path(settings.aigc_storage_dir).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root


def ensure_storage_root() -> Path:
    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def extension_for_mime(mime_type: str | None, fallback: str = "bin") -> str:
    if mime_type:
        normalized = mime_type.split(";")[0].strip().lower()
        if normalized in MIME_EXTENSIONS:
            return MIME_EXTENSIONS[normalized]
    return fallback


def mime_for_path(path: str | None) -> str:
    if not path:
        return "application/octet-stream"
    suffix = Path(path).suffix.lstrip(".").lower()
    if suffix in EXTENSION_MIMES:
        return EXTENSION_MIMES[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def asset_type_for_mime(mime_type: str) -> str:
    return "video" if mime_type.startswith("video/") else "image"


def _public_prefix() -> str:
    prefix = settings.aigc_public_prefix.strip() or "/media"
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return prefix.rstrip("/")


def public_url_for(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"{_public_prefix()}/{normalized}"


def save_bytes(tenant_id: int, data: bytes, extension: str) -> tuple[str, str]:
    """保存二进制内容，返回 (相对路径, 公开 URL)。"""
    root = ensure_storage_root()
    safe_extension = "".join(ch for ch in extension.lower() if ch.isalnum()) or "bin"
    now = utcnow()
    relative = f"{tenant_id}/{now:%Y%m}/{uuid4().hex}.{safe_extension}"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, public_url_for(relative)


def resolve_relative(relative_path: str | None) -> Path | None:
    """把数据库中的相对路径安全地解析到存储根目录内，阻止路径穿越。"""
    if not relative_path:
        return None
    root = storage_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def delete_stored(relative_path: str | None) -> bool:
    target = resolve_relative(relative_path)
    if target is None or not target.is_file():
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True


def safe_upload_extension(filename: str | None, content_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lstrip(".").lower()
        if 1 < len(suffix) <= 5 and suffix.isalnum() and suffix in EXTENSION_MIMES:
            return suffix
    return extension_for_mime(content_type, fallback="png")
