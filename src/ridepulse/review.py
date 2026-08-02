"""独立第二轮复判模块。

实现要求（文档15 §7.9）：
- 复判输入只能包含原始反馈和必要元数据，不能把第一轮结果告诉复判模型
- 对比字段: sentiment / theme_primary / need_type / severity / purchase_impact
- 冲突规则见 DATA_CONTRACT_v1.md §5
"""

from __future__ import annotations

from ridepulse.models import ClassificationResult, ReviewResult


def compare_and_judge(primary: ClassificationResult, review: ReviewResult) -> ReviewResult:
    """比较两轮结果，返回带 conflict_fields / human_review_required 的最终 ReviewResult。

    注意：本函数接收两轮结果进行确定性对比；复判模型本身必须独立调用。
    """
    raise NotImplementedError("8月6日实现")


def review_batch(records: list, primary_results: list[ClassificationResult],
                 client, prompt_path: str = "prompts/review_v1.md") -> list[ReviewResult]:
    """独立复判一批反馈。"""
    raise NotImplementedError("8月6日实现")
