"""第一轮 AI 分类模块。

实现要求（文档15 §7.8）：
1. 每条记录单独分类，保持 ID 对应
2. 模型输出经 Pydantic 校验
3. 置信度 < 0.65 自动进入人工复核
4. evidence_status 非 verified 时置信度降级
5. 保存 Prompt 版本、模型名和时间
"""

from __future__ import annotations

from ridepulse.models import ClassificationResult


def classify_batch(records: list, client, prompt_path: str = "prompts/classify_v1.md") -> list[ClassificationResult]:
    """对一批反馈执行分类，返回结果列表。"""
    raise NotImplementedError("8月5日实现")
