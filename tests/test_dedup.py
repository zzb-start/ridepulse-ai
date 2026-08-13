"""dedup 模块测试 — 规格来源：文档15 §7.6。

第一层：SHA-256 精确指纹 (normalized_text + brand + product_model)
第二层：字符 3-gram TF-IDF 余弦相似度，阈值默认 0.92
- 只标记 duplicate_group_id，不自动删除记录
- 来源不同但文本相同的转载，保留来源，评分时降低独立性
验收：同一句文字大小写、空格不同应归为重复；
     不同问题不能因为共享"同步失败"四个字就合并。
"""

from __future__ import annotations

import pytest

from ridepulse.dedup import exact_fingerprint, near_duplicate_groups


class TestExactFingerprint:
    def test_same_inputs_same_hash(self):
        a = exact_fingerprint("设备显示上传成功", "Magene", "C606")
        b = exact_fingerprint("设备显示上传成功", "Magene", "C606")
        assert a == b
        assert len(a) == 64  # SHA-256 hex

    def test_different_text_differs(self):
        assert exact_fingerprint("同步失败", "Magene", "C606") != exact_fingerprint(
            "上传失败", "Magene", "C606"
        )

    def test_different_brand_differs(self):
        assert exact_fingerprint("同步失败", "Magene", "C606") != exact_fingerprint(
            "同步失败", "Garmin", "C606"
        )

    def test_none_model_equivalent_to_empty(self):
        assert exact_fingerprint("同步失败", "Magene", None) == exact_fingerprint(
            "同步失败", "Magene", ""
        )


def _record(feedback_id: str, text: str) -> dict:
    return {"feedback_id": feedback_id, "original_text": text}


class TestNearDuplicateGroups:
    def test_whitespace_and_case_variants_merge(self):
        records = [
            _record("F0001", "Sync failed, activity not shown"),
            _record("F0002", "sync  failed, activity not shown"),
        ]
        groups = near_duplicate_groups(records)
        assert groups["F0001"] == groups["F0002"]

    def test_identical_texts_merge(self):
        records = [
            _record("F0001", "设备显示上传成功，但活动未出现在App里"),
            _record("F0002", "设备显示上传成功，但活动未出现在App里"),
        ]
        groups = near_duplicate_groups(records)
        assert groups["F0001"] == groups["F0002"]

    def test_punctuation_variant_merges(self):
        # 同一句话的全角/半角标点变体（转载常见差异）
        records = [
            _record("F0001", "设备显示上传成功，但活动未出现在App里"),
            _record("F0002", "设备显示上传成功,但活动未出现在App里"),
        ]
        groups = near_duplicate_groups(records)
        assert groups["F0001"] == groups["F0002"]

    def test_shared_phrase_alone_does_not_merge(self):
        records = [
            _record("F0001", "同步失败，活动记录没有上传到App"),
            _record("F0002", "同步失败，心率带无法连接"),
        ]
        assert near_duplicate_groups(records) == {}

    def test_distinct_issues_stay_separate(self):
        records = [
            _record("F0001", "码表屏幕在强光下看不清"),
            _record("F0002", "GPS定位漂移导致里程不准"),
            _record("F0003", "固件更新后电池耗电明显加快"),
        ]
        groups = near_duplicate_groups(records)
        assert len(groups) == 0  # 无任何重复组

    def test_group_id_only_assigned_to_duplicates(self):
        records = [
            _record("F0001", "设备显示上传成功，但活动未出现在App里"),
            _record("F0002", "设备显示上传成功，但活动未出现在App里"),
            _record("F0003", "完全无关的另一条反馈"),
        ]
        groups = near_duplicate_groups(records)
        assert groups["F0001"] == groups["F0002"]
        assert "F0003" not in groups

    def test_two_distinct_groups_get_distinct_ids(self):
        records = [
            _record("F0001", "设备显示上传成功，但活动未出现在App里"),
            _record("F0002", "设备显示上传成功，但活动未出现在App里"),
            _record("F0003", "GPS定位漂移导致里程明显不准"),
            _record("F0004", "GPS定位漂移导致里程明显不准"),
        ]
        groups = near_duplicate_groups(records)
        assert groups["F0001"] == groups["F0002"]
        assert groups["F0003"] == groups["F0004"]
        assert groups["F0001"] != groups["F0003"]

    def test_group_ids_are_deterministic(self):
        records = [
            _record("F0001", "设备显示上传成功，但活动未出现在App里"),
            _record("F0002", "设备显示上传成功，但活动未出现在App里"),
            _record("F0003", "GPS定位漂移导致里程明显不准"),
            _record("F0004", "GPS定位漂移导致里程明显不准"),
        ]
        first = near_duplicate_groups(records)
        second = near_duplicate_groups(records)
        assert first == second

    def test_empty_records_return_empty(self):
        assert near_duplicate_groups([]) == {}

    def test_threshold_is_configurable(self):
        # 两条反馈共享"同步失败，"前缀但问题不同
        records = [
            _record("F0001", "同步失败，活动没上传"),
            _record("F0002", "同步失败，心率带断了"),
        ]
        # 默认阈值 0.92 不合并
        assert len(near_duplicate_groups(records)) == 0
        # 降低阈值后合并（共享前缀的 3-gram 余弦约 0.25）
        groups = near_duplicate_groups(records, threshold=0.2)
        assert groups["F0001"] == groups["F0002"]
