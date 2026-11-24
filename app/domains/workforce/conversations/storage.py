"""对话附件私有存储：按租户/会话落盘，仅通过鉴权接口下载。"""

from pathlib import Path
from uuid import uuid4

from app.core.config import settings

TEXT_EXTENSIONS = {"txt", "md", "markdown", "csv", "json", "log", "yaml", "yml"}
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | {
    "pdf",
    "docx",
    "xlsx",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
}


def storage_root() -> Path:
    root = Path(settings.chat_attachment_dir).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root


def ensure_storage_root() -> Path:
    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lstrip(".").lower()
    return suffix if suffix in ALLOWED_EXTENSIONS else ""


def save_attachment(
    tenant_id: int, conversation_id: int, data: bytes, extension: str
) -> str:
    relative = (
        f"{tenant_id}/{conversation_id}/{uuid4().hex}.{extension}"
        if extension
        else f"{tenant_id}/{conversation_id}/{uuid4().hex}"
    )
    target = ensure_storage_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative


def resolve_attachment(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    root = storage_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def delete_attachment(relative_path: str | None) -> bool:
    path = resolve_attachment(relative_path)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def extract_text(data: bytes, extension: str) -> str:
    if extension not in TEXT_EXTENSIONS:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    text = text.strip()
    limit = settings.chat_attachment_text_limit
    if len(text) > limit:
        text = text[:limit] + "\n…（附件内容已截断）"
    return text
