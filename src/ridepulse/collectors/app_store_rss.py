"""App Store 公开评论连接器 — Apple 公开评论 JSON 接口。

实现要求（文档15 §7.4）：
1. 只访问无需登录的公开接口
2. 请求设置 User-Agent、超时、最多 3 次重试
3. 保存原始 JSON 快照到 output/<run_id>/raw/
4. 保存接口 URL、抓取时间、storefront、App ID 和游标
5. 评论 ID 映射为 source_record_id，增量采集不重复入库
6. 接口无数据时返回清晰状态，不生成伪评论
7. 接口不可达时失败并记录，不转为未经允许的 HTML 爬虫
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

APP_STORE_REVIEWS_URL = (
    "https://itunes.apple.com/{storefront}/rss/customerreviews/"
    "id={app_id}/sortBy=mostRecent/json"
)


@dataclass
class AppStoreReview:
    source_record_id: str
    platform: str = "App Store"
    url: str = ""
    raw_text: str = ""
    fetched_at: str = ""


class AppStoreRSSConnector:
    """App Store 公开评论连接器。"""

    name = "app_store_rss"

    def __init__(self, *, app_id: str, storefront: str = "us",
                 timeout_seconds: int = 30, max_retries: int = 3) -> None:
        self.app_id = app_id
        self.storefront = storefront
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.last_response: dict = field(default_factory=dict)

    def fetch(self, *, since: str | None = None, limit: int = 50) -> list[AppStoreReview]:
        """采集评论，返回 AppStoreReview 列表。"""
        raise NotImplementedError("8月3日实现")

    def _fetch_raw(self, url: str) -> httpx.Response:
        raise NotImplementedError("8月3日实现")
