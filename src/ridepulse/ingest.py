"""数据导入模块 — CSV 读取与 FeedbackRecord 构造。

实现要求（文档15 §7.5）：
1. UTF-8-SIG 读取，失败时报明确编码错误
2. 表头检查
3. 逐行构造 FeedbackRecord
4. 保存有效行和无效行
5. 无效行不进入后续模型调用
6. 输出 ValidationReport
"""

from __future__ import annotations

from ridepulse.models import FeedbackRecord, ValidationReport


def load_csv(path: str) -> ValidationReport:
    """从 CSV 文件导入反馈记录。"""
    raise NotImplementedError("8月3日实现")


def load_fixture_json(path: str) -> list[FeedbackRecord]:
    """从 JSON fixture 导入反馈记录（开发期用）。"""
    raise NotImplementedError("8月3日实现")
