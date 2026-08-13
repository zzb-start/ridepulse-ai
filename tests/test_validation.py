"""validation 模块测试 — 规格来源：文档15 §7.5。

要求：
- 单行字段级校验给出具体字段错误
- 校验报告渲染包含行号与字段定位
"""

from __future__ import annotations

from ridepulse.validation import render_report, validate_row


def valid_row() -> dict:
    return {
        "feedback_id": "F0001",
        "source_record_id": "SR-1",
        "ingest_batch_id": "BATCH-20260802-120000",
        "source_platform": "App Store",
        "source_type": "app_store",
        "source_url": "https://apps.apple.com/app/id123",
        "source_permalink_level": "page_only",
        "source_date_precision": "day",
        "accessed_at": "2026-08-02",
        "language": "zh",
        "brand": "Magene",
        "original_text": "同步失败",
        "text_provenance": "verbatim",
        "translation_method": "not_needed",
        "evidence_status": "verified",
    }


class TestValidateRow:
    def test_valid_row_passes(self):
        record, errors = validate_row(valid_row())
        assert record is not None
        assert errors == {}

    def test_empty_feedback_id_detected(self):
        row = valid_row()
        row["feedback_id"] = ""
        record, errors = validate_row(row)
        assert record is None
        assert "feedback_id" in errors

    def test_field_level_error_has_location(self):
        """坏行必须指出具体字段（§7.5 验收：不能只显示解析失败）。"""
        row = valid_row()
        row["source_url"] = "ftp://not-https"
        row["language"] = "english"
        record, errors = validate_row(row)
        assert record is None
        assert "source_url" in errors
        assert "language" in errors

    def test_unknown_column_tolerated(self):
        """未知列不导致整行失败（表头检查在 ingest 层处理）。"""
        row = valid_row()
        row["extra_column"] = "x"
        record, _ = validate_row(row)
        assert record is not None


class TestRenderReport:
    def test_render_contains_counts(self, tmp_path):
        from ridepulse.ingest import load_csv
        import csv as _csv
        from pathlib import Path

        path = Path(tmp_path) / "bad.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=list(valid_row().keys()))
            writer.writeheader()
            writer.writerow(valid_row())
            bad = valid_row()
            bad["feedback_id"] = ""
            writer.writerow(bad)

        report = load_csv(str(path), out_dir=str(tmp_path / "check"))
        text = render_report(report)
        assert "总数: 2" in text  # 1 有效 + 1 无效
        assert "有效: 1" in text
        assert "无效: 1" in text
        assert "feedback_id" in text
