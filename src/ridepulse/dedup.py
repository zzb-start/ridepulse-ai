"""去重模块 — 两层去重。

实现要求：
第一层: SHA-256 精确指纹 (normalized_text + brand + product_model)
第二层: 字符 3-gram TF-IDF 余弦相似度，阈值默认 0.92
- 只标记 duplicate_group_id，不自动删除
- 来源不同但文本相同的转载，保留来源，评分时降低独立性
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from ridepulse.normalize import normalize_text


def exact_fingerprint(normalized_text: str, brand: str, product_model: str | None) -> str:
    """确定性精确指纹：SHA-256(normalized_text | brand | product_model)。

    product_model 的 None 与空串视为等价。
    """
    payload = f"{normalized_text}\x1f{brand}\x1f{product_model or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compare_text(text: str) -> str:
    """去重比对专用文本：规范化 + 大小写折叠，不影响存储原文。"""
    return normalize_text(text).casefold()


def near_duplicate_groups(records: list[dict], threshold: float = 0.92) -> dict[str, str]:
    """近似重复分组，返回 {feedback_id: duplicate_group_id}。

    - 只给 >=2 成员的组分配 duplicate_group_id（格式 DG-0001），单例不返回
    - 记录须含 feedback_id 与 original_text 键
    - 相同文本（含大小写/空白差异）余弦相似度为 1.0，必然同组；
      共享少量常用词但问题不同的记录因阈值 0.92 而保持独立
    """
    if not records:
        return {}

    items = [
        (rec["feedback_id"], _compare_text(rec.get("original_text", "")))
        for rec in records
        if rec.get("feedback_id") is not None and rec.get("original_text")
    ]
    if not items:
        return {}

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    ids = [item[0] for item in items]
    texts = [item[1] for item in items]

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3))
    matrix = vectorizer.fit_transform(texts)
    similarity = cosine_similarity(matrix)

    # 并查集：相似度 >= 阈值的记录合并为同一组
    parent = list(range(len(ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            if similarity[i][j] >= threshold:
                union(i, j)

    members: dict[int, list[str]] = defaultdict(list)
    for idx, fid in enumerate(ids):
        members[find(idx)].append(fid)

    result: dict[str, str] = {}
    # 按组内最小 ID 排序，保证组号确定
    for order, (_, member_ids) in enumerate(
        sorted(members.items(), key=lambda kv: min(kv[1])), start=1
    ):
        if len(member_ids) < 2:
            continue
        group_id = f"DG-{order:04d}"
        for fid in member_ids:
            result[fid] = group_id
    return result
