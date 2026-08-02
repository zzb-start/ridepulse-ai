"""共享测试 fixture。"""

from __future__ import annotations

from datetime import date

import pytest

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


@pytest.fixture
def valid_feedback_record() -> FeedbackRecord:
    """一条完全合法的反馈记录 fixture。"""
    return FeedbackRecord(
        feedback_id="F0001",
        source_record_id="SR-APPSTORE-0001",
        ingest_batch_id="BATCH-20260802-120000",
        source_platform="App Store",
        source_type=SourceType.APP_STORE,
        source_url="https://apps.apple.com/cz/app/onelapfit/id1555629744",
        source_permalink_level=PermalinkLevel.PAGE_ONLY,
        source_date=date(2025, 6, 15),
        source_date_raw="2025年6月15日",
        source_date_precision="day",
        accessed_at=date(2026, 8, 2),
        language="zh",
        market="CN",
        brand="Magene",
        product_model="C606",
        firmware_version=None,
        app_version=None,
        original_text="设备显示上传成功，但活动未出现在App里，重试了三次都一样。",
        translated_text=None,
        text_provenance=TextProvenance.VERBATIM,
        translation_method=TranslationMethod.NOT_NEEDED,
        archive_path=None,
        archive_sha256=None,
        evidence_status=EvidenceStatus.VERIFIED,
        verification_note="App Store 页面级核验通过",
    )


@pytest.fixture
def valid_classification() -> ClassificationResult:
    """一条完全合法的分类结果 fixture。"""
    return ClassificationResult(
        feedback_id="F0001",
        sentiment=Sentiment.NEGATIVE,
        theme_primary=ThemePrimary.CONNECTIVITY,
        theme_secondary=[ThemePrimary.FIRMWARE],
        need_type=NeedType.REAL_NEED,
        scenario="training",
        user_type="unknown",
        severity=Severity.S2,
        purchase_impact=PurchaseImpact.INFLUENCE,
        jtbd="用户希望骑行活动在App中可靠显示以完成训练数据管理",
        root_cause_hypotheses=["上传校验仅检查活动级别，未检查字段级别"],
        is_actionable=True,
        is_constructive=True,
        confidence=0.9,
        rationale="用户明确描述了上传成功但数据不显示的可复现问题",
        model_name="fake-model",
        prompt_version="classify_v1",
    )
