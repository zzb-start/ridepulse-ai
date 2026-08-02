"""Pipeline 编排模块 — 每次运行按固定状态推进。

状态流（文档15 §7.15）：
CREATED -> COLLECTED_OR_IMPORTED -> VALIDATED -> DEDUPED -> CLASSIFIED
-> REVIEWED -> WAITING_HUMAN_REVIEW 或 CLUSTERED -> SCORED
-> CARDS_GENERATED -> WAITING_CARD_APPROVAL -> DELIVERED -> COMPLETED
-> FAILED

要求：失败保留前序结果、可断点重试、输出到 output/<run_id>/、
生成 run_summary.json 和 run_report.md。
"""

from __future__ import annotations

from ridepulse.models import PipelineState


class Pipeline:
    """一次完整运行的编排器。"""

    def __init__(self, *, run_id: str, db=None, config=None) -> None:
        self.run_id = run_id
        self.db = db
        self.config = config
        self.state = PipelineState.CREATED

    def run(self, input_path: str) -> dict:
        """执行完整流水线，返回运行摘要。"""
        raise NotImplementedError("8月9日实现")

    def resume(self) -> dict:
        """从失败步骤恢复。"""
        raise NotImplementedError("8月9日实现")
