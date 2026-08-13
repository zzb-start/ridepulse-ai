"""clustering 模块测试 — 规格来源：文档15 §7.12。

要求：
1. 先按一级主题分桶，桶内语义聚类
2. 记录噪声点，不强行归类
3. 小于 3 条的簇保留但置信度低（下游评分处理）
4. 固定随机种子，结果可复现
5. 按 source_record_id 去重计数，不重复抬高频次
"""

from __future__ import annotations

from datetime import date

from ridepulse.clustering import cluster_feedback
from ridepulse.embedding import fake_embed
from ridepulse.models import (
    ClassificationResult,
    EvidenceStatus,
    FeedbackRecord,
    NeedType,
    PermalinkLevel,
    PurchaseImpact,
    Sentiment,
    Severity,
    SourceType,
    TextProvenance,
    ThemePrimary,
    TranslationMethod,
)


def make_record(feedback_id: str, text: str, *, theme: str = "connectivity",
                severity: str = "S3", source_record_id: str | None = None,
                platform: str = "App Store", language: str = "zh",
                brand: str = "Magene", source_date=None) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=feedback_id,
        source_record_id=source_record_id or f"SR-{feedback_id}",
        ingest_batch_id="BATCH-20260808-210000",
        source_platform=platform,
        source_type=SourceType.APP_STORE,
        source_url="https://apps.apple.com/cz/app/onelapfit/id1555629744",
        source_permalink_level=PermalinkLevel.PAGE_ONLY,
        source_date=source_date,
        source_date_raw=None,
        source_date_precision="day",
        accessed_at=date(2026, 8, 8),
        language=language,
        market="unknown",
        brand=brand,
        product_model=None,
        firmware_version=None,
        app_version=None,
        original_text=text,
        translated_text=None,
        text_provenance=TextProvenance.VERBATIM,
        translation_method=TranslationMethod.NOT_NEEDED,
        archive_path=None,
        archive_sha256=None,
        evidence_status=EvidenceStatus.VERIFIED,
        verification_note=None,
    )


def make_classification(feedback_id: str, *, theme: str = "connectivity",
                        severity: str = "S3") -> ClassificationResult:
    return ClassificationResult(
        feedback_id=feedback_id,
        sentiment=Sentiment.NEGATIVE,
        theme_primary=ThemePrimary(theme),
        theme_secondary=[],
        need_type=NeedType.REAL_NEED,
        scenario="training",
        user_type="unknown",
        severity=Severity(severity),
        purchase_impact=PurchaseImpact.INFLUENCE,
        jtbd="用户希望问题得到解决",
        root_cause_hypotheses=[],
        is_actionable=True,
        is_constructive=False,
        confidence=0.9,
        rationale="测试",
        model_name="test",
        prompt_version="test",
    )


def vectors_for(records, classifications):
    """fake embedding：同文本 -> 同向量 -> 必合并；异文本 -> 独立。"""
    result = {}
    for record in records:
        cls = classifications.get(record.feedback_id)
        theme = cls.theme_primary.value if cls else "other"
        result[record.feedback_id] = fake_embed(
            f"{record.brand}|{theme}|{record.original_text}", 64
        )
    return result


class TestBucketByTheme:
    def test_different_themes_never_merge(self):
        """不同一级主题必须分桶，不跨主题合并。"""
        r1 = make_record("F0001", "同步失败问题文本", theme="connectivity")
        r2 = make_record("F0002", "同步失败问题文本", theme="firmware")
        classifications = {
            "F0001": make_classification("F0001", theme="connectivity"),
            "F0002": make_classification("F0002", theme="firmware"),
        }
        vectors = vectors_for([r1, r2], classifications)
        clusters = cluster_feedback([r1, r2], vectors, classifications)
        assert len(clusters) == 2
        assert clusters[0].theme_primary != clusters[1].theme_primary


class TestSemanticMerge:
    def test_identical_text_merges(self):
        """同主题同文本 -> 合并为一簇。"""
        r1 = make_record("F0001", "活动同步后App不显示数据")
        r2 = make_record("F0002", "活动同步后App不显示数据")
        classifications = {fid: make_classification(fid) for fid in ("F0001", "F0002")}
        vectors = vectors_for([r1, r2], classifications)
        clusters = cluster_feedback([r1, r2], vectors, classifications)
        assert len(clusters) == 1
        assert set(clusters[0].member_feedback_ids) == {"F0001", "F0002"}

    def test_noise_point_marked(self):
        """同主题桶内落单记录标记 is_noise=True，不强行归类。"""
        r1 = make_record("F0001", "活动同步后App不显示数据")
        r2 = make_record("F0002", "活动同步后App不显示数据")
        r3 = make_record("F0003", "完全不同的另一个问题描述")
        classifications = {fid: make_classification(fid) for fid in ("F0001", "F0002", "F0003")}
        vectors = vectors_for([r1, r2, r3], classifications)
        clusters = cluster_feedback([r1, r2, r3], vectors, classifications)
        noise = [c for c in clusters if c.is_noise]
        merged = [c for c in clusters if not c.is_noise]
        assert len(noise) == 1
        assert noise[0].member_feedback_ids == ["F0003"]
        assert merged[0].member_feedback_ids == ["F0001", "F0002"]


class TestCounts:
    def test_unique_source_record_not_inflated(self):
        """同一 source_record 拆分的多条 feedback 只计 1 个独立用户。"""
        r1 = make_record("F0001", "活动同步后App不显示数据", source_record_id="SR-COMMON")
        r2 = make_record("F0002", "活动同步后App不显示数据", source_record_id="SR-COMMON")
        r3 = make_record("F0003", "活动同步后App不显示数据", source_record_id="SR-OTHER")
        classifications = {fid: make_classification(fid) for fid in ("F0001", "F0002", "F0003")}
        vectors = vectors_for([r1, r2, r3], classifications)
        clusters = cluster_feedback([r1, r2, r3], vectors, classifications)
        assert len(clusters) == 1
        assert clusters[0].unique_source_record_count == 2  # 而不是 3

    def test_deterministic_repeatable(self):
        """固定输入 -> 两次聚类结果完全一致。"""
        records = [make_record(f"F{i:04d}", f"问题描述文本{i}") for i in range(1, 6)]
        classifications = {r.feedback_id: make_classification(r.feedback_id) for r in records}
        vectors = vectors_for(records, classifications)
        first = cluster_feedback(records, vectors, classifications)
        second = cluster_feedback(records, vectors, classifications)
        assert [c.member_feedback_ids for c in first] == [c.member_feedback_ids for c in second]

    def test_max_severity_and_counts(self):
        """簇的计数与最高严重度正确。"""
        r1 = make_record("F0001", "相同文本", severity="S1", platform="App Store", language="zh")
        r2 = make_record("F0002", "相同文本", severity="S3", platform="论坛", language="en")
        classifications = {
            "F0001": make_classification("F0001", severity="S1"),
            "F0002": make_classification("F0002", severity="S3"),
        }
        vectors = vectors_for([r1, r2], classifications)
        clusters = cluster_feedback([r1, r2], vectors, classifications)
        cluster = clusters[0]
        assert cluster.max_severity == Severity.S1
        assert cluster.platform_count == 2
        assert cluster.language_count == 2
        assert cluster.brand_count == 1
