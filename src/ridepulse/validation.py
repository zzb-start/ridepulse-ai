"""数据校验模块 — FeedbackRecord 字段级校验。

实现要求（文档15 §7.5）：
- 校验报告: total_rows / valid_rows / invalid_rows / duplicate_ids /
  missing_fields / invalid_urls / unverified_evidence_count / warnings
- 给出坏 CSV 时指出具体行和字段
"""

from __future__ import annotations

from ridepulse.models import ValidationReport
