"""采集连接器统一接口。"""

from __future__ import annotations

from typing import Protocol


class RawSourceRecord(Protocol):
    """原始采集记录。"""

    source_record_id: str
    platform: str
    url: str
    raw_text: str
    fetched_at: str


class SourceConnector(Protocol):
    """连接器协议。"""

    name: str

    def fetch(self, *, since: str | None, limit: int) -> list[RawSourceRecord]:
        ...
