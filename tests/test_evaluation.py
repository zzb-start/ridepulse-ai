"""evaluation 模块测试。

指标：Cohen's Kappa / 加权 Kappa / 每字段 accuracy 与 Macro F1 / severity 加权 Kappa。
"""

from __future__ import annotations

import pytest

from ridepulse.evaluation import cohens_kappa, evaluate_model, weighted_kappa


class TestCohenKappa:
    def test_perfect_agreement_is_one(self):
        assert cohens_kappa([1, 1, 2, 2], [1, 1, 2, 2]) == 1.0

    def test_zero_agreement(self):
        # po=0.5, pe=0.5 -> kappa=0
        assert cohens_kappa([0, 0, 1, 1], [0, 1, 1, 0]) == 0.0

    def test_negative_possible(self):
        # 完全错位的标注: po=0, pe=1/3 -> kappa=-0.5
        assert cohens_kappa([1, 1, 2, 2, 3, 3], [2, 2, 3, 3, 1, 1]) < 0

    def test_length_mismatch_rejected(self):
        with pytest.raises(ValueError):
            cohens_kappa([1, 2], [1])

    def test_single_label_agreement(self):
        assert cohens_kappa(["a", "a"], ["a", "a"]) == 1.0


class TestWeightedKappa:
    def test_perfect_agreement(self):
        assert weighted_kappa([1, 1, 2, 2, 3, 3], [1, 1, 2, 2, 3, 3]) == 1.0

    def test_known_linear_value(self):
        # a=[1,2,3], b=[3,2,1]: observed=1/3, expected=5/9 -> kappa=-0.5
        assert weighted_kappa([1, 2, 3], [3, 2, 1], weights="linear") == -0.5

    def test_unknown_weights_rejected(self):
        with pytest.raises(ValueError):
            weighted_kappa([1, 2], [1, 2], weights="sqrt")

    def test_severity_ordinal_better_than_plain(self):
        """有序标签的相邻误判：加权 Kappa 高于普通 Kappa。"""
        # 全部差一级（S2 vs S3 等）
        a = ["S1", "S2", "S3", "S4", "S5"]
        b = ["S2", "S3", "S4", "S5", "S1"]
        assert weighted_kappa(a, b) > cohens_kappa(a, b)


class TestEvaluateModel:
    def test_matches_gold(self, valid_classification):
        gold = [{
            "feedback_id": "F0001",
            "theme_primary": "connectivity",
            "need_type": "real_need",
            "severity": "S2",
            "purchase_impact": "influence",
        }]
        metrics = evaluate_model([valid_classification], gold)
        assert metrics["paired_count"] == 1
        assert metrics["theme_primary"]["accuracy"] == 1.0
        assert metrics["theme_primary"]["macro_f1"] == 1.0
        assert metrics["severity_weighted_kappa"] == 1.0

    def test_no_overlap_reports_error(self):
        gold = [{"feedback_id": "F9999", "theme_primary": "x", "need_type": "x",
                 "severity": "S1", "purchase_impact": "x"}]
        from ridepulse.models import ClassificationResult
        metrics = evaluate_model([ClassificationResult(**{
            "feedback_id": "F0001", "sentiment": 2, "theme_primary": "connectivity",
            "need_type": "real_need", "severity": "S2", "purchase_impact": "influence",
            "jtbd": "用户希望问题得到解决并得到回应", "is_actionable": True, "is_constructive": False,
            "confidence": 0.9, "rationale": "测试", "model_name": "m", "prompt_version": "v",
        })], gold)
        assert "error" in metrics

    def test_review_rate_computed(self, valid_classification):
        gold = [{
            "feedback_id": "F0001",
            "theme_primary": "connectivity",
            "need_type": "real_need",
            "severity": "S2",
            "purchase_impact": "influence",
        }]
        low_confidence = valid_classification.model_copy(update={"confidence": 0.5})
        metrics = evaluate_model([low_confidence], gold)
        assert metrics["review_rate"] == 1.0
