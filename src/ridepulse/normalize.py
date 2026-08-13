"""文本规范化模块。

实现要求（文档15 §7.6）：
1. Unicode NFKC 规范化
2. 合并多余空白
3. 保留原文，不覆盖 original_text
4. 品牌/型号别名统一（Magene/迈金 -> Magene）
5. 版本号规范化但保留原始文本
"""

from __future__ import annotations

import re
import unicodedata

# 品牌别名表：原文 -> 统一品牌字段值
BRAND_ALIASES: dict[str, str] = {
    "迈金": "Magene",
    "迈金科技": "Magene",
    "magene": "Magene",
    "佳明": "Garmin",
    "garmin": "Garmin",
    "百锐腾": "Bryton",
    "bryton": "Bryton",
    "wahoo": "Wahoo",
    "行者": "XOSS",
    "xoss": "XOSS",
}

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFKC + 空白合并。

    只用于比对/索引，绝不回写 original_text。
    """
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = _WHITESPACE_RUN.sub(" ", normalized)
    return collapsed.strip()


def normalize_brand(raw: str) -> str:
    """品牌别名统一（大小写不敏感）。

    未知品牌原样返回（去除首尾空白），不做猜测映射。
    """
    cleaned = raw.strip()
    if not cleaned:
        return ""
    return BRAND_ALIASES.get(cleaned) or BRAND_ALIASES.get(cleaned.lower(), cleaned)


def normalize_version(raw: str | None) -> str | None:
    """版本号规范化：去 v 前缀、合并空白。

    只用于比对/展示，调用方仍需保留原始版本文本。
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered.startswith("v") and len(lowered) > 1 and lowered[1].isdigit():
        cleaned = cleaned[1:]
    return _WHITESPACE_RUN.sub(" ", cleaned).strip()
