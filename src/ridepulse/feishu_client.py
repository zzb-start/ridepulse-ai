"""飞书开放平台客户端 — 多维表格推送。

实现要求（文档15 §9）：
1. 获取并缓存 tenant_access_token，过期刷新
2. 创建/更新记录，按 card_id 查找防止重复
3. 处理限流、超时和权限错误
4. 错误信息不得包含 Secret
5. 测试使用 Mock HTTP 响应
"""

from __future__ import annotations

from typing import Any


class FeishuClient:
    """飞书多维表格客户端。"""

    def __init__(self, *, app_id: str, app_secret: str,
                 bitable_app_token: str, tables: dict[str, str] | None = None) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        self.tables = tables or {}
        self._token: str | None = None

    def get_tenant_access_token(self) -> str:
        raise NotImplementedError("8月10日实现")

    def upsert_record(self, table_key: str, record: dict[str, Any], dedup_field: str = "card_id") -> str:
        """按 dedup_field 查找，存在则更新，不存在则创建。返回远程记录 ID。"""
        raise NotImplementedError("8月10日实现")

    def update_record_status(self, table_key: str, remote_record_id: str, status: str) -> None:
        raise NotImplementedError("8月10日实现")


class FakeFeishuClient(FeishuClient):
    """测试用假客户端。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(app_id="fake", app_secret="fake", bitable_app_token="fake", **kwargs)
        self.records: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str, dict]] = []

    def get_tenant_access_token(self) -> str:
        return "fake-token"

    def upsert_record(self, table_key: str, record: dict, dedup_field: str = "card_id") -> str:
        self.calls.append((table_key, "upsert", record))
        store = self.records.setdefault(table_key, [])
        remote_id = f"rec_{len(store) + 1}"
        store.append({**record, "_remote_id": remote_id})
        return remote_id

    def update_record_status(self, table_key: str, remote_record_id: str, status: str) -> None:
        self.calls.append((table_key, "update_status", {"id": remote_record_id, "status": status}))
