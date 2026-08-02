"""证据卡生成模块。

实现要求（文档15 §7.14）：
1. 代码先生成结构化簇摘要和分数
2. 只把簇内允许引用的反馈传给模型
3. 代码验证所有引用 ID 都属于该簇
4. 每条核心发现至少一个 feedback_id
5. URL 由代码附加，不允许模型编 URL
6. 证据卡默认 human_review_status=pending
"""

from __future__ import annotations

from ridepulse.models import EvidenceCard


def generate_cards(clusters: list, records_by_id: dict, client=None) -> list[EvidenceCard]:
    raise NotImplementedError("8月8日实现")


def validate_citation(card: EvidenceCard, cluster_members: set[str]) -> list[str]:
    """验证证据卡引用的 ID 是否都在簇内，返回违规 ID 列表。"""
    raise NotImplementedError("8月8日实现")
