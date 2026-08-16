"""飞书开放平台客户端 — 多维表格推送。

实现要求：
1. 获取并缓存 tenant_access_token，过期刷新
2. 创建/更新记录，按 card_id 查找防止重复
3. 处理限流、超时和权限错误
4. 错误信息不得包含 Secret
5. 测试使用 Mock HTTP 响应
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FEISHU_BASE_URL = "https://open.feishu.cn"
# 默认表名 -> 表 ID 配置键（Config.feishu_*_table_id）
DEFAULT_TABLES = {
    "feedback": "feishu_feedback_table_id",
    "evidence": "feishu_evidence_table_id",
    "review": "feishu_review_table_id",
    "experiment": "feishu_experiment_table_id",
}


class FeishuError(Exception):
    """飞书 API 调用失败（消息已脱敏，不含 Secret）。"""


class FeishuClient:
    """飞书多维表格客户端。"""

    def __init__(self, *, app_id: str, app_secret: str,
                 bitable_app_token: str, tables: dict[str, str] | None = None,
                 timeout_seconds: int = 30, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        # tables: {"evidence": "表ID", ...}
        self.tables = tables or {}
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._client = httpx.Client(
            base_url=FEISHU_BASE_URL,
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # ----------------------------------------------------------
    # Token
    # ----------------------------------------------------------

    def get_tenant_access_token(self) -> str:
        """获取并缓存 tenant_access_token，过期（提前60秒）自动刷新。"""
        if self._token and time.monotonic() < self._token_expires_at - 60:
            return self._token
        resp = self._client.post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        self._raise_for_status(resp, "获取 token")
        data = resp.json()
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuError(f"飞书 token 响应异常: code={data.get('code')}")
        self._token = token
        self._token_expires_at = time.monotonic() + float(data.get("expires_in", 7200))
        return token

    # ----------------------------------------------------------
    # 记录操作
    # ----------------------------------------------------------

    def _table_id(self, table_key: str) -> str:
        table_id = self.tables.get(table_key)
        if not table_id:
            raise FeishuError(f"未配置表: {table_key}（请设置 FEISHU_{table_key.upper()}_TABLE_ID）")
        return table_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_tenant_access_token()}"}

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        """带重试的请求（仅 429 / 5xx 重试）。"""
        attempts = 0
        while True:
            attempts += 1
            resp = self._client.request(method, path, headers=self._headers(), json=json_body)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempts <= self.max_retries:
                    time.sleep(min(0.5 * (2 ** (attempts - 1)), 5.0))
                    continue
                raise FeishuError(f"飞书服务错误（HTTP {resp.status_code}），重试耗尽")
            if resp.status_code >= 400:
                raise FeishuError(f"飞书请求被拒绝（HTTP {resp.status_code}）: {resp.text[:200]}")
            data = resp.json()
            if data.get("code") not in (0, None):
                raise FeishuError(f"飞书业务错误 code={data.get('code')}: {data.get('msg', '')[:200]}")
            return data

    def upsert_record(self, table_key: str, record: dict[str, Any],
                      dedup_field: str = "card_id") -> str:
        """按 dedup_field 查找，存在则更新，不存在则创建。返回远程记录 ID。

        先按 dedup_field 精确过滤搜索；命中更新、未命中创建。
        """
        table_id = self._table_id(table_key)
        dedup_value = record.get(dedup_field)

        if dedup_value is not None:
            search = self._request(
                "POST",
                f"/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{table_id}/records/search",
                json_body={
                    "filter": {"conjunction": "and", "conditions": [
                        {"field_name": dedup_field, "operator": "is", "value": [str(dedup_value)]},
                    ]},
                    "page_size": 1,
                },
            )
            items = (search.get("items") or [])
            if items:
                remote_id = items[0]["record_id"]
                self._request(
                    "PUT",
                    f"/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{table_id}/records/{remote_id}",
                    json_body={"fields": record},
                )
                logger.info("飞书更新记录: table=%s %s=%s", table_key, dedup_field, dedup_value)
                return remote_id

        created = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{table_id}/records",
            json_body={"fields": record},
        )
        remote_id = (created.get("record") or {}).get("record_id")
        if not remote_id:
            raise FeishuError(f"飞书创建记录响应缺少 record_id (table={table_key})")
        logger.info("飞书创建记录: table=%s %s=%s", table_key, dedup_field, dedup_value)
        return remote_id

    def update_record_status(self, table_key: str, remote_record_id: str, status: str) -> None:
        """更新远程记录的 human_review_status 字段（状态回流）。"""
        table_id = self._table_id(table_key)
        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{table_id}/records/{remote_record_id}",
            json_body={"fields": {"human_review_status": status}},
        )
        logger.info("飞书状态回流: %s -> %s", remote_record_id, status)

    def _raise_for_status(self, resp: httpx.Response, context: str) -> None:
        """HTTP 错误统一转 FeishuError（消息不包含 Secret）。"""
        if resp.status_code >= 400:
            raise FeishuError(f"飞书 {context} 失败（HTTP {resp.status_code}）: {resp.text[:200]}")


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
        existing = next((r for r in store if r.get(dedup_field) == record.get(dedup_field)), None)
        if existing:
            existing.update(record)
            return existing["_remote_id"]
        remote_id = f"rec_{len(store) + 1}"
        store.append({**record, "_remote_id": remote_id})
        return remote_id

    def update_record_status(self, table_key: str, remote_record_id: str, status: str) -> None:
        self.calls.append((table_key, "update_status", {"id": remote_record_id, "status": status}))
        for store in self.records.values():
            for row in store:
                if row.get("_remote_id") == remote_record_id:
                    row["human_review_status"] = status
