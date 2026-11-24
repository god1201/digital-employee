"""Embedding：外部 OpenAI 兼容接口 + 本地哈希向量回退。"""

import hashlib
import logging
import math
import re

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RE = re.compile(r"[一-鿿]+")


def is_external_configured() -> bool:
    # 仅显式配置 EMBEDDING_API_KEY 时才走外部 Embedding；
    # DeepSeek 的 Key 只用于对话，不用于 embeddings。
    return bool(settings.embedding_api_key)


def _features(text: str) -> list[str]:
    lowered = text.lower()
    features = _WORD_RE.findall(lowered)
    for sequence in _CJK_RE.findall(lowered):
        features.append(sequence)
        features.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return features


def local_embed(text: str, dim: int | None = None) -> list[float]:
    """确定性本地哈希向量，无外部 API 也能做向量检索。"""
    dimension = max(32, int(dim or settings.embedding_dim))
    vector = [0.0] * dimension
    for token in _features(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dimension
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _endpoint() -> str:
    base = (
        settings.embedding_base_url or settings.llm_base_url or "https://api.openai.com/v1"
    ).rstrip("/")
    return f"{base}/embeddings"


def _api_key() -> str:
    return settings.embedding_api_key


async def _external_embed(texts: list[str]) -> list[list[float]]:
    key = _api_key()
    if not key:
        raise RuntimeError("未配置 Embedding API Key")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    vectors: list[list[float]] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            response = await client.post(
                _endpoint(),
                headers=headers,
                json={"model": settings.embedding_model, "input": batch},
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Embedding 调用失败（{response.status_code}）: {response.text[:200]}"
                )
            data = response.json()
            items = data.get("data") or []
            items.sort(key=lambda item: item.get("index", 0))
            for item in items:
                vector = item.get("embedding")
                if not isinstance(vector, list):
                    raise RuntimeError("Embedding 返回结构异常")
                vectors.append([float(value) for value in vector])

    if len(vectors) != len(texts):
        raise RuntimeError("Embedding 返回数量不匹配")
    return vectors


async def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    if not texts:
        return [], "none"

    if is_external_configured():
        try:
            return await _external_embed(texts), settings.embedding_model
        except Exception as exc:  # noqa: BLE001
            logger.warning("外部 Embedding 失败，回退本地哈希向量: %s", exc)

    if settings.local_embedding_enabled:
        return [local_embed(text) for text in texts], "local-hash"

    return [[] for _ in texts], "none"
