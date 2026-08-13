"""normalize 模块测试 — 规格来源：文档15 §7.6。

要求：
1. Unicode NFKC 规范化
2. 合并多余空白
3. 保留原文，不覆盖 original_text（调用方责任，此处验证 normalize 不改写字段）
4. 品牌别名统一（Magene/迈金 -> Magene）
5. 版本号规范化但保留原始文本
"""

from __future__ import annotations

import pytest

from ridepulse.normalize import normalize_brand, normalize_text, normalize_version


class TestNormalizeText:
    def test_nfkc_normalizes_fullwidth_and_halfwidth(self):
        # 全角字母 -> 半角
        assert normalize_text("ＡＢＣ１２３") == "ABC123"
        # 半角片假名 -> 全角片假名
        assert normalize_text("ｶﾀｶﾅ") == "カタカナ"

    def test_merges_whitespace_runs(self):
        assert normalize_text("同步  失败\t\n  重试") == "同步 失败 重试"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_text("  同步失败  ") == "同步失败"

    def test_nfkc_maps_fullwidth_punctuation_to_ascii(self):
        # NFKC 规范行为：全角逗号/感叹号 -> 半角（对去重有益，原文仍保留）
        assert normalize_text("同步失败，活动未出现！") == "同步失败,活动未出现!"


class TestNormalizeBrand:
    def test_identity_for_canonical_brand(self):
        assert normalize_brand("Magene") == "Magene"

    def test_aliases_map_to_canonical(self):
        assert normalize_brand("迈金") == "Magene"
        assert normalize_brand("迈金科技") == "Magene"
        assert normalize_brand("佳明") == "Garmin"
        assert normalize_brand("百锐腾") == "Bryton"

    def test_latin_case_variants_map_to_canonical(self):
        assert normalize_brand("magene") == "Magene"
        assert normalize_brand("MAGENE") == "Magene"
        assert normalize_brand("GARMIN") == "Garmin"

    def test_unknown_brand_passes_through_cleaned(self):
        assert normalize_brand(" 某新品牌 ") == "某新品牌"

    def test_is_idempotent(self):
        assert normalize_brand(normalize_brand("迈金")) == "Magene"


class TestNormalizeVersion:
    def test_strips_version_prefix(self):
        assert normalize_version("v1.2.3") == "1.2.3"
        assert normalize_version("V1.2.3") == "1.2.3"

    def test_collapses_inner_whitespace(self):
        assert normalize_version("1.2  .  3") == "1.2 . 3"

    def test_strips_surrounding_whitespace_and_prefix(self):
        assert normalize_version("  V1.2.3  ") == "1.2.3"

    def test_none_passes_through(self):
        assert normalize_version(None) is None

    def test_plain_version_unchanged(self):
        assert normalize_version("1.2.3") == "1.2.3"
        assert normalize_version("12.9.0-beta") == "12.9.0-beta"
