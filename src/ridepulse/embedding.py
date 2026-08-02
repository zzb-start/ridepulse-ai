"""Embedding 模块 — 三种模式。

实现要求（文档15 §7.11）：
1. api: 正式模式（OpenAI 兼容 Embedding API）
2. local: 备用（多语言 sentence-transformers）
3. fake: 仅测试（按文本哈希生成确定性向量，不得用于比赛指标）

输入文本组合: [品牌] [产品型号] [主题] [场景] [原文或译文]
要求：缓存向量避免重复计费；记录模型名和维度。
"""

from __future__ import annotations


def embed(texts: list[str], mode: str = "fake", model: str = "") -> list[list[float]]:
    """返回文本向量列表。"""
    raise NotImplementedError("8月7日实现")


def fake_embed(text: str, dimension: int = 64) -> list[float]:
    """确定性假向量（测试用）。"""
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:dimension]]
