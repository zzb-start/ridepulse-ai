"""独立第二轮复判模块。

实现要求：
- 复判输入只能包含原始反馈和必要元数据，不能把第一轮结果告诉复判模型
- 对比字段: sentiment / theme_primary / need_type / severity / purchase_impact
- 冲突规则：
  1. 任一核心字段不同 -> conflict_fields
  2. theme_primary / need_type / severity 冲突 -> 必须人工复核
  3. 情感相差 2 级以上 -> 必须人工复核
  4. 两轮都低置信度 -> 必须人工复核
  5. 第二轮调用失败 -> 必须人工复核（review_status=failed）
- 人工复核状态机: pending -> approved / corrected / rejected
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ridepulse.llm_client import LLMClientError
from ridepulse.models import (
    ClassificationResult,
    HumanReview,
    HumanReviewStatus,
    NeedType,
    PurchaseImpact,
    ReviewConflictStatus,
    ReviewResult,
    Sentiment,
    Severity,
    ThemePrimary,
)

logger = logging.getLogger(__name__)

# 对比字段（两轮结果逐字段比较）
COMPARE_FIELDS = ("sentiment", "theme_primary", "need_type", "severity", "purchase_impact")
# 冲突时必须人工复核的字段
MUST_REVIEW_FIELDS = {"theme_primary", "need_type", "severity"}
# 低置信度阈值（与 classify 一致）
LOW_CONFIDENCE_THRESHOLD = 0.65
# 情感相差达到该值必须人工复核
SENTIMENT_GAP_REQUIRING_REVIEW = 2


def _load_system_prompt(prompt_path: str) -> str:
    """读取 Prompt 文件；缺失时回退默认提示词。"""
    candidates = [
        Path(prompt_path),
        Path(__file__).resolve().parents[2] / prompt_path,  # 仓库根目录相对路径
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return (
        "你是一个独立的骑行产品用户反馈复核员。只依据输入原文独立判断，"
        "无法确定时填 unknown。只输出 JSON，键包括：review_sentiment, "
        "review_theme_primary, review_need_type, review_severity, "
        "review_purchase_impact, review_jtbd, review_confidence。"
    )


def _prompt_version(prompt_path: str) -> str:
    """Prompt 版本号取文件名（不含扩展名）。"""
    return Path(prompt_path).stem or "review_v1"


def _build_review_prompt(record) -> str:
    """复判用户消息：只含原始反馈与必要元数据，绝不包含第一轮分类结果。"""
    lines = [f"【原文】{record.original_text}"]
    if record.translated_text:
        lines.append(f"【中文译文】{record.translated_text}")
    lines.append(f"【品牌】{record.brand}")
    if record.product_model:
        lines.append(f"【产品型号】{record.product_model}")
    lines.append(f"【语言】{record.language}")
    lines.append(f"【来源平台】{record.source_platform}")
    return "\n".join(lines)


def _diff_fields(primary: ClassificationResult, review: ReviewResult) -> list[str]:
    """两轮结果在对比字段上的差异列表。"""
    return [
        field
        for field in COMPARE_FIELDS
        if getattr(primary, field) != getattr(review, f"review_{field}")
    ]


def _failed_review(feedback_id: str, model_name: str, prompt_version: str) -> ReviewResult:
    """构造复判失败占位结果：状态 failed，必须人工复核。

    失败记录不使用任何猜测字段——review_* 字段为显式哨兵值，
    下游必须优先检查 review_status == failed。
    """
    return ReviewResult(
        feedback_id=feedback_id,
        review_sentiment=Sentiment.NEUTRAL,
        review_theme_primary=ThemePrimary.OTHER,
        review_need_type=NeedType.UNKNOWN,
        review_severity=Severity.S5,
        review_purchase_impact=PurchaseImpact.UNKNOWN,
        review_jtbd="复判调用失败，未生成独立判断",
        review_confidence=0.0,
        conflict_fields=[],
        review_status=ReviewConflictStatus.FAILED,
        human_review_required=True,
        model_name=model_name,
        prompt_version=prompt_version,
    )


def compare_and_judge(primary: ClassificationResult, review: ReviewResult) -> ReviewResult:
    """确定性对比两轮结果，返回带 conflict_fields / review_status / human_review_required 的最终结果。

    不修改入参；复判模型本身必须独立调用（见 review_batch）。
    """
    if review.review_status == ReviewConflictStatus.FAILED:
        return review.model_copy()

    conflicts = _diff_fields(primary, review)

    if conflicts:
        review_status = ReviewConflictStatus.CONFLICT
    else:
        review_status = ReviewConflictStatus.AGREED

    human_review_required = False
    if any(field in MUST_REVIEW_FIELDS for field in conflicts):
        human_review_required = True
    if abs(primary.sentiment - review.review_sentiment) >= SENTIMENT_GAP_REQUIRING_REVIEW:
        human_review_required = True
    if (
        primary.confidence < LOW_CONFIDENCE_THRESHOLD
        and review.review_confidence < LOW_CONFIDENCE_THRESHOLD
    ):
        human_review_required = True

    return review.model_copy(
        update={
            "conflict_fields": conflicts,
            "review_status": review_status,
            "human_review_required": human_review_required,
        }
    )


def review_batch(records: list, primary_results: list[ClassificationResult],
                 client, prompt_path: str = "prompts/review_v1.md") -> list[ReviewResult]:
    """独立复判一批反馈，返回与输入同序、一一对应的最终 ReviewResult。

    - 每条单独独立调用，用户消息只含原文与必要元数据
    - 调用失败或输出未通过校验 -> review_status=failed，必须人工复核
    - 成功输出经 compare_and_judge 与第一轮对比
    """
    system = _load_system_prompt(prompt_path)
    prompt_version = _prompt_version(prompt_path)

    results: list[ReviewResult] = []
    for record, primary in zip(records, primary_results):
        try:
            raw = client.complete_json(system, _build_review_prompt(record))
            # 系统字段由代码注入，不信任模型回显
            raw["feedback_id"] = record.feedback_id
            raw["model_name"] = client.model
            raw["prompt_version"] = prompt_version
            raw["conflict_fields"] = []
            raw["human_review_required"] = False
            raw["review_status"] = ReviewConflictStatus.AGREED  # 占位，compare_and_judge 覆盖
            review = ReviewResult.model_validate(raw)
        except (LLMClientError, ValidationError) as exc:
            logger.warning("复判失败 (%s): %s", record.feedback_id, exc)
            results.append(
                _failed_review(record.feedback_id, client.model, prompt_version)
            )
            continue
        results.append(compare_and_judge(primary, review))
    return results


def apply_human_decision(*, primary: ClassificationResult, review: ReviewResult,
                         final_sentiment: Sentiment, final_theme_primary: ThemePrimary,
                         final_need_type: NeedType, final_severity: Severity,
                         final_purchase_impact: PurchaseImpact,
                         reviewer: str, note: str, rejected: bool = False) -> HumanReview:
    """人工复核：pending -> approved / corrected / rejected。

    记录原始分类、复判分类、冲突字段、最终字段、复核理由、复核人标识与时间。
    状态判定：
    - rejected=True -> rejected
    - 最终字段与两轮结果均一致 -> approved
    - 最终字段与至少一轮不同（冲突裁决）-> corrected
    """
    if rejected:
        status = HumanReviewStatus.REJECTED
    elif (
        final_sentiment == primary.sentiment
        and final_theme_primary == primary.theme_primary
        and final_need_type == primary.need_type
        and final_severity == primary.severity
        and final_purchase_impact == primary.purchase_impact
        and final_sentiment == review.review_sentiment
        and final_theme_primary == review.review_theme_primary
        and final_need_type == review.review_need_type
        and final_severity == review.review_severity
        and final_purchase_impact == review.review_purchase_impact
    ):
        status = HumanReviewStatus.APPROVED
    else:
        status = HumanReviewStatus.CORRECTED

    return HumanReview(
        feedback_id=primary.feedback_id,
        primary_result=primary,
        review_result=review,
        conflict_fields=_diff_fields(primary, review),
        final_sentiment=final_sentiment,
        final_theme_primary=final_theme_primary,
        final_need_type=final_need_type,
        final_severity=final_severity,
        final_purchase_impact=final_purchase_impact,
        review_status=status,
        review_note=note,
        reviewer=reviewer,
        reviewed_at=datetime.now(),
    )
