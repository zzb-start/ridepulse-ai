"""交付模块 — 证据卡推送飞书并处理状态回流。

实现要求（文档15 §9.4 最小真实闭环）：
1. 批准证据卡 -> 推送飞书 -> 飞书出现记录
2. 飞书修改状态 -> 系统重新读取/手动同步 -> 本地记录成功
"""

from __future__ import annotations

from typing import Any


def push_card(feishu_client: Any, card: dict, run_id: str) -> str:
    """推送一张证据卡到飞书，返回远程记录 ID。

    card: EvidenceCard.model_dump() 结果（含 card_id / cluster_id / title /
          priority_score / priority_level / confidence_level / evidence_ids /
          human_review_status 等）
    """
    record: dict[str, Any] = {
        "card_id": card["card_id"],
        "cluster_id": card["cluster_id"],
        "title": card["title"],
        "priority_score": card["priority_score"],
        "priority_level": card["priority_level"],
        "confidence_level": card["confidence_level"],
        "evidence_ids": ";".join(card.get("evidence_ids", [])),
        "platforms": ";".join(card.get("platforms", [])),
        "brands": ";".join(card.get("brands", [])),
        "human_review_status": card.get("human_review_status", "pending"),
        "run_id": run_id,
    }
    return feishu_client.upsert_record("evidence", record, dedup_field="card_id")


def sync_card_status(feishu_client: Any, remote_record_id: str, status: str) -> None:
    """飞书侧状态回流：把远程记录的 human_review_status 更新为本地值。"""
    feishu_client.update_record_status("evidence", remote_record_id, status)
