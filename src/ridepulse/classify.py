"""第一轮 AI 分类模块。

实现要求：
1. 每条记录单独分类，保持 ID 对应
2. 模型输出经 Pydantic 校验
3. 置信度 < 0.65 自动进入人工复核（下游据此判定）
4. evidence_status 非 verified 时置信度降级
5. 保存 Prompt 版本、模型名和时间
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from ridepulse.llm_client import LLMClientError, REPAIR_SYSTEM_PROMPT
from ridepulse.models import (
    ClassificationResult,
    EvidenceStatus,
    FeedbackRecord,
    NeedType,
    PurchaseImpact,
    Scenario,
    Sentiment,
    Severity,
    ThemePrimary,
    UserType,
)

logger = logging.getLogger(__name__)

# evidence_status 非 verified 时的置信度上限：
# 未核验证据不得以高置信度跳过人工复核（0.6 < 0.65 必然进入复核）
UNVERIFIED_CONFIDENCE_CAP = 0.6

# 修复调用时反馈给模型的合法枚举清单（与 models.py 保持一致，程序生成不硬编码）
_ENUM_HINT = (
    "合法枚举：sentiment ∈ {1,2,3,4,5}；"
    f"theme_primary ∈ {{{', '.join(e.value for e in ThemePrimary)}}}；"
    f"need_type ∈ {{{', '.join(e.value for e in NeedType)}}}；"
    f"severity ∈ {{{', '.join(e.value for e in Severity)}}}；"
    f"purchase_impact ∈ {{{', '.join(e.value for e in PurchaseImpact)}}}；"
    f"scenario ∈ {{{', '.join(e.value for e in Scenario)}}}；"
    f"user_type ∈ {{{', '.join(e.value for e in UserType)}}}；"
    "theme_secondary 为 theme_primary 值的数组；confidence ∈ [0,1]；"
    "is_actionable / is_constructive 为布尔值。"
)

DEFAULT_SYSTEM_PROMPT = (
    "你是一个骑行产品用户反馈分类助手。只依据输入原文分类，无法确定时填 unknown。"
    "只输出 JSON，键包括：sentiment, theme_primary, theme_secondary, need_type, "
    "scenario, user_type, severity, purchase_impact, jtbd, root_cause_hypotheses, "
    "is_actionable, is_constructive, confidence, rationale。"
)


def _load_system_prompt(prompt_path: str) -> str:
    """读取 Prompt 文件；缺失时回退默认提示词。"""
    candidates = [
        Path(prompt_path),
        Path(__file__).resolve().parents[2] / prompt_path,  # 仓库根目录相对路径
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return DEFAULT_SYSTEM_PROMPT


def _prompt_version(prompt_path: str) -> str:
    """Prompt 版本号取文件名（不含扩展名）。"""
    return Path(prompt_path).stem or "classify_v1"


def _build_user_prompt(record: FeedbackRecord) -> str:
    """构造单条反馈的用户消息：只含原文与必要元数据。"""
    lines = [f"【原文】{record.original_text}"]
    if record.translated_text:
        lines.append(f"【中文译文】{record.translated_text}")
    lines.append(f"【品牌】{record.brand}")
    if record.product_model:
        lines.append(f"【产品型号】{record.product_model}")
    lines.append(f"【语言】{record.language}")
    lines.append(f"【来源平台】{record.source_platform}")
    return "\n".join(lines)


def _failed_classification(feedback_id: str, model_name: str,
                           prompt_version: str, error: str) -> ClassificationResult:
    """构造分类失败占位结果：保守哨兵值 + 置信度 0，不猜测任何字段。

    与 review._failed_review 同一模式：低置信/冲突机制会把该记录送入人工复核，
    而不是让整条流水线崩溃。
    """
    return ClassificationResult(
        feedback_id=feedback_id,
        sentiment=Sentiment.NEUTRAL,
        theme_primary=ThemePrimary.OTHER,
        theme_secondary=[],
        need_type=NeedType.UNKNOWN,
        scenario=Scenario.UNKNOWN,
        user_type=UserType.UNKNOWN,
        severity=Severity.S5,
        purchase_impact=PurchaseImpact.UNKNOWN,
        jtbd="分类调用失败，未生成独立判断",
        root_cause_hypotheses=[],
        is_actionable=False,
        is_constructive=False,
        confidence=0.0,
        rationale=f"模型输出未通过字段校验或调用失败，已标记待人工复核：{error[:120]}",
        model_name=model_name,
        prompt_version=prompt_version,
    )


def _validate_with_repair(raw: dict, record: FeedbackRecord, client,
                          system: str, prompt_version: str) -> ClassificationResult:
    """校验模型输出；失败时做一次修复调用（带合法枚举清单），仍失败抛 ValidationError。"""
    raw = dict(raw)
    # 系统字段由代码注入，不信任模型回显
    raw["feedback_id"] = record.feedback_id
    raw["model_name"] = client.model
    raw["prompt_version"] = prompt_version
    try:
        return ClassificationResult.model_validate(raw)
    except ValidationError as exc:
        logger.warning("分类输出校验失败 (%s)，执行一次修复调用：%s", record.feedback_id, exc)
        repair_user = (
            f"校验错误：\n{exc}\n\n"
            f"{_ENUM_HINT}\n\n"
            f"原输出：\n{json.dumps(raw, ensure_ascii=False)}\n\n"
            f"请只输出修正后的合法 JSON 对象，不要包含任何解释或 Markdown 代码块标记。"
        )
        raw2 = dict(client.complete_json(REPAIR_SYSTEM_PROMPT, repair_user))
        raw2["feedback_id"] = record.feedback_id
        raw2["model_name"] = client.model
        raw2["prompt_version"] = prompt_version
        return ClassificationResult.model_validate(raw2)


def classify_batch(records: list, client, prompt_path: str = "prompts/classify_v1.md") -> list[ClassificationResult]:
    """对一批反馈执行分类，返回与输入同序、一一对应的结果列表。

    - 单条单独调用，天然保持 feedback_id 对应
    - 模型输出经 ClassificationResult 校验；校验失败做一次带枚举清单的修复调用
    - 仍失败则返回保守占位结果（置信度 0、哨兵字段），由下游送入人工复核，
      绝不崩溃整条流水线（与 review_batch 的 _failed_review 模式一致）
    - evidence_status 非 verified 时置信度封顶 0.6
    """
    system = _load_system_prompt(prompt_path)
    prompt_version = _prompt_version(prompt_path)

    results: list[ClassificationResult] = []
    for record in records:
        try:
            raw = client.complete_json(system, _build_user_prompt(record))
            result = _validate_with_repair(raw, record, client, system, prompt_version)
        except (LLMClientError, ValidationError) as exc:
            logger.warning("分类失败 (%s)：%s", record.feedback_id, exc)
            result = _failed_classification(
                record.feedback_id, client.model, prompt_version, str(exc)
            )
        if record.evidence_status != EvidenceStatus.VERIFIED:
            result.confidence = min(result.confidence, UNVERIFIED_CONFIDENCE_CAP)
        results.append(result)
    return results
