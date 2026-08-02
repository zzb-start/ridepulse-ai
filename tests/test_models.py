"""数据模型测试 — 验证统一数据契约的合法/非法样本处理。

对应当日完成标准:
- Pydantic 模型可导入
- 一个合法样本测试通过
- 一个非法样本被拒绝

注意: Pydantic v2 的 model_copy(update=...) 不触发校验，
必须用 model_dump() + model_validate() 重新验证非法样本。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ridepulse.models import (
    ClassificationResult,
    EvidenceCard,
    EvidenceStatus,
    FeedbackRecord,
    ReviewResult,
    Severity,
    ThemePrimary,
)


def revalidate(model: Any, **updates: Any) -> Any:
    """从模型 dump 出 dict，应用更新后重新验证（校验生效的关键）。"""
    data = model.model_dump()
    data.update(updates)
    return type(model).model_validate(data)


class TestFeedbackRecord:
    """FeedbackRecord 合法与非法样本。"""

    def test_valid_sample_passes(self, valid_feedback_record: FeedbackRecord):
        """合法样本通过校验。"""
        assert valid_feedback_record.feedback_id == "F0001"
        assert valid_feedback_record.evidence_status == EvidenceStatus.VERIFIED

    def test_invalid_feedback_id_rejected(self, valid_feedback_record: FeedbackRecord):
        """非法 feedback_id（非 F 开头四位数字）被拒绝。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, feedback_id="abc")

    def test_invalid_url_rejected(self, valid_feedback_record: FeedbackRecord):
        """非 HTTPS URL 被拒绝。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, source_url="http://example.com")

    def test_missing_required_field_rejected(self, valid_feedback_record: FeedbackRecord):
        """缺少必填字段（original_text 为空）被拒绝。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, original_text="")

    def test_invalid_language_rejected(self, valid_feedback_record: FeedbackRecord):
        """非法语言代码被拒绝。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, language="english")

    def test_invalid_enum_rejected(self, valid_feedback_record: FeedbackRecord):
        """非法枚举值被拒绝。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, source_type="hacker")

    def test_extra_fields_rejected(self, valid_feedback_record: FeedbackRecord):
        """未知字段被拒绝（extra=forbid，防止各自发明字段）。"""
        with pytest.raises(ValidationError):
            revalidate(valid_feedback_record, hacked_field="x")

    def test_optional_fields_can_be_none(self, valid_feedback_record: FeedbackRecord):
        """选填字段可为 None（固件版本、App版本等）。"""
        record = revalidate(
            valid_feedback_record,
            firmware_version=None,
            app_version=None,
            translated_text=None,
            archive_path=None,
        )
        assert record.firmware_version is None


class TestClassificationResult:
    """分类结果模型。"""

    def test_valid_sample_passes(self, valid_classification: ClassificationResult):
        assert valid_classification.feedback_id == "F0001"
        assert valid_classification.severity == Severity.S2

    def test_jtbd_too_short_rejected(self, valid_classification: ClassificationResult):
        with pytest.raises(ValidationError):
            revalidate(valid_classification, jtbd="同步")

    def test_confidence_out_of_range_rejected(self, valid_classification: ClassificationResult):
        with pytest.raises(ValidationError):
            revalidate(valid_classification, confidence=1.5)

    def test_root_cause_max_3(self, valid_classification: ClassificationResult):
        with pytest.raises(ValidationError):
            revalidate(valid_classification, root_cause_hypotheses=["a", "b", "c", "d"])

    def test_invalid_theme_rejected(self, valid_classification: ClassificationResult):
        with pytest.raises(ValidationError):
            revalidate(valid_classification, theme_primary="sync")


class TestReviewResult:
    """复判结果模型。"""

    def test_valid_sample_passes(self):
        review = ReviewResult(
            feedback_id="F0001",
            review_sentiment=2,
            review_theme_primary=ThemePrimary.CONNECTIVITY,
            review_need_type="real_need",
            review_severity="S2",
            review_purchase_impact="influence",
            review_jtbd="用户希望骑行活动在App中可靠显示以完成训练数据管理",
            review_confidence=0.85,
            conflict_fields=["theme_primary"],
            review_status="conflict",
            human_review_required=True,
            model_name="fake-review-model",
            prompt_version="review_v1",
        )
        assert review.human_review_required is True

    def test_invalid_review_status_rejected(self):
        with pytest.raises(ValidationError):
            ReviewResult(
                feedback_id="F0001",
                review_sentiment=2,
                review_theme_primary="connectivity",
                review_need_type="real_need",
                review_severity="S2",
                review_purchase_impact="influence",
                review_jtbd="用户希望骑行活动在App中可靠显示以完成训练数据管理",
                review_confidence=0.85,
                review_status="maybe",
                human_review_required=False,
                model_name="fake-review-model",
                prompt_version="review_v1",
            )


class TestEvidenceCard:
    """证据卡模型。"""

    def test_valid_sample_passes(self):
        card = EvidenceCard(
            card_id="EC-2026-0001",
            cluster_id="CL-0001",
            title="码表→App→第三方平台的数据同步链路可靠性",
            problem_statement="多条反馈指向同步链路存在三类断裂模式",
            priority_score=88,
            priority_level="P0",
            confidence_level="medium",
            evidence_ids=["F0001", "F0002"],
            platforms=["App Store", "Google Play"],
            brands=["Magene"],
            languages=["zh", "en"],
            root_cause_hypotheses=["上传校验未检查字段级别"],
            counter_evidence="部分用户重试后成功",
            recommended_actions=[
                {
                    "action": "增加字段级同步校验",
                    "suggested_owner": "App开发",
                    "expected_result": "字段完整率>=99%",
                    "validation_metric": "字段完整率",
                    "effort_size": "M",
                }
            ],
            suggested_owner="App开发",
        )
        assert card.human_review_status == "pending"
        assert card.priority_level == "P0"

    def test_card_id_format_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceCard(
                card_id="CARD-001",
                cluster_id="CL-0001",
                title="测试",
                problem_statement="测试问题描述",
                priority_score=50,
                priority_level="P2",
                confidence_level="low",
                evidence_ids=["F0001"],
            )

    def test_cluster_id_format_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceCard(
                card_id="EC-2026-0002",
                cluster_id="CL-2",
                title="测试",
                problem_statement="测试问题描述",
                priority_score=50,
                priority_level="P2",
                confidence_level="low",
                evidence_ids=["F0001"],
            )

    def test_empty_evidence_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceCard(
                card_id="EC-2026-0002",
                cluster_id="CL-0002",
                title="测试",
                problem_statement="测试问题描述",
                priority_score=50,
                priority_level="P2",
                confidence_level="low",
                evidence_ids=[],
            )
