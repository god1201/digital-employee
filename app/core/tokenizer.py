"""Token 计量：优先 tiktoken，缺失时按中英文字符比例保守估算。

- 提示词预算使用与目标模型一致的编码器，避免“按字符截断”导致真实超限；
- 未安装 tiktoken 时保持确定性回退，不影响启动；
- 任务步骤的 Token 仍以 LLM 返回的 usage 为准，此处只负责提示词侧计量。
"""

import logging
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)

try:  # 可选依赖：pip install ".[tokenizer]"
    import tiktoken
except ImportError:  # pragma: no cover - 取决于部署环境
    tiktoken = None


@lru_cache(maxsize=16)
def _encoding(model: str | None):
    if tiktoken is None:
        return None
    name = (model or settings.llm_model or "gpt-4o-mini").strip()
    try:
        return tiktoken.encoding_for_model(name)
    except Exception:  # noqa: BLE001 - 未知模型/离线缺缓存都回退
        logger.debug("tiktoken 无模型编码器: %s", name)
    for candidate in ("o200k_base", "cl100k_base"):
        try:
            return tiktoken.get_encoding(candidate)
        except Exception:  # noqa: BLE001 - 离线且无缓存时回退启发式
            logger.debug("tiktoken 编码器不可用: %s", candidate)
    return None


def heuristic_tokens(text: str) -> int:
    """无 tokenizer 时的保守估算：CJK 1.5 字符/token，其他 4 字符/token。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        code = ord(char)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7AF
        ):
            cjk += 1
        else:
            other += 1
    return max(1, int(cjk / 1.5 + other / 4))


def count_tokens(text: str, *, model: str | None = None) -> int:
    if not text:
        return 0
    encoding = _encoding(model)
    if encoding is not None:
        try:
            return max(1, len(encoding.encode(text, disallowed_special=())))
        except Exception:  # noqa: BLE001
            logger.debug("tiktoken 计数失败，回退启发式", exc_info=True)
    return heuristic_tokens(text)


def tokenizer_backend() -> str:
    return "tiktoken" if _encoding(None) is not None else "heuristic"
