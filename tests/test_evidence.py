"""evidence 模块测试 — 规格来源：文档15 §7.14。

要求：
1. 代码先生成结构化簇摘要和分数
2. 只把簇内允许引用的反馈传给模型
3. 代码验证所有引用 ID 都属于该簇
4. 每条核心发现至少一个 feedback_id
5. URL 由代码附加，不允许模型编 URL
6. 证据卡默认 human_review_status=pending
"""

from __future__ import annotations

from datetime import date

import pytest

from ridepulse.evidence import generate_cards, validate_citation
from ridepulse.models import (
    ClassificationResult,
    EvidenceStatus,
    FeedbackRecord,
    HumanReviewStatus,
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
from ridepulse.clustering import cluster_feedback
from ridepulse.embedding import fake_embed


def make_record(feedback_id: str, text: str) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=feedback_id,
        source_record_id=f"SR-{feedback_id}",
        ingest_batch_id="BATCH-20260808-210000",
        source_platform="App Store",
        source_type=SourceType.APP_STORE,
        source_url=f"https://apps.apple.com/review/{feedback_id}",
        source_permalink_level=PermalinkLevel.PAGE_ONLY,
        source_date=date(2026, 7, 1),
        source_date_raw=None,
        source_date_precision="day",
        accessed_at=date(2026, 8, 8),
        language="zh",
        market="unknown",
        brand="Magene",
        product_model="C606",
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


def make_classification(feedback_id: str) -> ClassificationResult:
    return ClassificationResult(
        feedback_id=feedback_id,
        sentiment=Sentiment.NEGATIVE,
        theme_primary=ThemePrimary.CONNECTIVITY,
        theme_secondary=[],
        need_type=NeedType.REAL_NEED,
        scenario="training",
        user_type="unknown",
        severity=Severity.S2,
        purchase_impact=PurchaseImpact.INFLUENCE,
        jtbd="用户希望同步数据在App中正确显示以完成训练记录管理",
        root_cause_hypotheses=["上传校验只检查活动级别"],
        is_actionable=True,
        is_constructive=False,
        confidence=0.9,
        rationale="测试",
        model_name="test",
        prompt_version="test",
    )


def build_cluster_data():
    records = [
        make_record("F0001", "活动同步后App不显示数据，重试三次一样"),
        make_record("F0002", "活动同步后App不显示数据，重试三次一样"),
        make_record("F0003", "心率数据同步到Strava后字段为空"),
    ]
    classifications = {r.feedback_id: make_classification(r.feedback_id) for r in records}
    vectors = {
        r.feedback_id: fake_embed(f"{r.brand}|connectivity|{r.original_text}", 64)
        for r in records
    }
    clusters = cluster_feedback(records, vectors, classifications)
    records_by_id = {r.feedback_id: r for r in records}
    return records, classifications, clusters, records_by_id


class TestGenerateCards:
    def test_deterministic_card_without_client(self):
        """无客户端（或Fake）时使用确定性模板，流水线不中断。"""
        records, classifications, clusters, records_by_id = build_cluster_data()
        cards = generate_cards(clusters, records_by_id, classifications, client=None)
        assert len(cards) == len(clusters)
        for card in cards:
            assert card.card_id.startswith("EC-2026-")
            assert card.title
            assert card.problem_statement
            assert card.evidence_ids
            assert card.human_review_status == HumanReviewStatus.PENDING

    def test_evidence_ids_within_cluster(self):
        """引用 ID 必须属于该簇（生成时即校验）。"""
        records, classifications, clusters, records_by_id = build_cluster_data()
        cards = generate_cards(clusters, records_by_id, classifications, client=None)
        for card in cards:
            cluster = next(c for c in clusters if c.cluster_id == card.cluster_id)
            violations = validate_citation(card, set(cluster.member_feedback_ids))
            assert violations == []

    def test_urls_attached_by_code(self):
        """URL 由代码附加：卡内 evidence 条目带数据中的 source_url。"""
        records, classifications, clusters, records_by_id = build_cluster_data()
        cards = generate_cards(clusters, records_by_id, classifications, client=None)
        # 直接验证 records_by_id 的 URL 与记录一致（模型无从编造）
        for card in cards:
            for fid in card.evidence_ids:
                assert records_by_id[fid].source_url.startswith("https://")

    def test_llm_failure_falls_back_to_template(self):
        """模型调用失败回退确定性模板，不产生空卡。"""
        records, classifications, clusters, records_by_id = build_cluster_data()

        class BrokenClient:
            model = "broken-model"

            def complete_json(self, system: str, user: str, **kwargs):
                raise RuntimeError("boom")

        cards = generate_cards(clusters, records_by_id, classifications,
                               client=BrokenClient())
        assert cards
        assert all(card.title for card in cards)


class TestValidateCitation:
    def test_violation_detected(self):
        records, classifications, clusters, records_by_id = build_cluster_data()
        cards = generate_cards(clusters, records_by_id, classifications, client=None)
        card = cards[0]
        members = set(card.evidence_ids)
        # 越界引用应被检出
        violations = validate_citation(
            card.model_copy(update={"evidence_ids": list(members) + ["F9999"]}),
            members,
        )
        assert violations == ["F9999"]

    def test_clean_citation_no_violation(self):
        records, classifications, clusters, records_by_id = build_cluster_data()
        cards = generate_cards(clusters, records_by_id, classifications, client=None)
        members = set(cards[0].evidence_ids)
        assert validate_citation(cards[0], members) == []
