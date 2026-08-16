"""review 模块测试。

7.9 对比字段: sentiment / theme_primary / need_type / severity / purchase_impact
冲突规则：
1. 任一核心字段不同 -> 记录 conflict_fields
2. theme_primary / need_type / severity 冲突 -> 必须人工复核
3. 情感相差 2 级以上 -> 必须人工复核
4. 两轮都低置信度 -> 必须人工复核
5. 第二轮调用失败 -> 必须人工复核
复判输入只能包含原始反馈和必要元数据，不能把第一轮结果告诉复判模型。

7.10 人工复核状态机: pending -> approved / corrected / rejected
"""

from __future__ import annotations

import pytest

from ridepulse.llm_client import FakeLLMClient, LLMClientError
from ridepulse.models import (
    ClassificationResult,
    HumanReview,
    HumanReviewStatus,
    NeedType,
    PurchaseImpact,
    ReviewConflictStatus,
    ReviewResult,
    Sentiment,
    Severity,
    ThemePrimary,
)
from ridepulse.review import apply_human_decision, compare_and_judge, review_batch


def make_primary(**overrides) -> ClassificationResult:
    values: dict = {
        "feedback_id": "F0001",
        "sentiment": Sentiment.NEGATIVE,
        "theme_primary": ThemePrimary.CONNECTIVITY,
        "need_type": NeedType.REAL_NEED,
        "severity": Severity.S2,
        "purchase_impact": PurchaseImpact.UNKNOWN,
        "jtbd": "用户希望骑行活动在App中可靠显示以完成训练数据管理",
        "is_actionable": True,
        "is_constructive": True,
        "confidence": 0.9,
        "rationale": "可复现的上传问题",
        "model_name": "fake-primary",
        "prompt_version": "classify_v1",
    }
    values.update(overrides)
    return ClassificationResult(**values)


def make_review(**overrides) -> ReviewResult:
    values: dict = {
        "feedback_id": "F0001",
        "review_sentiment": Sentiment.NEGATIVE,
        "review_theme_primary": ThemePrimary.CONNECTIVITY,
        "review_need_type": NeedType.REAL_NEED,
        "review_severity": Severity.S2,
        "review_purchase_impact": PurchaseImpact.UNKNOWN,
        "review_jtbd": "用户希望骑行活动在App中可靠显示以完成训练数据管理",
        "review_confidence": 0.85,
        "conflict_fields": [],
        "review_status": ReviewConflictStatus.AGREED,
        "human_review_required": False,
        "model_name": "fake-review",
        "prompt_version": "review_v1",
    }
    values.update(overrides)
    return ReviewResult(**values)


class TestCompareAndJudge:
    def test_agreed_when_fields_match(self):
        result = compare_and_judge(make_primary(), make_review())
        assert result.review_status == ReviewConflictStatus.AGREED
        assert result.conflict_fields == []
        assert result.human_review_required is False

    def test_theme_conflict_requires_review(self):
        result = compare_and_judge(
            make_primary(), make_review(review_theme_primary=ThemePrimary.FIRMWARE)
        )
        assert result.review_status == ReviewConflictStatus.CONFLICT
        assert result.conflict_fields == ["theme_primary"]
        assert result.human_review_required is True

    def test_need_type_conflict_requires_review(self):
        result = compare_and_judge(
            make_primary(), make_review(review_need_type=NeedType.FEATURE_REQUEST)
        )
        assert result.conflict_fields == ["need_type"]
        assert result.human_review_required is True

    def test_severity_conflict_requires_review(self):
        result = compare_and_judge(
            make_primary(), make_review(review_severity=Severity.S4)
        )
        assert result.conflict_fields == ["severity"]
        assert result.human_review_required is True

    def test_purchase_impact_conflict_recorded_but_not_auto_review(self):
        result = compare_and_judge(
            make_primary(), make_review(review_purchase_impact=PurchaseImpact.INFLUENCE)
        )
        assert result.conflict_fields == ["purchase_impact"]
        assert result.human_review_required is False

    def test_sentiment_gap_of_two_requires_review(self):
        result = compare_and_judge(
            make_primary(sentiment=Sentiment.STRONG_NEGATIVE),
            make_review(review_sentiment=Sentiment.NEUTRAL),
        )
        assert result.conflict_fields == ["sentiment"]
        assert result.human_review_required is True

    def test_sentiment_gap_of_one_does_not_require_review(self):
        result = compare_and_judge(
            make_primary(sentiment=Sentiment.STRONG_NEGATIVE),
            make_review(review_sentiment=Sentiment.NEGATIVE),
        )
        assert result.human_review_required is False

    def test_both_low_confidence_requires_review(self):
        result = compare_and_judge(
            make_primary(confidence=0.5), make_review(review_confidence=0.4)
        )
        assert result.human_review_required is True

    def test_one_low_confidence_alone_does_not_require_review(self):
        result = compare_and_judge(
            make_primary(confidence=0.9), make_review(review_confidence=0.4)
        )
        assert result.human_review_required is False

    def test_failed_review_passes_through_with_review_required(self):
        failed = make_review(
            review_status=ReviewConflictStatus.FAILED,
            human_review_required=True,
        )
        result = compare_and_judge(make_primary(), failed)
        assert result is not failed  # 返回副本，不修改入参
        assert result.review_status == ReviewConflictStatus.FAILED
        assert result.human_review_required is True

    def test_conflict_fields_list_all_differences(self):
        result = compare_and_judge(
            make_primary(),
            make_review(
                review_sentiment=Sentiment.POSITIVE,
                review_theme_primary=ThemePrimary.FIRMWARE,
                review_need_type=NeedType.INCIDENTAL_FAILURE,
            ),
        )
        assert set(result.conflict_fields) == {"sentiment", "theme_primary", "need_type"}


class TestReviewBatch:
    def test_returns_one_result_per_record_in_order(self, valid_feedback_record):
        primary = make_primary()
        records = [valid_feedback_record.model_copy(update={"feedback_id": "F0001"})]

        def responder(system: str, user: str) -> dict:
            return {
                "review_sentiment": 2,
                "review_theme_primary": "connectivity",
                "review_need_type": "real_need",
                "review_severity": "S2",
                "review_purchase_impact": "unknown",
                "review_jtbd": "用户希望骑行活动在App中可靠显示以完成训练数据管理",
                "review_confidence": 0.85,
            }

        client = FakeLLMClient(responder=responder)
        results = review_batch(records, [primary], client, prompt_path="prompts/review_v1.md")
        assert len(results) == 1
        assert results[0].feedback_id == "F0001"
        assert results[0].review_status == ReviewConflictStatus.AGREED
        assert results[0].human_review_required is False
        assert results[0].model_name == "fake-model"
        assert results[0].prompt_version == "review_v1"

    def test_review_prompt_does_not_contain_first_round_result(self, valid_feedback_record):
        """独立复判：输入只能有原文与必要元数据，不能泄露第一轮分类。"""
        primary = make_primary()
        captured: list[tuple[str, str]] = []

        def responder(system: str, user: str) -> dict:
            captured.append((system, user))
            return {
                "review_sentiment": 2,
                "review_theme_primary": "connectivity",
                "review_need_type": "real_need",
                "review_severity": "S2",
                "review_purchase_impact": "unknown",
                "review_jtbd": "用户希望骑行活动在App中可靠显示以完成训练数据管理",
                "review_confidence": 0.85,
            }

        client = FakeLLMClient(responder=responder)
        review_batch(
            [valid_feedback_record], [primary], client, prompt_path="prompts/review_v1.md"
        )
        _, user_text = captured[0]
        # 用户消息（模型看到的输入）不得包含第一轮的任何分类结论
        assert "connectivity" not in user_text
        assert "real_need" not in user_text
        # 但原文必须出现
        assert "设备显示上传成功" in user_text

    def test_conflicting_review_marked_for_human_review(self, valid_feedback_record):
        primary = make_primary()

        def responder(system: str, user: str) -> dict:
            return {
                "review_sentiment": 2,
                "review_theme_primary": "firmware",  # 与第一轮 connectivity 冲突
                "review_need_type": "real_need",
                "review_severity": "S2",
                "review_purchase_impact": "unknown",
                "review_jtbd": "用户希望固件更新后功能保持稳定",
                "review_confidence": 0.85,
            }

        client = FakeLLMClient(responder=responder)
        results = review_batch(
            [valid_feedback_record], [primary], client, prompt_path="prompts/review_v1.md"
        )
        assert results[0].review_status == ReviewConflictStatus.CONFLICT
        assert results[0].human_review_required is True
        assert results[0].conflict_fields == ["theme_primary"]

    def test_call_failure_produces_failed_status_with_review_required(self, valid_feedback_record):
        primary = make_primary()

        def responder(system: str, user: str) -> dict:
            raise LLMClientError("模型不可用")

        client = FakeLLMClient(responder=responder)
        results = review_batch(
            [valid_feedback_record], [primary], client, prompt_path="prompts/review_v1.md"
        )
        result = results[0]
        assert result.review_status == ReviewConflictStatus.FAILED
        assert result.human_review_required is True

    def test_batch_preserves_id_correspondence(self, valid_feedback_record):
        primary1 = make_primary()
        primary2 = make_primary(
            feedback_id="F0002",
            theme_primary=ThemePrimary.FIRMWARE,
            severity=Severity.S3,
        )
        records = [
            valid_feedback_record.model_copy(update={"feedback_id": "F0001"}),
            valid_feedback_record.model_copy(
                update={"feedback_id": "F0002", "original_text": "固件更新后循环重启"}
            ),
        ]

        def responder(system: str, user: str) -> dict:
            theme = "firmware" if "固件更新" in user else "connectivity"
            return {
                "review_sentiment": 2,
                "review_theme_primary": theme,
                "review_need_type": "real_need",
                "review_severity": "S3",
                "review_purchase_impact": "unknown",
                "review_jtbd": "用户希望功能保持稳定",
                "review_confidence": 0.85,
            }

        client = FakeLLMClient(responder=responder)
        results = review_batch(records, [primary1, primary2], client, prompt_path="prompts/review_v1.md")
        assert [r.feedback_id for r in results] == ["F0001", "F0002"]


class TestApplyHumanDecision:
    def test_approves_when_final_matches_both_rounds(self):
        primary = make_primary()
        review = make_review()
        result = apply_human_decision(
            primary=primary,
            review=review,
            final_sentiment=Sentiment.NEGATIVE,
            final_theme_primary=ThemePrimary.CONNECTIVITY,
            final_need_type=NeedType.REAL_NEED,
            final_severity=Severity.S2,
            final_purchase_impact=PurchaseImpact.UNKNOWN,
            reviewer="liang",
            note="两轮一致，通过",
        )
        assert isinstance(result, HumanReview)
        assert result.review_status == HumanReviewStatus.APPROVED
        assert result.reviewer == "liang"
        assert result.review_note == "两轮一致，通过"
        assert result.reviewed_at is not None

    def test_corrected_when_final_differs_from_review_round(self):
        result = apply_human_decision(
            primary=make_primary(),
            review=make_review(review_severity=Severity.S4),
            final_sentiment=Sentiment.NEGATIVE,
            final_theme_primary=ThemePrimary.CONNECTIVITY,
            final_need_type=NeedType.REAL_NEED,
            final_severity=Severity.S2,
            final_purchase_impact=PurchaseImpact.UNKNOWN,
            reviewer="feng",
            note="以第一轮为准，严重度应为S2",
        )
        assert result.review_status == HumanReviewStatus.CORRECTED
        assert result.conflict_fields == ["severity"]

    def test_rejected_sets_status_and_keeps_record(self):
        result = apply_human_decision(
            primary=make_primary(),
            review=make_review(review_status=ReviewConflictStatus.CONFLICT),
            final_sentiment=Sentiment.NEUTRAL,
            final_theme_primary=ThemePrimary.OTHER,
            final_need_type=NeedType.UNKNOWN,
            final_severity=Severity.S5,
            final_purchase_impact=PurchaseImpact.NO_IMPACT,
            reviewer="liang",
            note="内容与产品无关，作废",
            rejected=True,
        )
        assert result.review_status == HumanReviewStatus.REJECTED
        assert result.review_note == "内容与产品无关，作废"
