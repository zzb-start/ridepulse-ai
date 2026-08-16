"""feishu_client 模块测试。

要求：
1. token 获取并缓存，过期刷新
2. upsert：按 dedup_field 查找，存在更新、不存在创建
3. 限流/超时重试，错误信息不含 Secret
4. Mock HTTP 响应测试
"""

from __future__ import annotations

import json

import httpx
import pytest

from ridepulse.feishu_client import FeishuClient, FeishuError

TABLES = {"evidence": "tbl_evidence"}


def make_client(handler, *, token_expires_in: int = 7200):
    """构造带 Mock Transport 的客户端。"""
    calls = {"token": 0}

    def router(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("tenant_access_token/internal"):
            calls["token"] += 1
            return httpx.Response(200, json={
                "code": 0, "tenant_access_token": "t-abc",
                "expires_in": token_expires_in,
            })
        return handler(request)

    return FeishuClient(app_id="app", app_secret="secret",
                        bitable_app_token="bapp", tables=TABLES,
                        transport=httpx.MockTransport(router)), calls


class TestToken:
    def test_token_cached_and_refreshed(self):
        client, calls = make_client(lambda req: httpx.Response(200, json={"code": 0}))
        assert client.get_tenant_access_token() == "t-abc"
        assert client.get_tenant_access_token() == "t-abc"
        assert calls["token"] == 1  # 缓存命中，未重复请求
        # 模拟过期：直接改过期时间，应重新获取
        client._token_expires_at = 0.0
        assert client.get_tenant_access_token() == "t-abc"
        assert calls["token"] == 2

    def test_token_error_is_sanitized(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 99991663, "msg": "凭证无效"})

        def token_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t"})

        client = FeishuClient(app_id="app", app_secret="secret",
                              bitable_app_token="bapp", tables=TABLES,
                              transport=httpx.MockTransport(
                                  lambda req: token_handler(req)
                                  if "tenant_access_token" in req.url.path else handler(req)
                              ))
        with pytest.raises(FeishuError) as exc:
            client._request("POST", "/open-apis/bitable/v1/apps/bapp/tables/tbl_evidence/records")
        assert "secret" not in str(exc.value).lower()


class TestUpsert:
    def test_create_when_missing(self):
        created = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "search" in request.url.path:
                return httpx.Response(200, json={"code": 0, "items": []})
            created.append(request)
            return httpx.Response(200, json={"code": 0, "record": {"record_id": "rec_new"}})

        client, _ = make_client(handler)
        remote_id = client.upsert_record("evidence", {"card_id": "EC-2026-0001", "title": "T"})
        assert remote_id == "rec_new"
        assert len(created) == 1
        assert json.loads(created[0].content)["fields"]["card_id"] == "EC-2026-0001"

    def test_update_when_exists(self):
        updated = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "search" in request.url.path:
                return httpx.Response(200, json={
                    "code": 0,
                    "items": [{"record_id": "rec_existing"}],
                })
            updated.append(request)
            return httpx.Response(200, json={"code": 0, "record": {"record_id": "rec_existing"}})

        client, _ = make_client(handler)
        remote_id = client.upsert_record("evidence", {"card_id": "EC-2026-0001", "title": "T2"})
        assert remote_id == "rec_existing"
        assert len(updated) == 1
        assert "rec_existing" in updated[0].url.path  # PUT 到已有记录

    def test_missing_table_config_rejected(self):
        client, _ = make_client(lambda req: httpx.Response(200, json={"code": 0}))
        with pytest.raises(FeishuError, match="未配置表"):
            client.upsert_record("nonexistent", {"card_id": "EC-2026-0001"})


class TestUpdateStatus:
    def test_update_record_status(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"code": 0})

        client, _ = make_client(handler)
        client.update_record_status("evidence", "rec_1", "approved")
        assert len(seen) == 1
        body = json.loads(seen[0].content)
        assert body["fields"]["human_review_status"] == "approved"


class TestRetry:
    def test_5xx_retried_then_succeeds(self):
        # upsert 先 search 后 create；search 第一次 500 重试成功，
        # create 一次成功 —— 总请求数 2（search 重试 1 次 + create 1 次）
        attempts = {"search": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "search" in request.url.path:
                attempts["search"] += 1
                if attempts["search"] == 1:
                    return httpx.Response(500, text="boom")
                return httpx.Response(200, json={"code": 0, "items": []})
            return httpx.Response(200, json={"code": 0, "record": {"record_id": "rec_1"}})

        client, _ = make_client(handler)
        remote_id = client.upsert_record("evidence", {"card_id": "EC-2026-0001"})
        assert remote_id == "rec_1"
        assert attempts["search"] == 2
