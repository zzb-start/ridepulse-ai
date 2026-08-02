"""评测模块 — 模型与双人标注的对比指标。

指标（文档15 §10）：
- 每个分类字段准确率 / Macro F1
- severity 加权 Kappa
- 低置信度召回率 / 冲突门控召回率
- 人工复核率
"""

from __future__ import annotations


def cohens_kappa(a: list, b: list) -> float:
    """Cohen's Kappa（分类一致性）。"""
    raise NotImplementedError("8月12日实现")


def weighted_kappa(a: list, b: list, weights: str = "linear") -> float:
    """加权 Kappa（用于 severity 等有序分类）。"""
    raise NotImplementedError("8月12日实现")
