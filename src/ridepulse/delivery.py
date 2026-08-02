"""交付模块 — 证据卡推送飞书并处理状态回流。

实现要求（文档15 §9.4 最小真实闭环）：
1. 批准证据卡 -> 推送飞书 -> 飞书出现记录
2. 飞书修改状态 -> 系统重新读取/手动同步 -> 本地记录成功
"""

from __future__ import annotations


def push_card(feishu_client, card: dict, run_id: str) -> str:
    """推送一张证据卡到飞书，返回远程记录 ID。"""
    raise NotImplementedError("8月10日实现")
