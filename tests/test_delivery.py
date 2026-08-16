"""delivery 模块测试 — 最小真实闭环。

要求：
1. 批准证据卡 -> 推送飞书 -> 飞书出现记录
2. 飞书修改状态 -> 系统同步 -> 本地记录成功
"""

from __future__ import annotations

from ridepulse.delivery import push_card, sync_card_status
from ridepulse.feishu_client import FakeFeishuClient


def make_card() -> dict:
    return {
        "card_id": "EC-2026-0001",
        "cluster_id": "CL-0001",
        "title": "同步失败问题",
        "priority_score": 88,
        "priority_level": "P0",
        "confidence_level": "high",
        "evidence_ids": ["F0001", "F0002"],
        "platforms": ["App Store", "论坛"],
        "brands": ["Magene"],
        "human_review_status": "approved",
    }


class TestPushCard:
    def test_card_appears_in_feishu(self):
        client = FakeFeishuClient()
        remote_id = push_card(client, make_card(), "RUN-20260811-120000")
        assert remote_id.startswith("rec_")
        store = client.records["evidence"]
        assert len(store) == 1
        assert store[0]["card_id"] == "EC-2026-0001"
        assert store[0]["run_id"] == "RUN-20260811-120000"

    def test_upsert_prevents_duplicate(self):
        client = FakeFeishuClient()
        first = push_card(client, make_card(), "RUN-20260811-120000")
        second = push_card(client, make_card(), "RUN-20260811-120000")
        assert first == second
        assert len(client.records["evidence"]) == 1  # 按 card_id 去重


class TestSyncStatus:
    def test_status_flows_back(self):
        client = FakeFeishuClient()
        remote_id = push_card(client, make_card(), "RUN-20260811-120000")
        sync_card_status(client, remote_id, "rejected")
        assert client.records["evidence"][0]["human_review_status"] == "rejected"
