"""标准 CSV 采集连接器 — 从标准 CSV 产生 RawSourceRecord。"""

from __future__ import annotations

from ridepulse.models import FeedbackRecord


def csv_to_records(path: str) -> list[FeedbackRecord]:
    raise NotImplementedError("8月3日实现")
