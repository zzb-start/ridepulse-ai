"""去重模块 — 两层去重。

实现要求（文档15 §7.6）：
第一层: SHA-256 精确指纹 (normalized_text + brand + product_model)
第二层: 字符 3-gram TF-IDF 余弦相似度，阈值默认 0.92
- 只标记 duplicate_group_id，不自动删除
- 来源不同但文本相同的转载，保留来源，评分时降低独立性
"""

from __future__ import annotations


def exact_fingerprint(normalized_text: str, brand: str, product_model: str | None) -> str:
    raise NotImplementedError("8月4日实现")


def near_duplicate_groups(records: list[dict], threshold: float = 0.92) -> dict[str, str]:
    """返回 {feedback_id: duplicate_group_id}。"""
    raise NotImplementedError("8月4日实现")
