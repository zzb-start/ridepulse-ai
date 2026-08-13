"""标准 CSV 采集连接器。

试点采集方式为"标准 CSV + 至少一个合规公开应用商店连接器"（M1 冻结范围），
因此标准 CSV 是主输入格式：直接复用 ingest.load_csv 的字段级校验，
产生可直接进入后续流水线的 FeedbackRecord（跳过 RawSourceRecord 中间层）。
"""

from __future__ import annotations

from ridepulse.ingest import load_csv
from ridepulse.models import FeedbackRecord


def csv_to_records(path: str) -> list[FeedbackRecord]:
    """从标准 CSV 产生 FeedbackRecord 列表（无效行被排除并落盘为 invalid.csv）。"""
    report = load_csv(path)
    return report.valid_records
