"""第一轮 AI 分类模块。

实现要求（文档15 §7.8）：
1. 每条记录单独分类，保持 ID 对应
2. 模型输出经 Pydantic 校验
3. 置信度 < 0.65 自动进入人工复核（下游据此判定）
4. evidence_status 非 verified 时置信度降级
5. 保存 Prompt 版本、模型名和时间
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ridepulse.llm_client import LLMClientError
from ridepulse.models import ClassificationResult, EvidenceStatus, FeedbackRecord

# evidence_status 非 verified 时的置信度上限：
# 未核验证据不得以高置信度跳过人工复核（0.6 < 0.65 必然进入复核）
UNVERIFIED_CONFIDENCE_CAP = 0.6

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


def classify_batch(records: list, client, prompt_path: str = "prompts/classify_v1.md") -> list[ClassificationResult]:
    """对一批反馈执行分类，返回与输入同序、一一对应的结果列表。

    - 单条单独调用，天然保持 feedback_id 对应
    - 模型输出经 ClassificationResult 校验；不通过抛 LLMClientError（进入人工队列）
    - evidence_status 非 verified 时置信度封顶 0.6
    """
    system = _load_system_prompt(prompt_path)
    prompt_version = _prompt_version(prompt_path)

    results: list[ClassificationResult] = []
    for record in records:
        raw = client.complete_json(system, _build_user_prompt(record))
        # 系统字段由代码注入，不信任模型回显
        raw["feedback_id"] = record.feedback_id
        raw["model_name"] = client.model
        raw["prompt_version"] = prompt_version
        try:
            result = ClassificationResult.model_validate(raw)
        except ValidationError as exc:
            raise LLMClientError(
                f"模型输出未通过字段校验 ({record.feedback_id}): {exc}"
            ) from exc
        if record.evidence_status != EvidenceStatus.VERIFIED:
            result.confidence = min(result.confidence, UNVERIFIED_CONFIDENCE_CAP)
        results.append(result)
    return results
