"""pipeline 模块测试。

要求：
1. 状态流: CREATED -> ... -> COMPLETED；失败保留前序结果（FAILED）
2. 输出到 output/<run_id>/，生成 run_summary.json / run_report.md
3. 离线基线使用数据标注列（offline_mode），不调用 LLM
4. resume 从失败步骤恢复，不重复已完成阶段
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from ridepulse.config import Config
from ridepulse.database import Database
from ridepulse.ingest import load_csv
from ridepulse.models import (
    EvidenceStatus,
    FeedbackRecord,
    NeedType,
    PermalinkLevel,
    PurchaseImpact,
    Sentiment,
    Severity,
    SourceType,
    TextProvenance,
    ThemePrimary,
    TranslationMethod,
)
from ridepulse.pipeline import Pipeline


def make_record(feedback_id: str, text: str) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=feedback_id,
        source_record_id=f"SR-{feedback_id}",
        ingest_batch_id="BATCH-20260808-210000",
        source_platform="App Store",
        source_type=SourceType.APP_STORE,
        source_url="https://apps.apple.com/cz/app/onelapfit/id1555629744",
        source_permalink_level=PermalinkLevel.PAGE_ONLY,
        source_date=date(2026, 7, 1),
        source_date_raw=None,
        source_date_precision="day",
        accessed_at=date(2026, 8, 8),
        language="zh",
        market="unknown",
        brand="Magene",
        product_model="C606",
        firmware_version=None,
        app_version=None,
        original_text=text,
        translated_text=None,
        text_provenance=TextProvenance.VERBATIM,
        translation_method=TranslationMethod.NOT_NEEDED,
        archive_path=None,
        archive_sha256=None,
        evidence_status=EvidenceStatus.VERIFIED,
        verification_note=None,
    )


# 标注列（离线基线读取用）
ANNOTATION_BY_ID = {
    "F0001": {"sentiment": 2, "theme_primary": "connectivity", "theme_secondary": "data_accuracy",
              "need_type": "real_need", "scenario": "training", "user_type": "enthusiast",
              "severity": "S2", "purchase_impact": "influence",
              "jtbd": "用户希望同步数据在App中正确显示", "is_actionable": "true",
              "is_constructive": "false"},
    "F0002": {"sentiment": 2, "theme_primary": "connectivity", "theme_secondary": "",
              "need_type": "real_need", "scenario": "training", "user_type": "unknown",
              "severity": "S3", "purchase_impact": "influence",
              "jtbd": "用户希望同步字段完整", "is_actionable": "true", "is_constructive": "false"},
    "F0003": {"sentiment": 3, "theme_primary": "firmware", "theme_secondary": "",
              "need_type": "feature_request", "scenario": "leisure", "user_type": "unknown",
              "severity": "S4", "purchase_impact": "no_impact",
              "jtbd": "用户希望增加固件设置项", "is_actionable": "true", "is_constructive": "true"},
}


def write_dataset_csv(tmp_path: Path, records: list[FeedbackRecord]) -> Path:
    path = tmp_path / "dataset.csv"
    rows = [record.model_dump() for record in records]
    for row in rows:
        row.update(ANNOTATION_BY_ID[row["feedback_id"]])
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def env(tmp_path: Path):
    """隔离的配置：临时 DB 与输出目录。"""
    return Config(
        env="test",
        db_path=tmp_path / "pipeline.db",
        output_dir=tmp_path / "out",
        llm_base_url="", llm_api_key="", llm_primary_model="",
    )


def build_records():
    return [
        make_record("F0001", "活动同步后App不显示数据，重试三次一样"),
        make_record("F0002", "心率数据同步到Strava后字段为空"),
        make_record("F0003", "固件更新后屏幕亮度设置丢失"),
    ]


class TestOfflineRun:
    def test_full_pipeline_completes(self, tmp_path: Path, env: Config):
        records = build_records()
        dataset = write_dataset_csv(tmp_path, records)
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-20260808-210000", db=db, config=env,
                            offline_mode=True)
        summary = pipeline.run(str(dataset))
        assert summary.state.value == "COMPLETED"
        assert summary.total_input == 3
        assert summary.valid_count == 3
        assert summary.classified_count == 3
        assert summary.cluster_count >= 1
        assert summary.card_count >= 1

        run_dir = env.output_dir / "RUN-20260808-210000"
        assert (run_dir / "run_summary.json").exists()
        assert (run_dir / "run_report.md").exists()
        assert (run_dir / "model_outputs.csv").exists()
        assert (run_dir / "review_outputs.csv").exists()
        assert (run_dir / "human_final_outputs.csv").exists()
        assert (run_dir / "cluster_results.csv").exists()
        assert (run_dir / "priority_scores.csv").exists()
        assert (run_dir / "evidence_cards.json").exists()
        assert (run_dir / "evidence_cards.md").exists()

        # run_summary.json 内容与摘要一致
        stored = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
        assert stored["state"] == "COMPLETED"

        # 证据卡 JSON 含代码附加的 URL
        cards = json.loads((run_dir / "evidence_cards.json").read_text(encoding="utf-8"))
        assert cards
        for card in cards:
            assert card["evidence"]
            for evidence in card["evidence"]:
                assert evidence["source_url"].startswith("https://")

        # DB 状态
        assert db.get_run("RUN-20260808-210000")["state"] == "COMPLETED"

    def test_offline_uses_annotation_columns(self, tmp_path: Path, env: Config):
        records = build_records()
        dataset = write_dataset_csv(tmp_path, records)
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-20260808-210000", db=db, config=env,
                            offline_mode=True)
        pipeline.run(str(dataset))
        rows = db.conn.execute(
            "SELECT feedback_id, model_name, prompt_version FROM classifications"
        ).fetchall()
        assert len(rows) == 3
        assert all(r["model_name"] == "annotation-gold-v1" for r in rows)

    def test_invalid_annotation_fails_loudly(self, tmp_path: Path, env: Config):
        """标注列非法（如 severity=XX）必须抛错，不静默猜测。"""
        records = [make_record("F0001", "文本")]
        dataset = write_dataset_csv(tmp_path, records)
        # 手动破坏标注列
        import io
        content = dataset.read_text(encoding="utf-8-sig").replace(",S2,", ",XX,")
        dataset.write_text(content, encoding="utf-8-sig")
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-20260808-210000", db=db, config=env,
                            offline_mode=True)
        with pytest.raises(ValueError, match="离线基线分类失败"):
            pipeline.run(str(dataset))
        # 失败保留前序结果（feedback 已入库）
        assert db.count_feedback("RUN-20260808-210000") == 1

    def test_no_llm_without_offline_raises(self, tmp_path: Path, env: Config):
        """未配置 LLM 且非离线模式：清晰报错而不是悄悄用假数据。"""
        records = build_records()
        dataset = write_dataset_csv(tmp_path, records)
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-20260808-210000", db=db, config=env)
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            pipeline.run(str(dataset))


class TestResume:
    def test_resume_completes_from_partial(self, tmp_path: Path, env: Config):
        records = build_records()
        dataset = write_dataset_csv(tmp_path, records)
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-20260808-210000", db=db, config=env,
                            offline_mode=True)
        # 先完整跑一遍，再 resume（应幂等完成）
        pipeline.run(str(dataset))
        resumed = Pipeline(run_id="RUN-20260808-210000", db=db, config=env,
                           offline_mode=True)
        summary = resumed.resume()
        assert summary.state.value == "COMPLETED"
        assert summary.classified_count == 3

    def test_resume_unknown_run_rejected(self, env: Config):
        db = Database(env.db_path)
        pipeline = Pipeline(run_id="RUN-99999999-000000", db=db, config=env)
        with pytest.raises(ValueError, match="run 不存在"):
            pipeline.resume()
