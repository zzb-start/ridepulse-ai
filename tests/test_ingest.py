"""ingest 模块测试 — 规格来源：文档15 §7.5。

要求：
1. 检查文件扩展名和大小
2. UTF-8-SIG 读取，编码错误明确报错，不静默乱码
3. 检查表头集合
4. 逐行构造 FeedbackRecord
5. 保存有效行和无效行
6. 无效行不进入后续模型调用
7. 校验报告指出具体行和字段
验收：坏 CSV 必须指出具体行和字段，不能只显示"解析失败"
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ridepulse.ingest import load_csv, load_fixture_json
from ridepulse.models import FeedbackRecord


def write_csv(path: Path, rows: list[dict]) -> Path:
    """以 utf-8-sig 写标准 CSV（None 写为空串，模拟真实导出）。"""
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def record_dict(valid_feedback_record: FeedbackRecord, **overrides) -> dict:
    """从 fixture 生成 CSV 行字典。"""
    data = valid_feedback_record.model_dump(mode="json")
    data.update(overrides)
    return data


class TestLoadCsv:
    def test_valid_csv_imports_all_rows(self, tmp_path, valid_feedback_record):
        path = write_csv(tmp_path / "valid.csv", [record_dict(valid_feedback_record)])
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.total_rows == 1
        assert report.valid_rows == 1
        assert report.invalid_rows == 0
        assert len(report.valid_records) == 1
        assert report.valid_records[0].feedback_id == "F0001"

    def test_valid_and_invalid_rows_saved_to_disk(self, tmp_path, valid_feedback_record):
        good = record_dict(valid_feedback_record)
        bad = record_dict(valid_feedback_record, feedback_id="F0002", original_text="")
        path = write_csv(tmp_path / "mixed.csv", [good, bad])
        out = tmp_path / "out"
        report = load_csv(str(path), out_dir=str(out))
        assert report.valid_rows == 1
        assert report.invalid_rows == 1
        # 有效行文件包含 F0001 且不含 F0002
        valid_content = (out / "mixed_valid.csv").read_text(encoding="utf-8-sig")
        invalid_content = (out / "mixed_invalid.csv").read_text(encoding="utf-8-sig")
        assert "F0001" in valid_content
        assert "F0002" not in valid_content
        assert "F0002" in invalid_content
        # 无效行文件带 error 列说明原因
        assert "original_text" in invalid_content

    def test_missing_required_header_raises_with_names(self, tmp_path, valid_feedback_record):
        row = record_dict(valid_feedback_record)
        del row["original_text"]
        path = write_csv(tmp_path / "bad_header.csv", [row])
        with pytest.raises(ValueError, match="original_text"):
            load_csv(str(path))

    def test_bad_encoding_reports_clearly(self, tmp_path):
        path = tmp_path / "gbk.csv"
        path.write_bytes("同步失败,活动未出现\n".encode("gbk"))
        with pytest.raises(ValueError, match="编码"):
            load_csv(str(path))

    def test_missing_field_marks_row_invalid_with_field_name(self, tmp_path, valid_feedback_record):
        rows = [
            record_dict(valid_feedback_record),
            record_dict(valid_feedback_record, feedback_id="F0002", original_text=""),
        ]
        path = write_csv(tmp_path / "missing.csv", rows)
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.valid_rows == 1
        assert report.invalid_rows == 1
        assert report.missing_fields.get("original_text") == 1
        # 警告必须指出具体行号（表头占第1行，坏数据在第3行）和字段
        assert any("第3行" in w and "original_text" in w for w in report.warnings)
        # 无效行不得进入有效记录
        assert [r.feedback_id for r in report.valid_records] == ["F0001"]

    def test_invalid_url_recorded_with_id(self, tmp_path, valid_feedback_record):
        rows = [record_dict(valid_feedback_record, source_url="example.com/no-scheme")]
        path = write_csv(tmp_path / "bad_url.csv", rows)
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.valid_rows == 0
        assert report.invalid_rows == 1
        assert report.invalid_urls == ["F0001: example.com/no-scheme"]

    def test_duplicate_ids_second_occurrence_invalid(self, tmp_path, valid_feedback_record):
        rows = [
            record_dict(valid_feedback_record),
            record_dict(valid_feedback_record),
        ]
        path = write_csv(tmp_path / "dup.csv", rows)
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.duplicate_ids == ["F0001"]
        assert report.valid_rows == 1
        assert report.invalid_rows == 1

    def test_unknown_column_warns_but_imports(self, tmp_path, valid_feedback_record):
        row = record_dict(valid_feedback_record)
        row["extra_column"] = "x"
        path = write_csv(tmp_path / "extra.csv", [row])
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.valid_rows == 1
        assert any("extra_column" in w for w in report.warnings)

    def test_non_csv_extension_rejected(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="CSV"):
            load_csv(str(path))

    def test_empty_file_rejected(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_bytes(b"")
        with pytest.raises(ValueError, match="空"):
            load_csv(str(path))

    def test_unverified_evidence_counted(self, tmp_path, valid_feedback_record):
        rows = [
            record_dict(valid_feedback_record, evidence_status="unverified"),
            record_dict(valid_feedback_record, feedback_id="F0002", evidence_status="verified"),
        ]
        path = write_csv(tmp_path / "unverified.csv", rows)
        report = load_csv(str(path), out_dir=str(tmp_path / "out"))
        assert report.unverified_evidence_count == 1
        assert report.valid_rows == 2


class TestLoadFixtureJson:
    def test_loads_valid_list(self, tmp_path, valid_feedback_record):
        path = tmp_path / "fixture.json"
        path.write_text(
            __import__("json").dumps([valid_feedback_record.model_dump(mode="json")]),
            encoding="utf-8",
        )
        records = load_fixture_json(str(path))
        assert len(records) == 1
        assert records[0].feedback_id == "F0001"

    def test_invalid_row_raises_with_feedback_id(self, tmp_path, valid_feedback_record):
        bad = valid_feedback_record.model_dump(mode="json")
        bad["feedback_id"] = "F9999"
        bad["original_text"] = ""
        path = tmp_path / "bad_fixture.json"
        path.write_text(__import__("json").dumps([bad]), encoding="utf-8")
        with pytest.raises(ValueError, match="F9999"):
            load_fixture_json(str(path))
