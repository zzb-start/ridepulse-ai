"""数据导入模块 — CSV 读取与 FeedbackRecord 构造。

实现要求（文档15 §7.5）：
1. UTF-8-SIG 读取，失败时报明确编码错误
2. 表头检查
3. 逐行构造 FeedbackRecord
4. 保存有效行和无效行
5. 无效行不进入后续模型调用
6. 输出 ValidationReport
验收：坏 CSV 必须指出具体行和字段，不能只显示"解析失败"
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pydantic import ValidationError

from ridepulse.config import get_config
from ridepulse.models import EvidenceStatus, FeedbackRecord, ValidationReport

MAX_CSV_BYTES = 100 * 1024 * 1024  # 100MB 上限

# 模型字段全集（用于识别未知列）
FIELD_NAMES = set(FeedbackRecord.model_fields)

# 可空字符串字段：CSV 空串 -> None
OPTIONAL_NONE_FIELDS = {
    "source_date_raw",
    "product_model",
    "firmware_version",
    "app_version",
    "translated_text",
    "archive_path",
    "archive_sha256",
    "verification_note",
}


def _required_headers() -> set[str]:
    """FeedbackRecord 的必填字段（作为 CSV 必需表头）。"""
    return {name for name, f in FeedbackRecord.model_fields.items() if f.is_required()}


def _coerce_row(raw: dict) -> dict:
    """CSV 行 -> 模型入参：空串处理、未知列丢弃。"""
    values: dict = {}
    for key, value in raw.items():
        if key not in FIELD_NAMES:
            continue  # 未知列已在表头检查中警告
        if isinstance(value, str):
            value = value.strip()
        if key == "market":
            values[key] = "unknown" if value == "" else value
        elif key == "source_date":
            values[key] = None if value == "" else value
        elif key in OPTIONAL_NONE_FIELDS:
            values[key] = None if value == "" else value
        else:
            values[key] = value
    return values


def _validation_notes(exc: ValidationError) -> dict[str, str]:
    """Pydantic 错误 -> {字段: 消息}。"""
    notes: dict[str, str] = {}
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        notes[field] = error["msg"]
    return notes


def _write_rows(path: Path, rows: list[dict], *, with_error: bool = False) -> None:
    """落盘有效/无效行（utf-8-sig，无效行带 error 列）。"""
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(rows[0].keys())
    if with_error and "error" not in fieldnames:
        fieldnames.append("error")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: str, *, out_dir: str | None = None) -> ValidationReport:
    """从 CSV 文件导入反馈记录，返回校验报告。

    - 有效行/无效行分别保存为 `<out_dir>/<stem>_valid.csv` 与 `_invalid.csv`
    - 有效记录在 `report.valid_records`（无效行绝不进入）
    - 重复 feedback_id：后续出现计为无效，保证下游 ID 唯一
    """
    p = Path(path)
    if p.suffix.lower() != ".csv":
        raise ValueError(f"仅支持 CSV 文件: {path}")
    if not p.exists():
        raise ValueError(f"文件不存在: {path}")
    size = p.stat().st_size
    if size == 0:
        raise ValueError(f"文件为空: {path}")
    if size > MAX_CSV_BYTES:
        raise ValueError(f"文件过大（超过 {MAX_CSV_BYTES // 1024 // 1024}MB）: {path}")

    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise ValueError(f"文件编码不是 UTF-8（utf-8-sig）: {path} — {exc}") from exc
    except csv.Error as exc:
        raise ValueError(f"CSV 解析失败: {path} — {exc}") from exc

    report = ValidationReport(total_rows=len(rows))

    missing_cols = sorted(_required_headers() - set(headers))
    if missing_cols:
        raise ValueError(f"CSV 缺少必需列: {missing_cols}")

    extra_cols = sorted(set(headers) - FIELD_NAMES)
    for col in extra_cols:
        report.warnings.append(f"忽略未知列: {col}")

    seen_ids: set[str] = set()
    valid_rows: list[dict] = []
    invalid_rows: list[dict] = []

    for lineno, raw in enumerate(rows, start=2):  # 第1行是表头
        values = _coerce_row(raw)
        feedback_id = values.get("feedback_id", "")

        if not feedback_id:
            report.invalid_rows += 1
            report.missing_fields["feedback_id"] = report.missing_fields.get("feedback_id", 0) + 1
            report.warnings.append(f"第{lineno}行: feedback_id 为空")
            invalid_rows.append({**raw, "error": "feedback_id 为空"})
            continue

        if feedback_id in seen_ids:
            report.invalid_rows += 1
            report.duplicate_ids.append(feedback_id)
            report.warnings.append(f"第{lineno}行 ({feedback_id}): feedback_id 重复")
            invalid_rows.append({**raw, "error": "feedback_id 重复"})
            continue
        seen_ids.add(feedback_id)

        try:
            record = FeedbackRecord(**values)
        except ValidationError as exc:
            report.invalid_rows += 1
            notes = _validation_notes(exc)
            for field in notes:
                report.missing_fields[field] = report.missing_fields.get(field, 0) + 1
            url_value = values.get("source_url", "")
            if url_value and not url_value.startswith("https://"):
                report.invalid_urls.append(f"{feedback_id}: {url_value}")
            for field, msg in notes.items():
                report.warnings.append(f"第{lineno}行 ({feedback_id}): {field} {msg}")
            invalid_rows.append(
                {**raw, "error": "; ".join(f"{k}: {v}" for k, v in notes.items())}
            )
            continue

        report.valid_rows += 1
        report.valid_records.append(record)
        report.valid_raw_rows.append(raw)
        valid_rows.append(raw)
        if record.evidence_status != EvidenceStatus.VERIFIED:
            report.unverified_evidence_count += 1

    out = Path(out_dir) if out_dir else get_config().output_dir / "imports"
    out.mkdir(parents=True, exist_ok=True)
    stem = p.stem
    _write_rows(out / f"{stem}_valid.csv", valid_rows)
    _write_rows(out / f"{stem}_invalid.csv", invalid_rows, with_error=True)
    return report


def load_fixture_json(path: str) -> list[FeedbackRecord]:
    """从 JSON fixture 导入反馈记录（开发期用）。"""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"fixture JSON 解析失败: {path} — {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"fixture JSON 必须是列表: {path}")

    records: list[FeedbackRecord] = []
    for idx, row in enumerate(data, start=1):
        try:
            records.append(FeedbackRecord(**row))
        except ValidationError as exc:
            raise ValueError(
                f"fixture 第{idx}条 ({row.get('feedback_id', '<unknown>')}) 校验失败: {exc}"
            ) from exc
    return records
