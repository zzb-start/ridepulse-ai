"""Embedding 模块 — 三种模式。

实现要求（文档15 §7.11）：
1. api: 正式模式（OpenAI 兼容 Embedding API）
2. local: 备用（多语言 sentence-transformers）
3. fake: 仅测试（按文本哈希生成确定性向量，不得用于比赛指标）

输入文本组合: [品牌] [产品型号] [主题] [场景] [原文或译文]
要求：缓存向量避免重复计费；记录模型名和维度。
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from typing import Any

import httpx

from ridepulse.config import Config, get_config

logger = logging.getLogger(__name__)

# 内存缓存: (text_hash, model) -> vector。避免同一文本重复计费。
_CACHE: dict[tuple[str, str], list[float]] = {}


class EmbeddingError(Exception):
    """Embedding 调用失败。"""


def fake_embed(text: str, dimension: int = 64) -> list[float]:
    """确定性假向量（测试用）——不得用于比赛指标。

    以文本 SHA-256 为随机种子生成 [-1, 1) 均匀分布向量：
    - 同一文本 -> 同一向量（相似度 1，必合并）
    - 不同文本 -> 近似正交（余弦相似度≈0，0.5 距离阈值下独立）
    直接截断 digest 的旧实现只有 32 维且不同文本相似度过高，已废弃。
    """
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dimension)]


def _compose_text(record: dict, classification: dict | None) -> str:
    """组合 Embedding 输入文本: [品牌] [产品型号] [主题] [场景] [原文或译文]。"""
    parts = [record.get("brand") or ""]
    if record.get("product_model"):
        parts.append(str(record["product_model"]))
    if classification:
        theme = classification.get("theme_primary")
        parts.append(theme.value if hasattr(theme, "value") else str(theme or ""))
        scenario = classification.get("scenario")
        if scenario and str(scenario) != "unknown":
            parts.append(scenario.value if hasattr(scenario, "value") else str(scenario))
    text = record.get("translated_text") or record.get("original_text") or ""
    parts.append(str(text))
    return " | ".join(part for part in parts if part)


class ApiEmbedder:
    """OpenAI 兼容 /embeddings 接口客户端（正式模式）。"""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = 60, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.usage_log: list[dict[str, Any]] = []
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。若配置了 embedding 维度则按块请求，保证响应一致。"""
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            batch = texts[i:i + 32]
            out.extend(self._embed_batch(batch))
        return out

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        attempts = 0
        while True:
            attempts += 1
            try:
                resp = self._client.post(
                    "/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": texts},
                )
                status = resp.status_code
                if status == 429 or status >= 500:
                    if attempts <= self.max_retries:
                        import time
                        time.sleep(min(0.5 * (2 ** (attempts - 1)), 5.0))
                        continue
                    raise EmbeddingError(f"Embedding 服务错误（HTTP {status}），重试耗尽")
                if status >= 400:
                    raise EmbeddingError(f"Embedding 请求被拒绝（HTTP {status}）: {resp.text[:200]}")
                data = resp.json()
                rows = sorted(data["data"], key=lambda row: row["index"])
                vectors = [row["embedding"] for row in rows]
                if not vectors:
                    raise EmbeddingError("Embedding 响应为空")
                self.usage_log.append({
                    "model": self.model,
                    "status": "success",
                    "count": len(vectors),
                    "attempts": attempts,
                })
                return vectors
            except httpx.TimeoutException as exc:
                if attempts <= self.max_retries:
                    import time
                    time.sleep(min(0.5 * (2 ** (attempts - 1)), 5.0))
                    continue
                raise EmbeddingError("Embedding 调用超时") from exc
            except httpx.RequestError as exc:
                raise EmbeddingError(f"Embedding 连接失败: {exc}") from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise EmbeddingError(f"Embedding 响应格式异常: {exc}") from exc


class LocalEmbedder:
    """备用模式：多语言 sentence-transformers。"""

    def __init__(self, model: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self.model = model
        self._encoder = None

    def _load(self) -> Any:
        if self._encoder is None:
            # 必须在 import torch 之前设置（Windows 上缺失会卡死在 OpenMP 初始化）
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
            # 模型已在本地缓存时离线加载，避免直连 huggingface.co 超时
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "local 模式需要安装 sentence-transformers: "
                    "pip install sentence-transformers"
                ) from exc
            self._encoder = SentenceTransformer(self.model)
        return self._encoder

    def embed(self, texts: list[str]) -> list[list[float]]:
        encoder = self._load()
        vectors = encoder.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]


def embed_texts(texts: list[str], *, mode: str = "fake", model: str = "",
                dimension: int = 64, api_client: ApiEmbedder | None = None) -> list[list[float]]:
    """对一批文本做向量化，返回与输入同序的向量列表。

    - fake: 确定性哈希向量（仅测试/开发，不得用于比赛指标）
    - api: 使用 ApiEmbedder（未传入时按 Config 构造）
    - local: 使用 sentence-transformers
    """
    if mode == "fake":
        return [fake_embed(text, dimension) for text in texts]
    if mode == "local":
        return LocalEmbedder(model=model or "paraphrase-multilingual-MiniLM-L12-v2").embed(texts)
    if mode == "api":
        client = api_client or _build_api_embedder()
        cached: list[list[float]] = []
        missing: list[int] = []
        missing_texts: list[str] = []
        for idx, text in enumerate(texts):
            key = (hashlib.sha256(text.encode("utf-8")).hexdigest(), client.model)
            if key in _CACHE:
                cached.append(_CACHE[key])
            else:
                cached.append([])
                missing.append(idx)
                missing_texts.append(text)
        if missing_texts:
            fresh = client.embed(missing_texts)
            for idx, vector in zip(missing, fresh):
                key = (hashlib.sha256(texts[idx].encode("utf-8")).hexdigest(), client.model)
                _CACHE[key] = vector
                cached[idx] = vector
        return cached
    raise ValueError(f"未知 embedding 模式: {mode}（可选 api / local / fake）")


def _build_api_embedder(config: Config | None = None) -> ApiEmbedder:
    """按全局配置构造正式模式客户端。"""
    config = config or get_config()
    if not (config.llm_base_url and config.llm_api_key):
        raise EmbeddingError(
            "api 模式需要 LLM_BASE_URL 与 LLM_API_KEY（Embedding 走同一 OpenAI 兼容接口）"
        )
    model = config.embedding_model or config.llm_primary_model
    if not model:
        raise EmbeddingError("api 模式需要 EMBEDDING_MODEL 或 LLM_PRIMARY_MODEL")
    return ApiEmbedder(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=model,
        timeout_seconds=config.llm_timeout_seconds,
        max_retries=config.llm_max_retries,
    )


def embed_records(records: list, classifications: dict[str, Any] | None = None,
                  *, mode: str = "fake", model: str = "", dimension: int = 64,
                  api_client: ApiEmbedder | None = None) -> dict[str, list[float]]:
    """对反馈记录做向量化，返回 {feedback_id: vector}。

    records: FeedbackRecord 列表（或其 model_dump() 字典列表）
    classifications: {feedback_id: ClassificationResult}，用于组合主题/场景
    """
    items = []
    for record in records:
        data = record.model_dump() if hasattr(record, "model_dump") else record
        classification = None
        if classifications:
            classification = classifications.get(data["feedback_id"])
            if hasattr(classification, "model_dump"):
                classification = classification.model_dump()
        items.append((data, classification))

    texts = [_compose_text(data, classification) for data, classification in items]
    vectors = embed_texts(texts, mode=mode, model=model, dimension=dimension,
                          api_client=api_client)
    return {data["feedback_id"]: vector for (data, _), vector in zip(items, vectors)}
