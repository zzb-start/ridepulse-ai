"""聚类模块。

实现要求（文档15 §7.12）：
1. 先按一级主题分桶，桶内语义聚类
2. 记录噪声点，不强行归类
3. 小于 3 条的簇保留但置信度低
4. 固定随机种子，结果可复现（使用无随机性的确定性算法）
5. 按 source_record_id 去重计数，不重复抬高频次
"""

from __future__ import annotations

import logging
from collections import defaultdict
from urllib.parse import urlparse

from ridepulse.models import (
    ClusterInfo,
    ClassificationResult,
    FeedbackRecord,
    Severity,
    ThemePrimary,
)

logger = logging.getLogger(__name__)

# 桶内聚类余弦距离阈值（1 - 余弦相似度）
DEFAULT_DISTANCE_THRESHOLD = 0.5
# 小于该成员数的簇标记低置信度（由下游评分使用）
SMALL_CLUSTER_SIZE = 3


def _domain(url: str) -> str:
    """URL 域名（不含 www 前缀），用于独立域名计数。"""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return url
    if host.startswith("www."):
        host = host[4:]
    return host


def _cluster_within_bucket(items: list[dict], vectors: dict[str, list[float]],
                           *, distance_threshold: float) -> list[list[str]]:
    """桶内语义聚类，返回 [成员 feedback_id 列表, ...]。

    - 成员数 < 2 时直接单例，不进模型（避免随机性）
    - 使用确定性 AgglomerativeClustering（cosine 距离、average 链接），
      结果仅取决于向量本身，天然可复现
    """
    fids = [item["feedback_id"] for item in items]
    if len(fids) < 2:
        return [[fid] for fid in fids]

    vecs = [vectors.get(fid) for fid in fids]
    if any(v is None for v in vecs):
        missing = [fid for fid, v in zip(fids, vecs) if v is None]
        logger.warning("缺少向量的记录按独立簇处理: %s", missing)
        return [[fid] for fid in fids]

    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
    ).fit_predict(vecs)

    groups: dict[int, list[str]] = defaultdict(list)
    for fid, label in zip(fids, labels):
        groups[int(label)].append(fid)
    return list(groups.values())


def _max_severity(severities: list[Severity]) -> Severity:
    """按严重度序取最高（S1 最高）。"""
    if not severities:
        return Severity.S5
    order = {sev: i for i, sev in enumerate(Severity)}
    return min(severities, key=lambda sev: order[sev])


def _time_range_days(dates: list) -> int | None:
    """时间跨度（天）；任一端缺失则返回 None。"""
    valid = [d for d in dates if d is not None]
    if len(valid) < 2:
        return None
    return (max(valid) - min(valid)).days


def cluster_feedback(records: list, vectors: dict[str, list[float]],
                     classifications: dict[str, ClassificationResult] | None = None,
                     *, seed: int = 42,
                     distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD) -> list[ClusterInfo]:
    """对反馈进行聚类，返回 ClusterInfo 列表。

    records: FeedbackRecord 列表
    vectors: {feedback_id: vector}（由 embedding.embed_records 产生）
    classifications: {feedback_id: ClassificationResult}，提供主题/严重度；
        缺省时退化为仅按 source_record_id 计数（主题 unknown）。
    seed: 保留参数，保证接口兼容；算法本身无随机性。
    """
    classes: dict[str, ClassificationResult] = classifications or {}

    # 1. 按一级主题分桶
    buckets: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        classification = classes.get(record.feedback_id)
        theme = classification.theme_primary.value if classification else ThemePrimary.OTHER.value
        buckets[theme].append(
            {
                "feedback_id": record.feedback_id,
                "theme": theme,
                "source_record_id": record.source_record_id,
                "severity": classification.severity if classification else None,
                "platform": record.source_platform,
                "domain": _domain(record.source_url),
                "language": record.language,
                "brand": record.brand,
                "source_date": record.source_date,
            }
        )

    # 2. 桶内语义聚类
    all_clusters: list[list[dict]] = []
    for theme in sorted(buckets):
        bucket_items = sorted(buckets[theme], key=lambda item: item["feedback_id"])
        member_groups = _cluster_within_bucket(bucket_items, vectors, distance_threshold=distance_threshold)
        for group in member_groups:
            all_clusters.append([item for item in bucket_items if item["feedback_id"] in group])

    # 3. 确定性排序：按首成员 feedback_id，避免顺序不稳定
    all_clusters.sort(key=lambda group: min(item["feedback_id"] for item in group))

    result: list[ClusterInfo] = []
    for order, members in enumerate(all_clusters, start=1):
        source_records = {item["source_record_id"] for item in members}
        domains = {item["domain"] for item in members}
        platforms = {item["platform"] for item in members}
        languages = {item["language"] for item in members}
        brands = {item["brand"] for item in members}
        severities = [item["severity"] for item in members if item["severity"] is not None]
        dates = [item["source_date"] for item in members]
        theme = members[0]["theme"]

        # 噪声点判定：主题桶内未与任何其他记录合并（单一成员）
        is_noise = len(members) == 1 and len(buckets.get(theme, [])) > 1

        result.append(
            ClusterInfo(
                cluster_id=f"CL-{order:04d}",
                member_feedback_ids=[item["feedback_id"] for item in members],
                unique_source_record_count=len(source_records),
                unique_domain_count=len(domains),
                platform_count=len(platforms),
                language_count=len(languages),
                brand_count=len(brands),
                max_severity=_max_severity(severities),
                time_range_days=_time_range_days(dates),
                is_noise=is_noise,
                theme_primary=ThemePrimary(theme) if theme in ThemePrimary._value2member_map_ else None,
            )
        )
    return result
