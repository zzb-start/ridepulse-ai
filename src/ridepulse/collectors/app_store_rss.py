"""App Store 公开评论连接器 — Apple 公开评论 JSON 接口。

实现要求：
1. 只访问无需登录的公开接口
2. 请求设置 User-Agent、超时、最多 3 次重试
3. 保存原始 JSON 快照到 output/<run_id>/raw/
4. 保存接口 URL、抓取时间、storefront、App ID 和游标
5. 评论 ID 映射为 source_record_id，增量采集不重复入库
6. 接口无数据时返回清晰状态，不生成伪评论
7. 接口不可达时失败并记录，不转为未经允许的 HTML 爬虫
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

APP_STORE_REVIEWS_URL = (
    "https://itunes.apple.com/{storefront}/rss/customerreviews/"
    "id={app_id}/sortBy=mostRecent/json"
)

USER_AGENT = "RidePulseAI/0.1 (2026 AI Pioneer Competition, Magene Pilot Collector)"


@dataclass
class AppStoreReview:
    source_record_id: str
    platform: str = "App Store"
    url: str = ""
    raw_text: str = ""
    fetched_at: str = ""


def _numeric_id(value: str) -> int | None:
    """评论 ID 转数值用于增量比较；非数字返回 None。"""
    if value.isdigit():
        return int(value)
    return None


class AppStoreRSSConnector:
    """App Store 公开评论连接器。"""

    name = "app_store_rss"

    def __init__(self, *, app_id: str, storefront: str = "us",
                 timeout_seconds: int = 30, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None,
                 backoff_base: float = 0.5) -> None:
        self.app_id = app_id
        self.storefront = storefront
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.last_response: dict = field(default_factory=dict)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    def fetch(self, *, since: str | None = None, limit: int = 50,
              run_id: str | None = None, out_dir: str = "output") -> list[AppStoreReview]:
        """采集评论，返回 AppStoreReview 列表。

        - `since` 为已入库的最新评论 ID 游标，<= since 的评论跳过（增量采集）
        - 原始 JSON 快照与元数据保存到 `out_dir/<run_id>/raw/`
        - 无数据时 last_response.status = "empty"，不生成伪评论
        """
        url = (
            f"{APP_STORE_REVIEWS_URL.format(storefront=self.storefront, app_id=self.app_id)}"
            f"?limit={limit}"
        )
        fetched_at = datetime.now().isoformat(timespec="seconds")
        self.last_response = {
            "url": url,
            "fetched_at": fetched_at,
            "storefront": self.storefront,
            "app_id": self.app_id,
            "status": "ok",
            "cursor": since,
        }

        response = self._fetch_raw(url)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"App Store 接口返回非 JSON: {url}") from None

        feed = data.get("feed")
        if not isinstance(feed, dict):
            self.last_response["status"] = "malformed"
            raise RuntimeError(f"App Store 接口响应格式异常: {url}")

        entries = feed.get("entry") or []
        if not entries:
            self.last_response["status"] = "empty"
            self._save_snapshot(data, fetched_at, run_id, out_dir)
            return []

        reviews: list[AppStoreReview] = []
        for entry in entries:
            review_id = self._review_id(entry)
            if review_id is None:
                continue
            if since is not None and self._is_old(review_id, since):
                continue
            reviews.append(self._to_review(entry, review_id, fetched_at))

        if reviews:
            self.last_response["cursor"] = max(r.source_record_id for r in reviews)
        self._save_snapshot(data, fetched_at, run_id, out_dir)
        logger.info(
            "App Store 采集完成: storefront=%s app_id=%s 新评论=%d",
            self.storefront, self.app_id, len(reviews),
        )
        return reviews

    # ----------------------------------------------------------
    # 内部实现
    # ----------------------------------------------------------

    def _fetch_raw(self, url: str) -> httpx.Response:
        """带重试的 GET：只对超时、429、5xx 重试，最多 max_retries 次。"""
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self._client.get(url)
                status = response.status_code
                if status == 429 or status >= 500:
                    if attempts <= self.max_retries:
                        self._backoff(attempts)
                        continue
                    self.last_response = {"url": url, "status": f"failed_http_{status}"}
                    raise RuntimeError(
                        f"App Store 接口返回 HTTP {status}，重试耗尽: {url}"
                    )
                if status >= 400:
                    self.last_response = {"url": url, "status": f"failed_http_{status}"}
                    raise RuntimeError(
                        f"App Store 接口拒绝请求（HTTP {status}）: {url}"
                    )
                return response
            except httpx.TimeoutException as exc:
                if attempts <= self.max_retries:
                    self._backoff(attempts)
                    continue
                self.last_response = {"url": url, "status": "failed_timeout"}
                raise RuntimeError(
                    f"App Store 接口超时（{self.timeout_seconds}s），重试耗尽: {url}"
                ) from exc
            except httpx.RequestError as exc:
                self.last_response = {"url": url, "status": "failed_connection"}
                raise RuntimeError(f"App Store 接口不可达: {url} — {exc}") from exc

    def _backoff(self, attempts: int) -> None:
        """指数退避，封顶 5 秒。"""
        time.sleep(min(self.backoff_base * (2 ** (attempts - 1)), 5.0))

    @staticmethod
    def _review_id(entry: dict) -> str | None:
        """从 entry 的 id label 提取评论 ID（displayable-entry-id 最后一段）。"""
        label = (entry.get("id") or {}).get("label", "")
        if not label:
            return None
        return label.rsplit("=", 1)[-1] or None

    def _is_old(self, review_id: str, since: str) -> bool:
        """评论是否早于/等于游标（数值比较，非数值回退字符串比较）。"""
        rid, sid = _numeric_id(review_id), _numeric_id(since)
        if rid is not None and sid is not None:
            return rid <= sid
        return review_id <= since

    def _to_review(self, entry: dict, review_id: str, fetched_at: str) -> AppStoreReview:
        link = (entry.get("link") or {}).get("attributes") or {}
        return AppStoreReview(
            source_record_id=review_id,
            url=link.get("href", ""),
            raw_text=((entry.get("content") or {}).get("label") or "").strip(),
            fetched_at=fetched_at,
        )

    def _save_snapshot(self, data: dict, fetched_at: str, run_id: str | None,
                       out_dir: str) -> None:
        """保存原始 JSON 快照与采集元数据。"""
        run_id = run_id or f"RUN-{datetime.now():%Y%m%d-%H%M%S}"
        raw_dir = Path(out_dir) / run_id / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        name = f"app_store_rss_{self.storefront}_{self.app_id}"
        (raw_dir / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta = {
            "url": self.last_response.get("url"),
            "fetched_at": fetched_at,
            "storefront": self.storefront,
            "app_id": self.app_id,
            "cursor": self.last_response.get("cursor"),
            "status": self.last_response.get("status"),
        }
        (raw_dir / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
