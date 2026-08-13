"""数据校验模块 — FeedbackRecord 字段级校验。

实现要求（文档15 §7.5）：
- 校验报告: total_rows / valid_rows / invalid_rows / duplicate_ids /
  missing_fields / invalid_urls / unverified_evidence_count / warnings
- 给出坏 CSV 时指出具体行和字段

主要校验逻辑在 ingest.load_csv（逐行 Pydantic 校验 + 行号/字段定位），
本模块提供单行字段级校验与报告渲染，供 CLI validate 与上游调用复用。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ridepulse.ingest import _coerce_row, _validation_notes
from ridepulse.models import FeedbackRecord, ValidationReport


def validate_row(raw: dict[str, Any]) -> tuple[FeedbackRecord | None, dict[str, str]]:
    """单行字段级校验：返回 (记录, 错误字典)。

    - 空 feedback_id 视为缺失
    - 错误字典 {字段: 消息}，字段级定位（文档15 §7.5 验收要求）
    """
    values = _coerce_row(raw)
    feedback_id = values.get("feedback_id", "")
    if not feedback_id:
        return None, {"feedback_id": "feedback_id 为空"}
    try:
        return FeedbackRecord(**values), {}
    except ValidationError as exc:
        return None, _validation_notes(exc)


def render_report(report: ValidationReport) -> str:
    """把校验报告渲染为可读文本（CLI 输出用）。"""
    lines = [
        f"总数: {report.total_rows}  有效: {report.valid_rows}  无效: {report.invalid_rows}",
        f"未核验证据: {report.unverified_evidence_count}",
    ]
    if report.duplicate_ids:
        lines.append(f"重复 ID ({len(report.duplicate_ids)}): {report.duplicate_ids[:20]}")
    if report.missing_fields:
        lines.append(f"字段问题: {report.missing_fields}")
    if report.invalid_urls:
        lines.append(f"非法 URL ({len(report.invalid_urls)}): {report.invalid_urls[:10]}")
    for warning in report.warnings[:100]:
        lines.append(f"  [警告] {warning}")
    if len(report.warnings) > 100:
        lines.append(f"  … 其余 {len(report.warnings) - 100} 条警告省略")
    return "\n".join(lines)
