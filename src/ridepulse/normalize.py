"""文本规范化模块。

实现要求（文档15 §7.6）：
1. Unicode NFKC 规范化
2. 合并多余空白
3. 保留原文，不覆盖 original_text
4. 品牌/型号别名统一（Magene/迈金 -> Magene）
5. 版本号规范化但保留原始文本
"""

from __future__ import annotations


def normalize_text(text: str) -> str:
    """NFKC + 空白合并。"""
    raise NotImplementedError("8月4日实现")


def normalize_brand(raw: str) -> str:
    """品牌别名统一。"""
    raise NotImplementedError("8月4日实现")
