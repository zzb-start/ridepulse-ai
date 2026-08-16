"""classify 模块测试。

要求：
1. 每条记录单独分类，保持 ID 对应
2. 模型输出经过 Pydantic 校验
3. 置信度 < 0.65 自动进入人工复核（下游依据置信度判断）
4. evidence_status 非 verified 时置信度降级
5. 保存 Prompt 版本、模型名和时间
验收：10 条固定 fixture 返回 10 条结构化结果，无丢 ID、重复 ID 或字段越界
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ridepulse.classify import classify_batch
from ridepulse.llm_client import FakeLLMClient, LLMClientError
from ridepulse.models import ClassificationResult, EvidenceStatus, Severity

VALID_LLM_OUTPUT = {
    "sentiment": 2,
    "theme_primary": "connectivity",
    "theme_secondary": ["firmware"],
    "need_type": "real_need",
    "scenario": "training",
    "user_type": "unknown",
    "severity": "S2",
    "purchase_impact": "unknown",
    "jtbd": "用户希望骑行活动在App中可靠显示以完成训练数据管理",
    "root_cause_hypotheses": ["上传校验仅检查活动级别"],
    "is_actionable": True,
    "is_constructive": True,
    "confidence": 0.9,
    "rationale": "用户明确描述了可复现的上传问题",
}


def make_client(responder) -> FakeLLMClient:
    return FakeLLMClient(responder=responder)


class TestClassifyBatch:
    def test_batch_returns_one_result_per_record_same_order(self, valid_feedback_record):
        records = [valid_feedback_record.model_copy(update={"feedback_id": f"F{i:04d}"}) for i in range(1, 11)]

        def responder(system: str, user: str) -> dict:
            output = dict(VALID_LLM_OUTPUT)
            output["confidence"] = 0.9
            return output

        client = make_client(responder)
        results = classify_batch(records, client, prompt_path="prompts/classify_v1.md")

        # 验收：10 条 -> 10 条结构化结果，无丢 ID、重复 ID
        assert len(results) == 10
        ids = [r.feedback_id for r in results]
        assert ids == [f"F{i:04d}" for i in range(1, 11)]
        assert len(ids) == len(set(ids))

    def test_results_are_validated_models(self, valid_feedback_record):
        client = make_client(lambda s, u: dict(VALID_LLM_OUTPUT))
        results = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")
        assert isinstance(results[0], ClassificationResult)
        assert results[0].feedback_id == "F0001"
        assert results[0].severity == "S2"

    def test_prompt_contains_original_text_per_record(self, valid_feedback_record):
        texts_seen: list[str] = []

        def responder(system: str, user: str) -> dict:
            texts_seen.append(user)
            return dict(VALID_LLM_OUTPUT)

        client = make_client(responder)
        records = [
            valid_feedback_record.model_copy(update={"feedback_id": "F0001"}),
            valid_feedback_record.model_copy(update={"feedback_id": "F0002", "original_text": "GPS定位漂移导致里程不准"}),
        ]
        classify_batch(records, client, prompt_path="prompts/classify_v1.md")
        assert "GPS定位漂移导致里程不准" in texts_seen[1]
        assert "设备显示上传成功" in texts_seen[0]

    def test_model_name_prompt_version_created_at_recorded(self, valid_feedback_record):
        client = make_client(lambda s, u: dict(VALID_LLM_OUTPUT))
        results = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")
        result = results[0]
        assert result.model_name == "fake-model"
        assert result.prompt_version == "classify_v1"
        assert isinstance(result.created_at, datetime)

    def test_custom_prompt_path_is_used_as_system_prompt(self, tmp_path, valid_feedback_record):
        prompt_file = tmp_path / "my_prompt.md"
        prompt_file.write_text("自定义分类规则：只分主题", encoding="utf-8")
        seen: list[str] = []
        client = make_client(lambda s, u: (seen.append(s) or dict(VALID_LLM_OUTPUT)))
        results = classify_batch([valid_feedback_record], client, prompt_path=str(prompt_file))
        assert "自定义分类规则" in seen[0]
        # 版本名取自文件名（不含扩展名）
        assert results[0].prompt_version == "my_prompt"

    def test_missing_prompt_file_falls_back_to_default(self, valid_feedback_record):
        seen: list[str] = []
        client = make_client(lambda s, u: (seen.append(s) or dict(VALID_LLM_OUTPUT)))
        results = classify_batch(
            [valid_feedback_record], client, prompt_path="prompts/不存在_xyz.md"
        )
        assert results[0].feedback_id == "F0001"
        assert seen[0]  # 有兜底系统提示词


class TestConfidence:
    def test_unverified_evidence_confidence_capped_at_06(self, valid_feedback_record):
        record = valid_feedback_record.model_copy(
            update={"evidence_status": EvidenceStatus.UNVERIFIED}
        )
        client = make_client(lambda s, u: dict(VALID_LLM_OUTPUT))
        result = classify_batch([record], client, prompt_path="prompts/classify_v1.md")[0]
        assert result.confidence == 0.6  # 0.9 被降级

    def test_verified_evidence_confidence_unchanged(self, valid_feedback_record):
        client = make_client(lambda s, u: dict(VALID_LLM_OUTPUT))
        result = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")[0]
        assert result.confidence == 0.9

    def test_low_confidence_passes_through(self, valid_feedback_record):
        client = make_client(lambda s, u: {**VALID_LLM_OUTPUT, "confidence": 0.5})
        result = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")[0]
        assert result.confidence == 0.5  # <0.65 由下游判定进入人工复核


class TestValidationGate:
    """校验失败不再崩溃整条流水线：一次修复调用 -> 仍失败返回保守占位（进人工复核）。"""

    def test_validation_failure_repairs_once_then_succeeds(self, valid_feedback_record):
        calls: list[str] = []

        def responder(system: str, user: str) -> dict:
            calls.append(system)
            return dict(VALID_LLM_OUTPUT) if len(calls) == 2 else {**VALID_LLM_OUTPUT, "severity": "unknown"}

        client = make_client(responder)
        results = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")
        assert len(calls) == 2  # 原始调用 + 一次修复调用
        assert results[0].severity == Severity.S2

    def test_repair_failure_returns_placeholder_not_raise(self, valid_feedback_record):
        client = make_client(lambda s, u: {**VALID_LLM_OUTPUT, "severity": "unknown"})
        results = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")
        result = results[0]
        assert result.confidence == 0.0
        assert result.severity == Severity.S5  # 保守哨兵，不猜测
        assert "待人工复核" in result.rationale

    def test_llm_error_returns_placeholder_not_raise(self, valid_feedback_record):
        def responder(system: str, user: str) -> dict:
            raise LLMClientError("LLM 调用失败")

        client = make_client(responder)
        results = classify_batch([valid_feedback_record], client, prompt_path="prompts/classify_v1.md")
        assert results[0].feedback_id == "F0001"
        assert results[0].confidence == 0.0
