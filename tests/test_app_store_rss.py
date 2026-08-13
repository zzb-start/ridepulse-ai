"""App Store 公开评论连接器测试 — 规格来源：文档15 §7.4。

要求：
1. 只访问无需登录的公开接口
2. 明确 User-Agent、超时、最多 3 次重试
3. 保存原始 JSON 快照到 output/<run_id>/raw/
4. 保存 URL、抓取时间、storefront、App ID 和游标
5. 评论 ID 映射为 source_record_id，增量采集（since 游标）
6. 接口无数据时返回清晰状态，不生成伪评论
7. 接口不可达时失败并记录，不转为 HTML 爬虫
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ridepulse.collectors.app_store_rss import APP_STORE_REVIEWS_URL, AppStoreRSSConnector


def review_entry(review_id: str, text: str, rating: str = "5") -> dict:
    return {
        "id": {
            "label": (
                "https://itunes.apple.com/us/reviews/id1555629744?l=en"
                f"&id=1555629744&displayable-entry-id={review_id}"
            )
        },
        "im:name": {"label": "rider"},
        "im:rating": {"label": rating},
        "im:version": {"label": "1.2.0"},
        "title": {"label": "title"},
        "content": {"label": text},
        "link": {"attributes": {"href": f"https://itunes.apple.com/us/reviews/{review_id}"}},
        "updated": {"label": "2025-06-15T10:00:00-07:00"},
    }


def feed_response(*entries) -> httpx.Response:
    return httpx.Response(
        200,
        json={"feed": {"entry": list(entries), "updated": {"label": "2026-08-02T12:00:00Z"}}},
    )


def make_connector(handler, **kwargs) -> AppStoreRSSConnector:
    return AppStoreRSSConnector(
        app_id="1555629744",
        storefront="us",
        transport=httpx.MockTransport(handler),
        backoff_base=0.0,
        **kwargs,
    )


class TestFetch:
    def test_parses_entries_into_reviews(self, tmp_path):
        conn = make_connector(lambda req: feed_response(review_entry("7720123456", "同步失败，活动未显示")))
        reviews = conn.fetch(run_id="RUN-TEST", out_dir=str(tmp_path))
        assert len(reviews) == 1
        r = reviews[0]
        assert r.source_record_id == "7720123456"
        assert r.platform == "App Store"
        assert "同步失败" in r.raw_text
        assert r.fetched_at

    def test_uses_expected_url_with_limit(self):
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return feed_response()

        conn = make_connector(handler)
        conn.fetch(limit=10)
        assert "1555629744" in urls[0]
        assert "storefront=us" in urls[0] or "/us/" in urls[0]
        assert "limit=10" in urls[0]

    def test_sends_explicit_user_agent(self):
        headers: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            headers.append(request.headers.get("User-Agent", ""))
            return feed_response()

        conn = make_connector(handler)
        conn.fetch()
        assert headers[0]

    def test_skips_reviews_at_or_below_since(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return feed_response(review_entry("7000000001", "旧评论"), review_entry("7720123456", "新评论"))

        conn = make_connector(handler)
        # since 等于最新评论 ID：两条都跳过
        assert conn.fetch(since="7720123456") == []
        # since 低于最旧评论 ID：两条都返回
        reviews = conn.fetch(since="7000000000")
        assert len(reviews) == 2

    def test_empty_feed_returns_clear_status(self, tmp_path):
        conn = make_connector(lambda req: feed_response())
        assert conn.fetch(run_id="RUN-TEST", out_dir=str(tmp_path)) == []
        assert conn.last_response["status"] == "empty"

    def test_saves_snapshot_and_metadata(self, tmp_path):
        conn = make_connector(lambda req: feed_response(review_entry("7720123456", "文本")))
        conn.fetch(run_id="RUN-TEST", out_dir=str(tmp_path))

        snapshot = tmp_path / "RUN-TEST" / "raw" / "app_store_rss_us_1555629744.json"
        assert snapshot.exists()
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        assert data["feed"]["entry"]

        meta_path = tmp_path / "RUN-TEST" / "raw" / "app_store_rss_us_1555629744.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["storefront"] == "us"
        assert meta["app_id"] == "1555629744"
        assert meta["cursor"] == "7720123456"
        assert meta["url"]
        assert meta["fetched_at"]
        assert meta["status"] == "ok"


class TestRetry:
    def test_retries_on_5xx_then_succeeds(self):
        events = [httpx.Response(500), feed_response(review_entry("1", "ok"))]
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return events.pop(0)

        conn = make_connector(handler)
        reviews = conn.fetch(limit=1)
        assert len(reviews) == 1
        assert len(calls) == 2

    def test_raises_and_records_status_after_max_retries(self):
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(503)

        conn = make_connector(handler, max_retries=2)
        with pytest.raises(RuntimeError, match="503"):
            conn.fetch()
        assert len(calls) == 3
        assert conn.last_response["status"].startswith("failed")

    def test_timeout_retried_then_succeeds(self):
        events: list = [httpx.ConnectTimeout("timeout", request=None), feed_response(review_entry("1", "ok"))]

        def handler(request: httpx.Request) -> httpx.Response:
            event = events.pop(0)
            if isinstance(event, Exception):
                raise event
            return event

        conn = make_connector(handler)
        assert len(conn.fetch(limit=1)) == 1

    def test_connection_error_raises_without_html_fallback(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        conn = make_connector(handler)
        with pytest.raises(RuntimeError, match="不可达"):
            conn.fetch()
        assert conn.last_response["status"] == "failed_connection"

    def test_malformed_body_raises_not_fake_reviews(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "not found"})

        conn = make_connector(handler)
        with pytest.raises(RuntimeError, match="格式异常"):
            conn.fetch()
