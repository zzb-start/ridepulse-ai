"""scoring 模块测试。

评分维度（总分100）：证据质量15 + 独立复现20 + 频次15 + 严重度20 + 可行动性15 + 购买影响15
含惩罚项与 P0-P3 / high-medium-low 判定。
"""

from __future__ import annotations

from datetime import date

from ridepulse.models import (
    ClusterInfo,
    EvidenceStatus,
    PurchaseImpact,
    Severity,
    ThemePrimary,
)
from ridepulse.scoring import score_cluster


def make_cluster(*, sources: int = 3, platforms: int = 2, severity: Severity = Severity.S2,
                 is_noise: bool = False) -> ClusterInfo:
    return ClusterInfo(
        cluster_id="CL-0001",
        member_feedback_ids=[f"F{i:04d}" for i in range(1, sources + 1)],
        unique_source_record_count=sources,
        unique_domain_count=platforms,
        platform_count=platforms,
        language_count=1,
        brand_count=1,
        max_severity=severity,
        time_range_days=30,
        is_noise=is_noise,
        theme_primary=ThemePrimary.CONNECTIVITY,
    )


def make_members(n: int, *, verified: int | None = None, actionable: bool = True,
                 purchase: PurchaseImpact = PurchaseImpact.NO_IMPACT) -> list[dict]:
    verified = n if verified is None else verified
    return [
        {
            "evidence_status": EvidenceStatus.VERIFIED if i < verified else EvidenceStatus.PARTIALLY_VERIFIED,
            "is_actionable": actionable,
            "purchase_impact": purchase,
        }
        for i in range(n)
    ]


class TestScoreDimensions:
    def test_evidence_quality_full_for_verified(self):
        score = score_cluster(make_cluster(), members=make_members(3))
        assert score["breakdown"]["evidence_quality"] == 15

    def test_reproduction_and_frequency_tiers(self):
        """独立用户 5 以上拿满 20+15；1 条最低。"""
        score5 = score_cluster(make_cluster(sources=5), members=make_members(5))
        assert score5["breakdown"]["reproduction"] == 20
        assert score5["breakdown"]["frequency"] == 15
        score1 = score_cluster(make_cluster(sources=1), members=make_members(1))
        assert score1["breakdown"]["reproduction"] == 4
        assert score1["breakdown"]["frequency"] == 3

    def test_severity_mapping(self):
        score = score_cluster(make_cluster(severity=Severity.S1), members=make_members(3))
        assert score["breakdown"]["severity"] == 20
        score = score_cluster(make_cluster(severity=Severity.S5), members=make_members(3))
        assert score["breakdown"]["severity"] == 2

    def test_purchase_impact_blocker_scores_full(self):
        members = make_members(3, purchase=PurchaseImpact.BLOCKER)
        score = score_cluster(make_cluster(), members=members)
        assert score["breakdown"]["purchase_impact"] == 15

    def test_total_never_exceeds_100(self):
        members = make_members(5, verified=5, actionable=True, purchase=PurchaseImpact.BLOCKER)
        score = score_cluster(make_cluster(sources=5, platforms=2, severity=Severity.S1),
                              members=members)
        assert score["priority_score"] <= 100


class TestPenalties:
    def test_single_platform_penalty(self):
        """单一平台证据扣 5 分。"""
        members = make_members(3)
        multi = score_cluster(make_cluster(platforms=2), members=members)
        single = score_cluster(make_cluster(platforms=1), members=members)
        assert multi["priority_score"] - single["priority_score"] == 5

    def test_noise_penalty(self):
        """噪声簇额外扣 10 分（其余条件相同，控制变量）。"""
        members = make_members(1)
        normal = score_cluster(make_cluster(sources=1, platforms=1), members=members)
        noise = score_cluster(make_cluster(sources=1, platforms=1, is_noise=True),
                              members=members)
        assert normal["priority_score"] - noise["priority_score"] == 10

    def test_unresolved_conflict_penalty(self):
        members = make_members(3)
        base = score_cluster(make_cluster(), members=members)
        conflicted = score_cluster(make_cluster(), members=members, unresolved_conflicts=2)
        assert base["priority_score"] - conflicted["priority_score"] == 6


class TestLevels:
    def test_priority_levels(self):
        """>=80 P0，65-79 P1，45-64 P2，<45 P3。"""
        members = make_members(5, verified=5, purchase=PurchaseImpact.BLOCKER)
        p0 = score_cluster(make_cluster(sources=5, platforms=2, severity=Severity.S1),
                           members=members)
        assert p0["priority_level"] == "P0"
        p3 = score_cluster(make_cluster(sources=1, platforms=1, severity=Severity.S5),
                           members=make_members(1))
        assert p3["priority_level"] == "P3"

    def test_confidence_levels(self):
        """多平台多来源高置信；单来源或噪声低置信。"""
        members = make_members(3, verified=3)
        high = score_cluster(make_cluster(sources=4, platforms=2), members=members)
        assert high["confidence_level"] == "high"
        low = score_cluster(make_cluster(sources=1, platforms=1), members=make_members(1))
        assert low["confidence_level"] == "low"
