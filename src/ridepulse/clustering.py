"""聚类模块。

实现要求（文档15 §7.12）：
1. 先按一级主题分桶，桶内语义聚类
2. 记录噪声点，不强行归类
3. 小于 3 条的簇保留但置信度低
4. 固定随机种子，结果可复现
5. 按 source_record_id 去重计数，不重复抬高频次
"""

from __future__ import annotations

from ridepulse.models import ClusterInfo


def cluster_feedback(records: list, vectors: list[list[float]], *, seed: int = 42) -> list[ClusterInfo]:
    """对反馈进行聚类，返回 ClusterInfo 列表。"""
    raise NotImplementedError("8月7日实现")
