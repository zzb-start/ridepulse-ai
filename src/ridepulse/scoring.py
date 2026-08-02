"""确定性优先级评分模块 — 分数完全由代码计算，模型不参与。

评分维度（文档15 §7.13，总分100）：
证据质量15 + 独立复现20 + 频次15 + 严重度20 + 可行动性15 + 购买影响15
含惩罚项与 P0-P3 / high-medium-low 判定。
"""

from __future__ import annotations


def score_cluster(cluster: dict, *, unresolved_conflicts: int = 0) -> dict:
    """计算需求簇分数，返回 {priority_score, priority_level, confidence_level, ...}。"""
    raise NotImplementedError("8月7日实现")
