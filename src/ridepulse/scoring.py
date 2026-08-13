"""确定性优先级评分模块 — 分数完全由代码计算，模型不参与。

评分维度（文档15 §7.13，总分100）：
证据质量15 + 独立复现20 + 频次15 + 严重度20 + 可行动性15 + 购买影响15
含惩罚项与 P0-P3 / high-medium-low 判定。
"""

from __future__ import annotations

from ridepulse.models import (
    ClusterInfo,
    EvidenceStatus,
    PurchaseImpact,
    PURCHASE_IMPACT_SCORE,
    SEVERITY_SCORE,
    Severity,
)

# 独立复现维度：按去重后独立用户数分档
REPRODUCTION_TIERS = [(1, 4), (2, 8), (3, 12), (4, 16), (5, 20)]
# 频次维度：同一档位
FREQUENCY_TIERS = [(1, 3), (2, 6), (3, 9), (4, 12), (5, 15)]

# 惩罚项
PENALTY_SINGLE_PLATFORM = 5        # 证据集中单一平台
PENALTY_NOISE = 10                 # 噪声点
PENALTY_UNVERIFIED_PER_MEMBER = 2  # 每条未核验证据
PENALTY_UNVERIFIED_CAP = 6
PENALTY_CONFLICT_PER_ITEM = 3      # 每个未解决冲突
PENALTY_CONFLICT_CAP = 9


def _tier_score(count: int, tiers: list[tuple[int, int]]) -> int:
    """按档位取分数（超出上限取最高档）。"""
    for threshold, score in tiers:
        if count <= threshold:
            return score
    return tiers[-1][1]


def _evidence_quality(members: list[dict]) -> int:
    """证据质量 0-15：verified 计 1 分，partially_verified 计 0.5 分。"""
    if not members:
        return 0
    total = 0.0
    for member in members:
        status = member.get("evidence_status")
        if status == EvidenceStatus.VERIFIED:
            total += 1.0
        elif status == EvidenceStatus.PARTIALLY_VERIFIED:
            total += 0.5
    return int(round((total / len(members)) * 15))


def _severity_score(cluster: ClusterInfo) -> int:
    """严重度 0-20：按簇内最高严重度映射（S1=20 ... S5=2）。"""
    return SEVERITY_SCORE.get(cluster.max_severity, 2)


def _actionability(members: list[dict]) -> int:
    """可行动性 0-15：簇内可行动证据占比。"""
    if not members:
        return 0
    actionable = sum(1 for member in members if member.get("is_actionable"))
    return int(round((actionable / len(members)) * 15))


def _purchase_impact(members: list[dict]) -> int:
    """购买影响 0-15：存在 blocker 计满，否则有 influence 计 8。"""
    scores = [
        PURCHASE_IMPACT_SCORE.get(member.get("purchase_impact", PurchaseImpact.UNKNOWN), 0)
        for member in members
    ]
    if not scores:
        return 0
    return max(scores)


def score_cluster(cluster: ClusterInfo, *, members: list[dict],
                  unresolved_conflicts: int = 0) -> dict:
    """计算需求簇分数，返回 {priority_score, priority_level, confidence_level, ...}。

    cluster: ClusterInfo（含计数与最高严重度）
    members: 簇内成员摘要列表，每项含 evidence_status / is_actionable / purchase_impact
    unresolved_conflicts: 未解决分类冲突数（惩罚项输入）
    """
    evidence_quality = _evidence_quality(members)
    reproduction = _tier_score(cluster.unique_source_record_count, REPRODUCTION_TIERS)
    frequency = _tier_score(cluster.unique_source_record_count, FREQUENCY_TIERS)
    severity = _severity_score(cluster)
    actionability = _actionability(members)
    purchase = _purchase_impact(members)

    penalties = 0
    penalty_notes: list[str] = []
    if cluster.platform_count == 1:
        penalties += PENALTY_SINGLE_PLATFORM
        penalty_notes.append("单一平台证据")
    if cluster.is_noise:
        penalties += PENALTY_NOISE
        penalty_notes.append("噪声点")
    unverified = sum(
        1 for member in members
        if member.get("evidence_status") in (EvidenceStatus.UNVERIFIED, EvidenceStatus.REJECTED)
    )
    if unverified:
        penalty = min(unverified * PENALTY_UNVERIFIED_PER_MEMBER, PENALTY_UNVERIFIED_CAP)
        penalties += penalty
        penalty_notes.append(f"未核验证据 {unverified} 条")
    if unresolved_conflicts:
        penalty = min(unresolved_conflicts * PENALTY_CONFLICT_PER_ITEM, PENALTY_CONFLICT_CAP)
        penalties += penalty
        penalty_notes.append(f"未解决冲突 {unresolved_conflicts} 个")

    raw_score = evidence_quality + reproduction + frequency + severity + actionability + purchase
    priority_score = max(0, min(100, raw_score - penalties))

    # 优先级等级（文档15 §7.13）
    if priority_score >= 80:
        priority_level = "P0"
    elif priority_score >= 65:
        priority_level = "P1"
    elif priority_score >= 45:
        priority_level = "P2"
    else:
        priority_level = "P3"

    # 置信度等级：多平台多来源高置信；单一来源或噪声低置信
    verified_fraction = _evidence_quality(members) / 15 if members else 0.0
    if cluster.is_noise or cluster.unique_source_record_count == 1:
        confidence_level = "low"
    elif (
        verified_fraction >= 0.5
        and cluster.unique_source_record_count >= 3
        and cluster.platform_count >= 2
    ):
        confidence_level = "high"
    else:
        confidence_level = "medium"

    return {
        "priority_score": priority_score,
        "priority_level": priority_level,
        "confidence_level": confidence_level,
        "breakdown": {
            "evidence_quality": evidence_quality,
            "reproduction": reproduction,
            "frequency": frequency,
            "severity": severity,
            "actionability": actionability,
            "purchase_impact": purchase,
        },
        "penalties": penalties,
        "penalty_notes": penalty_notes,
    }
