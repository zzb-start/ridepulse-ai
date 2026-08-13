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

import csv
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ridepulse.classify import classify_batch
from ridepulse.clustering import cluster_feedback
from ridepulse.config import Config, get_config
from ridepulse.database import Database
from ridepulse.dedup import exact_fingerprint, near_duplicate_groups
from ridepulse.embedding import embed_records
from ridepulse.evidence import generate_cards, validate_citation
from ridepulse.ingest import load_csv
from ridepulse.models import (
    ClassificationResult,
    EvidenceStatus,
    HumanReview,
    HumanReviewStatus,
    NeedType,
    PipelineState,
    PurchaseImpact,
    ReviewConflictStatus,
    RunSummary,
    Sentiment,
    Severity,
    ThemePrimary,
)
from ridepulse.normalize import normalize_text
from ridepulse.review import apply_human_decision, review_batch
from ridepulse.scoring import score_cluster

logger = logging.getLogger(__name__)

# 离线基线标识：使用数据自身标注列作为分类结果（非 LLM 输出）
OFFLINE_MODEL_NAME = "annotation-gold-v1"
OFFLINE_PROMPT_VERSION = "offline-baseline"


def _new_run_id(now: datetime | None = None) -> str:
    """生成 RUN-YYYYMMDD-HHMMSS。"""
    now = now or datetime.now()
    return f"RUN-{now:%Y%m%d-%H%M%S}"


def _as_bool(value: Any) -> bool:
    """CSV 布尔值容错：true/True/1/0/False。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


class Pipeline:
    """一次完整运行的编排器。

    offline_mode=True 时使用 CSV 中已有的标注列（sentiment/theme_primary 等）
    作为分类与复判结果——这是开发/演示基线，run_report 会明确标注
    classification_source=human_annotations，不得用于比赛模型指标。
    """

    def __init__(self, *, run_id: str | None = None, db: Database | None = None,
                 config: Config | None = None, classify_client=None,
                 review_client=None, evidence_client=None,
                 embedding_api=None, offline_mode: bool = False) -> None:
        self.config = config or get_config()
        self.run_id = run_id or _new_run_id()
        self.db = db or Database(self.config.db_path)
        self.offline_mode = offline_mode
        self.classify_client = classify_client
        self.review_client = review_client
        self.evidence_client = evidence_client
        self.embedding_api = embedding_api
        self.state = PipelineState.CREATED
        self.run_dir = self.config.output_dir / self.run_id
        self._raw_rows: dict[str, dict] = {}  # feedback_id -> CSV 原始行（离线标注来源）
        self.embedding_mode_used: str = ""  # 实际使用的 embedding 模式（可能因未配置密钥回退）

    # ------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------

    def run(self, input_path: str, *, human_decisions: dict | None = None) -> RunSummary:
        """执行完整流水线：导入→校验→去重→分类→复判→聚类→评分→证据卡。

        任一步失败：更新 DB 状态为 FAILED 并保留前序结果，可 resume。
        """
        summary = RunSummary(run_id=self.run_id)
        try:
            self.db.create_run(self.run_id)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.db.audit(self.run_id, actor="pipeline", action="run_started",
                          object_type="run", object_id=self.run_id)

            records = self._step_import(input_path, summary)
            self._set_state(PipelineState.COLLECTED_OR_IMPORTED)
            self._set_state(PipelineState.VALIDATED)
            logger.info("[%s] 导入完成: %d 条有效", self.run_id, len(records))

            self._step_dedup(records, summary)
            self._set_state(PipelineState.DEDUPED)

            classifications = self._step_classify(records, summary)
            self._set_state(PipelineState.CLASSIFIED)

            reviews = self._step_review(records, classifications, summary)
            if summary.human_review_count:
                self._set_state(PipelineState.WAITING_HUMAN_REVIEW)
            self._set_state(PipelineState.REVIEWED)

            human_final = self._step_human(records, classifications, reviews,
                                           human_decisions or {})

            vectors = self._step_embedding(records, classifications)
            clusters = self._step_cluster(records, vectors, classifications, summary)
            self._set_state(PipelineState.CLUSTERED)

            scores = self._step_score(clusters, records, classifications, reviews, summary)
            self._set_state(PipelineState.SCORED)

            cards = self._step_cards(clusters, records, classifications, scores, summary)
            self._set_state(PipelineState.CARDS_GENERATED)
            self._set_state(PipelineState.WAITING_CARD_APPROVAL)

            self._write_outputs(records, classifications, reviews, human_final,
                                clusters, scores, cards, summary)
            summary.state = PipelineState.COMPLETED
            summary.completed_at = datetime.now()
            self.db.update_run_state(self.run_id, "COMPLETED")
            self.db.complete_run(self.run_id)
            self._write_summary(summary)
            self.db.audit(self.run_id, actor="pipeline", action="run_completed",
                          object_type="run", object_id=self.run_id, after=summary.model_dump())
            logger.info("[%s] 流水线完成", self.run_id)
            return summary

        except Exception as exc:  # noqa: BLE001 — 失败保留前序结果
            logger.exception("[%s] 流水线失败: %s", self.run_id, exc)
            summary.state = PipelineState.FAILED
            summary.error_message = str(exc)[:500]
            self.db.update_run_state(self.run_id, "FAILED", error_message=str(exc)[:500])
            self._write_summary(summary)
            raise

    def resume(self) -> RunSummary:
        """从失败步骤恢复：跳过已完成阶段，只补未完成阶段。

        依赖 DB 中的反馈、分类、复核、簇与证据卡，不重新导入 CSV。
        """
        if self.db.get_run(self.run_id) is None:
            raise ValueError(f"run 不存在: {self.run_id}")
        summary = RunSummary(run_id=self.run_id)
        try:
            rows = self.db.list_feedback(self.run_id)
            records = [self._row_to_record(row) for row in rows]
            summary.valid_count = len(records)
            summary.total_input = len(records)
            # resume 不重跑去重阶段，去重数从 DB 的 duplicate_group_id 统计：
            # 每组代表 1 条 + 未分组记录
            grouped = {row["duplicate_group_id"] for row in rows
                       if row["duplicate_group_id"]}
            summary.deduped_count = len(grouped) + sum(
                1 for row in rows if not row["duplicate_group_id"]
            )

            classifications = self._load_classifications()
            reviews = self._load_reviews()
            clusters = self._load_clusters()
            cards = self._load_cards()
            summary.classified_count = len(classifications)
            summary.conflict_count = sum(
                1 for r in reviews if r.review_status == ReviewConflictStatus.CONFLICT
            )
            summary.human_review_count = sum(
                1 for r in reviews if r.human_review_required
            )
            summary.cluster_count = len(clusters)
            summary.card_count = len(cards)

            if not classifications:
                classifications = self._step_classify(records, summary)
            if not reviews:
                reviews = self._step_review(records, classifications, summary)
            if not clusters:
                vectors = self._step_embedding(records, classifications)
                clusters = self._step_cluster(records, vectors, classifications, summary)
            scores = self._step_score(clusters, records, classifications, reviews, summary)
            if not cards:
                cards = self._step_cards(clusters, records, classifications, scores, summary)

            human_final = self._load_human_final(records, classifications, reviews)
            self._write_outputs(records, classifications, reviews, human_final,
                                clusters, scores, cards, summary)
            summary.state = PipelineState.COMPLETED
            self.db.complete_run(self.run_id)
            self._write_summary(summary)
            return summary
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] resume 失败: %s", self.run_id, exc)
            summary.state = PipelineState.FAILED
            summary.error_message = str(exc)[:500]
            self._write_summary(summary)
            raise

    # ------------------------------------------------------------
    # 各阶段
    # ------------------------------------------------------------

    def _step_import(self, input_path: str, summary: RunSummary) -> list:
        """导入并校验 CSV；保存原始行供离线基线读取标注列。"""
        report = load_csv(input_path, out_dir=str(self.run_dir))
        summary.total_input = report.total_rows
        summary.valid_count = report.valid_rows
        self._raw_rows = {row["feedback_id"]: row for row in report.valid_raw_rows}
        for record in report.valid_records:
            self.db.insert_feedback(self.run_id, record.model_dump())
        if report.invalid_rows:
            logger.warning("[%s] 导入拒绝 %d 行: %s", self.run_id,
                           report.invalid_rows, report.warnings[:5])
        return report.valid_records

    def _step_dedup(self, records: list, summary: RunSummary) -> None:
        """两层去重：SHA-256 精确指纹 + 3-gram 近似。只标记不删除。"""
        groups: dict[str, str] = {}

        def fingerprint(record) -> str:
            return exact_fingerprint(
                normalize_text(record.original_text), record.brand, record.product_model
            )

        exact_groups: dict[str, list[str]] = {}
        for record in records:
            exact_groups.setdefault(fingerprint(record), []).append(record.feedback_id)
        for order, (_, member_ids) in enumerate(
            sorted(exact_groups.items(), key=lambda kv: min(kv[1])), start=1
        ):
            if len(member_ids) >= 2:
                group_id = f"DG-{order:04d}"
                for fid in member_ids:
                    groups[fid] = group_id

        # 近似层（仅对未命中精确组的记录）
        ungrouped = [r for r in records if r.feedback_id not in groups]
        near = near_duplicate_groups(
            [{"feedback_id": r.feedback_id, "original_text": r.original_text}
             for r in ungrouped]
        )
        for fid, group_id in near.items():
            if fid not in groups:
                groups[fid] = group_id

        for record in records:
            normalized = normalize_text(record.original_text)
            content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            self.db.update_feedback_derived(
                record.feedback_id,
                normalized_text=normalized,
                content_sha256=content_sha256,
                duplicate_group_id=groups.get(record.feedback_id),
            )

        # 去重后数 = 每个重复组代表数 + 非重复记录数
        group_members: dict[str, list[str]] = {}
        for fid, group in groups.items():
            group_members.setdefault(group, []).append(fid)
        representatives = {r.feedback_id for r in records if r.feedback_id not in groups}
        representatives.update(min(members) for members in group_members.values())
        summary.deduped_count = len(representatives)

    def _step_classify(self, records: list, summary: RunSummary) -> list[ClassificationResult]:
        """第一轮 AI 分类（离线模式使用数据标注列）。"""
        if self.offline_mode:
            results = self._classify_offline(records)
        else:
            if self.classify_client is None:
                if not self.config.llm_configured:
                    raise ValueError(
                        "未配置 LLM_API_KEY/LLM_BASE_URL/LLM_PRIMARY_MODEL，"
                        "且未指定 classify_client；离线模式请传 offline_mode=True"
                    )
                from ridepulse.llm_client import BaseLLMClient
                self.classify_client = BaseLLMClient(
                    base_url=self.config.llm_base_url,
                    api_key=self.config.llm_api_key,
                    model=self.config.llm_primary_model,
                    timeout_seconds=self.config.llm_timeout_seconds,
                    max_retries=self.config.llm_max_retries,
                )
            results = classify_batch(records, self.classify_client)
        for result in results:
            self.db.insert_classification(self.run_id, result.model_dump())
        summary.classified_count = len(results)
        return results

    def _classify_offline(self, records: list) -> list[ClassificationResult]:
        """离线基线：使用 CSV 原始行中的标注列构造 ClassificationResult。

        只接受合法枚举值；缺失列/非法值抛清晰错误（不得静默猜测）。
        """
        results: list[ClassificationResult] = []
        for record in records:
            row = self._raw_rows.get(record.feedback_id, {})
            try:
                theme_secondary_raw = row.get("theme_secondary") or []
                if isinstance(theme_secondary_raw, str):
                    theme_secondary_raw = theme_secondary_raw.split(";")
                results.append(ClassificationResult(
                    feedback_id=record.feedback_id,
                    sentiment=Sentiment(int(row["sentiment"])),
                    theme_primary=ThemePrimary(row["theme_primary"]),
                    theme_secondary=[ThemePrimary(t) for t in theme_secondary_raw if t],
                    need_type=NeedType(row["need_type"]),
                    scenario=row.get("scenario") or "unknown",
                    user_type=row.get("user_type") or "unknown",
                    severity=Severity(row["severity"]),
                    purchase_impact=PurchaseImpact(row["purchase_impact"]),
                    jtbd=row.get("jtbd") or "用户希望解决该反馈中的问题",
                    root_cause_hypotheses=[],
                    is_actionable=_as_bool(row.get("is_actionable")),
                    is_constructive=_as_bool(row.get("is_constructive")),
                    confidence=0.95 if record.evidence_status == EvidenceStatus.VERIFIED else 0.7,
                    rationale="来自数据标注列（离线基线，非 LLM 输出）",
                    model_name=OFFLINE_MODEL_NAME,
                    prompt_version=OFFLINE_PROMPT_VERSION,
                ))
            except (ValidationError, KeyError, ValueError) as exc:
                raise ValueError(
                    f"离线基线分类失败 ({record.feedback_id}): 数据标注列不完整或非法 — {exc}"
                ) from exc
        return results

    def _step_review(self, records: list, classifications: list[ClassificationResult],
                     summary: RunSummary) -> list:
        """独立第二轮复判。"""
        if self.offline_mode:
            results = self._review_offline(classifications)
        else:
            if self.review_client is None:
                if not self.config.llm_configured:
                    raise ValueError("未配置 LLM 且未指定 review_client")
                from ridepulse.llm_client import BaseLLMClient
                self.review_client = BaseLLMClient(
                    base_url=self.config.llm_base_url,
                    api_key=self.config.llm_api_key,
                    model=self.config.llm_review_model or self.config.llm_primary_model,
                    timeout_seconds=self.config.llm_timeout_seconds,
                    max_retries=self.config.llm_max_retries,
                )
            results = review_batch(records, classifications, self.review_client)
        for result in results:
            self.db.insert_review(self.run_id, result.model_dump())
        summary.conflict_count = sum(
            1 for r in results if r.review_status == ReviewConflictStatus.CONFLICT
        )
        summary.human_review_count = sum(1 for r in results if r.human_review_required)
        return results

    def _review_offline(self, classifications: list[ClassificationResult]) -> list:
        """离线基线复判：与第一轮完全一致（同源标注），无冲突。"""
        from ridepulse.models import ReviewResult
        return [
            ReviewResult(
                feedback_id=primary.feedback_id,
                review_sentiment=primary.sentiment,
                review_theme_primary=primary.theme_primary,
                review_need_type=primary.need_type,
                review_severity=primary.severity,
                review_purchase_impact=primary.purchase_impact,
                review_jtbd=primary.jtbd,
                review_confidence=primary.confidence,
                conflict_fields=[],
                review_status=ReviewConflictStatus.AGREED,
                human_review_required=False,
                model_name=OFFLINE_MODEL_NAME,
                prompt_version=OFFLINE_PROMPT_VERSION,
            )
            for primary in classifications
        ]

    def _step_human(self, records: list, classifications: list[ClassificationResult],
                    reviews: list, human_decisions: dict) -> dict:
        """人工复核：有裁决的写入 human_reviews；其余按规则生成最终字段。

        返回 {feedback_id: {sentiment, theme_primary, need_type, severity,
        purchase_impact, review_status}}，覆盖所有记录（最终输出用）。
        """
        review_by_id = {r.feedback_id: r for r in reviews}
        primary_by_id = {c.feedback_id: c for c in classifications}
        finals: dict[str, dict] = {}

        for review in reviews:
            decision = human_decisions.get(review.feedback_id)
            if review.human_review_required and decision:
                primary = primary_by_id[review.feedback_id]
                human = apply_human_decision(
                    primary=primary, review=review,
                    final_sentiment=Sentiment(decision["sentiment"]),
                    final_theme_primary=ThemePrimary(decision["theme_primary"]),
                    final_need_type=NeedType(decision["need_type"]),
                    final_severity=Severity(decision["severity"]),
                    final_purchase_impact=PurchaseImpact(decision["purchase_impact"]),
                    reviewer=decision.get("reviewer", "human"),
                    note=decision.get("note", ""),
                )
                self._insert_human_review(human)
                finals[review.feedback_id] = {
                    "sentiment": human.final_sentiment,
                    "theme_primary": human.final_theme_primary,
                    "need_type": human.final_need_type,
                    "severity": human.final_severity,
                    "purchase_impact": human.final_purchase_impact,
                    "review_status": human.review_status,
                }
            elif review.human_review_required:
                # 未裁决：保持 pending，最终字段暂用第一轮结果
                self.db.insert_human_review_pending(
                    self.run_id, review.feedback_id,
                    primary_json=primary_by_id[review.feedback_id].model_dump(),
                    review_json=review.model_dump(),
                    conflict_fields=review.conflict_fields,
                )
                primary = primary_by_id[review.feedback_id]
                finals[review.feedback_id] = {
                    "sentiment": primary.sentiment,
                    "theme_primary": primary.theme_primary,
                    "need_type": primary.need_type,
                    "severity": primary.severity,
                    "purchase_impact": primary.purchase_impact,
                    "review_status": HumanReviewStatus.PENDING,
                }

        for primary in classifications:
            if primary.feedback_id not in finals:
                finals[primary.feedback_id] = {
                    "sentiment": primary.sentiment,
                    "theme_primary": primary.theme_primary,
                    "need_type": primary.need_type,
                    "severity": primary.severity,
                    "purchase_impact": primary.purchase_impact,
                    "review_status": HumanReviewStatus.APPROVED,
                }
        return finals

    def _insert_human_review(self, human: HumanReview) -> None:
        """写入人工复核结果（含 primary/review JSON）。"""
        self.db.insert_human_review_pending(
            self.run_id, human.feedback_id,
            primary_json=human.primary_result.model_dump() if human.primary_result else None,
            review_json=human.review_result.model_dump() if human.review_result else None,
            conflict_fields=human.conflict_fields,
        )
        self.db.update_human_review(
            self.run_id, human.feedback_id,
            status=human.review_status.value,
            note=human.review_note,
            reviewer=human.reviewer,
            final={
                "sentiment": human.final_sentiment.value if human.final_sentiment else None,
                "theme_primary": human.final_theme_primary.value if human.final_theme_primary else None,
                "need_type": human.final_need_type.value if human.final_need_type else None,
                "severity": human.final_severity.value if human.final_severity else None,
                "purchase_impact": human.final_purchase_impact.value if human.final_purchase_impact else None,
            },
        )

    def _step_embedding(self, records: list, classifications: list[ClassificationResult]) -> dict:
        """Embedding：正式模式 api，未配置时回退 fake（在 run_report 如实标注）。"""
        by_id = {c.feedback_id: c for c in classifications}
        mode = self.config.embedding_mode
        if mode == "api" and not (self.config.llm_base_url and self.config.llm_api_key):
            mode = "fake"
            logger.warning("Embedding api 模式未配置密钥，回退 fake（不可用于比赛指标）")
        self.embedding_mode_used = mode
        return embed_records(
            records, by_id, mode=mode, model=self.config.embedding_model,
            dimension=self.config.embedding_dimension or 64,
            api_client=self.embedding_api,
        )

    def _step_cluster(self, records: list, vectors: dict,
                      classifications: list[ClassificationResult],
                      summary: RunSummary) -> list:
        """聚类。"""
        by_id = {c.feedback_id: c for c in classifications}
        clusters = cluster_feedback(records, vectors, by_id)
        for cluster in clusters:
            self.db.insert_cluster(self.run_id, cluster.model_dump())
        summary.cluster_count = len(clusters)
        return clusters

    def _step_score(self, clusters: list, records: list,
                    classifications: list[ClassificationResult], reviews: list,
                    summary: RunSummary) -> dict:
        """确定性评分。"""
        records_by_id = {r.feedback_id: r for r in records}
        class_by_id = {c.feedback_id: c for c in classifications}
        review_by_id = {r.feedback_id: r for r in reviews}

        unresolved: dict[str, int] = {}
        for cluster in clusters:
            unresolved[cluster.cluster_id] = sum(
                1 for fid in cluster.member_feedback_ids
                if review_by_id.get(fid) and review_by_id[fid].human_review_required
            )

        scores: dict[str, dict] = {}
        for cluster in clusters:
            members = []
            for fid in cluster.member_feedback_ids:
                record = records_by_id[fid]
                classification = class_by_id.get(fid)
                members.append({
                    "evidence_status": record.evidence_status,
                    "is_actionable": classification.is_actionable if classification else False,
                    "purchase_impact": classification.purchase_impact if classification else PurchaseImpact.UNKNOWN,
                })
            scores[cluster.cluster_id] = score_cluster(
                cluster, members=members,
                unresolved_conflicts=unresolved.get(cluster.cluster_id, 0),
            )
        return scores

    def _step_cards(self, clusters: list, records: list,
                    classifications: list[ClassificationResult], scores: dict,
                    summary: RunSummary) -> list:
        """证据卡生成 + 引用校验。"""
        records_by_id = {r.feedback_id: r for r in records}
        class_by_id = {c.feedback_id: c for c in classifications}
        client = None
        if not self.offline_mode and self.evidence_client is None and self.config.llm_configured:
            from ridepulse.llm_client import BaseLLMClient
            client = BaseLLMClient(
                base_url=self.config.llm_base_url,
                api_key=self.config.llm_api_key,
                model=self.config.llm_evidence_model or self.config.llm_primary_model,
                timeout_seconds=self.config.llm_timeout_seconds,
                max_retries=self.config.llm_max_retries,
            )
        cards = generate_cards(clusters, records_by_id, class_by_id, scores,
                               client or self.evidence_client)
        for cluster in clusters:
            members = set(cluster.member_feedback_ids)
            for card in cards:
                if card.cluster_id != cluster.cluster_id:
                    continue
                violations = validate_citation(card, members)
                if violations:
                    raise ValueError(
                        f"证据卡 {card.card_id} 引用越界: {violations}（必须属于簇 {cluster.cluster_id}）"
                    )
        for card in cards:
            self.db.insert_evidence_card(self.run_id, card.model_dump())
        summary.card_count = len(cards)
        return cards

    # ------------------------------------------------------------
    # 输出
    # ------------------------------------------------------------

    def _write_outputs(self, records: list, classifications: list[ClassificationResult],
                       reviews: list, human_final: dict, clusters: list, scores: dict,
                       cards: list, summary: RunSummary) -> None:
        """把运行结果写到 output/<run_id>/。"""
        records_by_id = {r.feedback_id: r for r in records}
        class_by_id = {c.feedback_id: c for c in classifications}

        # model_outputs.csv
        with (self.run_dir / "model_outputs.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "feedback_id", "sentiment", "theme_primary", "theme_secondary",
                "need_type", "scenario", "user_type", "severity", "purchase_impact",
                "jtbd", "is_actionable", "confidence", "model_name", "prompt_version",
            ])
            writer.writeheader()
            for c in classifications:
                writer.writerow({
                    "feedback_id": c.feedback_id,
                    "sentiment": c.sentiment.value, "theme_primary": c.theme_primary.value,
                    "theme_secondary": ";".join(t.value for t in c.theme_secondary),
                    "need_type": c.need_type.value, "scenario": c.scenario.value,
                    "user_type": c.user_type.value, "severity": c.severity.value,
                    "purchase_impact": c.purchase_impact.value, "jtbd": c.jtbd,
                    "is_actionable": c.is_actionable, "confidence": c.confidence,
                    "model_name": c.model_name, "prompt_version": c.prompt_version,
                })

        # review_outputs.csv
        with (self.run_dir / "review_outputs.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "feedback_id", "review_sentiment", "review_theme_primary", "review_need_type",
                "review_severity", "review_purchase_impact", "review_confidence",
                "conflict_fields", "review_status", "human_review_required",
            ])
            writer.writeheader()
            for r in reviews:
                writer.writerow({
                    "feedback_id": r.feedback_id,
                    "review_sentiment": r.review_sentiment.value,
                    "review_theme_primary": r.review_theme_primary.value,
                    "review_need_type": r.review_need_type.value,
                    "review_severity": r.review_severity.value,
                    "review_purchase_impact": r.review_purchase_impact.value,
                    "review_confidence": r.review_confidence,
                    "conflict_fields": ";".join(r.conflict_fields),
                    "review_status": r.review_status.value,
                    "human_review_required": r.human_review_required,
                })

        # human_final_outputs.csv（覆盖所有记录）
        with (self.run_dir / "human_final_outputs.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "feedback_id", "sentiment", "theme_primary", "need_type",
                "severity", "purchase_impact", "review_status",
            ])
            writer.writeheader()
            for record in records:
                final = human_final.get(record.feedback_id)
                if not final:
                    continue
                writer.writerow({
                    "feedback_id": record.feedback_id,
                    "sentiment": final["sentiment"].value if hasattr(final["sentiment"], "value") else final["sentiment"],
                    "theme_primary": final["theme_primary"].value if hasattr(final["theme_primary"], "value") else final["theme_primary"],
                    "need_type": final["need_type"].value if hasattr(final["need_type"], "value") else final["need_type"],
                    "severity": final["severity"].value if hasattr(final["severity"], "value") else final["severity"],
                    "purchase_impact": final["purchase_impact"].value if hasattr(final["purchase_impact"], "value") else final["purchase_impact"],
                    "review_status": final["review_status"].value if hasattr(final["review_status"], "value") else final["review_status"],
                })

        # cluster_results.csv
        with (self.run_dir / "cluster_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "cluster_id", "member_feedback_ids", "unique_source_record_count",
                "unique_domain_count", "platform_count", "language_count", "brand_count",
                "max_severity", "time_range_days", "is_noise", "theme_primary",
            ])
            writer.writeheader()
            for cluster in clusters:
                writer.writerow({
                    "cluster_id": cluster.cluster_id,
                    "member_feedback_ids": ";".join(cluster.member_feedback_ids),
                    "unique_source_record_count": cluster.unique_source_record_count,
                    "unique_domain_count": cluster.unique_domain_count,
                    "platform_count": cluster.platform_count,
                    "language_count": cluster.language_count,
                    "brand_count": cluster.brand_count,
                    "max_severity": cluster.max_severity.value,
                    "time_range_days": cluster.time_range_days,
                    "is_noise": int(cluster.is_noise),
                    "theme_primary": cluster.theme_primary.value if cluster.theme_primary else "",
                })

        # priority_scores.csv
        with (self.run_dir / "priority_scores.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "cluster_id", "priority_score", "priority_level", "confidence_level",
                "breakdown", "penalties", "penalty_notes",
            ])
            writer.writeheader()
            for cluster in clusters:
                score = scores.get(cluster.cluster_id, {})
                writer.writerow({
                    "cluster_id": cluster.cluster_id,
                    "priority_score": score.get("priority_score", 0),
                    "priority_level": score.get("priority_level", "P3"),
                    "confidence_level": score.get("confidence_level", "low"),
                    "breakdown": json.dumps(score.get("breakdown", {}), ensure_ascii=False),
                    "penalties": score.get("penalties", 0),
                    "penalty_notes": ";".join(score.get("penalty_notes", [])),
                })

        # evidence_cards.json / evidence_cards.md（md 附代码生成的 URL，模型不编 URL）
        cards_json = []
        for card in cards:
            card_data = card.model_dump(mode="json")  # datetime -> ISO 字符串
            card_data["evidence"] = [
                {
                    "feedback_id": fid,
                    "source_url": records_by_id[fid].source_url,
                }
                for fid in card.evidence_ids
                if fid in records_by_id
            ]
            cards_json.append(card_data)
        (self.run_dir / "evidence_cards.json").write_text(
            json.dumps(cards_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_evidence_markdown(cards_json, records_by_id, class_by_id)

        # LLM usage（真实调用时）
        usage: list[dict] = []
        for client in (self.classify_client, self.review_client, self.evidence_client):
            if client is not None and hasattr(client, "usage_log"):
                usage.extend(client.usage_log)
        if usage:
            (self.run_dir / "usage_log.json").write_text(
                json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _write_evidence_markdown(self, cards: list[dict], records_by_id: dict,
                                  class_by_id: dict) -> None:
        """证据卡 Markdown 导出：每条核心发现附 feedback_id 与代码附加的 URL。"""
        lines = [
            "# RidePulse AI Evidence Cards",
            "",
            f"> 运行: `{self.run_id}`",
            f"> 分类来源: {'离线基线（数据标注列）' if self.offline_mode else 'LLM'}",
            f"> 生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
        ]
        for card in cards:
            lines += [
                f"## {card['card_id']} {card['title']}",
                "",
                f"- 优先级: {card['priority_score']}/100（{card['priority_level']}）",
                f"- 置信度: {card['confidence_level']}",
                f"- 复核状态: {card['human_review_status']}",
                f"- 平台: {', '.join(card['platforms']) or '-'}",
                f"- 品牌: {', '.join(card['brands']) or '-'}",
                f"- 语言: {', '.join(card['languages']) or '-'}",
                f"- 根因假设（待验证）: {'; '.join(card['root_cause_hypotheses']) or '-'}",
                "",
                "问题陈述：",
                "",
                card["problem_statement"],
                "",
                "证据（URL 由系统从数据附加）：",
                "",
            ]
            for evidence in card.get("evidence", []):
                fid = evidence["feedback_id"]
                classification = class_by_id.get(fid)
                severity = classification.severity.value if classification else "-"
                lines.append(f"- [{fid}]({evidence['source_url']})（严重度 {severity}）")
            if card["recommended_actions"]:
                lines += ["", "建议动作：", ""]
                for action in card["recommended_actions"]:
                    if isinstance(action, dict):
                        name = action.get("action") or action.get("name") or ""
                        owner = action.get("owner") or ""
                    else:
                        name, owner = str(action), ""
                    lines.append(f"- {name}（{owner}）" if owner else f"- {name}")
            lines.append("")
        (self.run_dir / "evidence_cards.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_summary(self, summary: RunSummary) -> None:
        (self.run_dir / "run_summary.json").write_text(
            json.dumps(summary.model_dump(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        completed = f"{summary.completed_at:%Y-%m-%d %H:%M:%S}" if summary.completed_at else "-"
        lines = [
            "# RidePulse AI 运行报告",
            "",
            f"- run_id: `{summary.run_id}`",
            f"- 状态: `{summary.state.value}`",
            f"- 分类来源: {'离线基线（数据标注列，非 LLM）' if self.offline_mode else 'LLM'}",
            f"- Embedding 模式: `{self.embedding_mode_used or self.config.embedding_mode}`"
            + ("（⚠️ 未配置密钥回退 fake，语义聚类仅演示）" if self.embedding_mode_used == "fake" else ""),
            f"- 输入/有效/去重后: {summary.total_input} / {summary.valid_count} / {summary.deduped_count}",
            f"- 已分类: {summary.classified_count}",
            f"- 冲突/待人工复核: {summary.conflict_count} / {summary.human_review_count}",
            f"- 需求簇: {summary.cluster_count}",
            f"- 证据卡: {summary.card_count}",
            f"- 已推送飞书: {summary.delivered_count}",
            f"- 开始/完成: {summary.started_at:%Y-%m-%d %H:%M:%S} / {completed}",
            "",
        ]
        if summary.error_message:
            lines += ["## 错误", "", f"```\n{summary.error_message}\n```", ""]
        lines += [
            "## 说明",
            "",
            "- 分数完全由代码计算（文档15 §7.13），模型不参与评分。",
            "- 证据卡 URL 由系统从数据附加，模型不生成 URL。",
            "- 人工复核队列见 `human_final_outputs.csv` 与数据库 human_reviews 表。",
            "",
        ]
        (self.run_dir / "run_report.md").write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------
    # DB 恢复辅助
    # ------------------------------------------------------------

    def _row_to_record(self, row) -> Any:
        """数据库行 -> FeedbackRecord（resume 用）。"""
        from ridepulse.models import FeedbackRecord
        data = dict(row)
        data.pop("id", None)
        data.pop("run_id", None)
        data.pop("normalized_text", None)
        data.pop("duplicate_group_id", None)
        data.pop("content_sha256", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)
        return FeedbackRecord(**data)

    def _load_classifications(self) -> list[ClassificationResult]:
        rows = self.db.conn.execute(
            "SELECT * FROM classifications WHERE run_id=? ORDER BY feedback_id",
            (self.run_id,),
        ).fetchall()
        if not rows:
            return []
        results: list[ClassificationResult] = []
        for row in rows:
            data = dict(row)
            results.append(ClassificationResult(
                feedback_id=data["feedback_id"],
                sentiment=Sentiment(data["sentiment"]),
                theme_primary=ThemePrimary(data["theme_primary"]),
                theme_secondary=[ThemePrimary(t) for t in self.db._loads(data["theme_secondary"])],
                need_type=NeedType(data["need_type"]),
                scenario=data["scenario"],
                user_type=data["user_type"],
                severity=Severity(data["severity"]),
                purchase_impact=PurchaseImpact(data["purchase_impact"]),
                jtbd=data["jtbd"],
                root_cause_hypotheses=self.db._loads(data["root_cause_hypotheses"]),
                is_actionable=bool(data["is_actionable"]),
                is_constructive=bool(data["is_constructive"]),
                confidence=data["confidence"],
                rationale=data["rationale"],
                model_name=data["model_name"],
                prompt_version=data["prompt_version"],
            ))
        return results

    def _load_reviews(self) -> list:
        from ridepulse.models import ReviewResult
        rows = self.db.conn.execute(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY feedback_id", (self.run_id,)
        ).fetchall()
        if not rows:
            return []
        results = []
        for row in rows:
            data = dict(row)
            results.append(ReviewResult(
                feedback_id=data["feedback_id"],
                review_sentiment=Sentiment(data["review_sentiment"]),
                review_theme_primary=ThemePrimary(data["review_theme_primary"]),
                review_need_type=NeedType(data["review_need_type"]),
                review_severity=Severity(data["review_severity"]),
                review_purchase_impact=PurchaseImpact(data["review_purchase_impact"]),
                review_jtbd=data["review_jtbd"],
                review_confidence=data["review_confidence"],
                conflict_fields=self.db._loads(data["conflict_fields"]),
                review_status=ReviewConflictStatus(data["review_status"]),
                human_review_required=bool(data["human_review_required"]),
                model_name=data["model_name"],
                prompt_version=data["prompt_version"],
            ))
        return results

    def _load_human_final(self, records: list, classifications: list[ClassificationResult],
                          reviews: list) -> dict:
        """从 DB 恢复人工复核最终字段（resume 用）。"""
        by_id = {r.feedback_id: r for r in reviews}
        primary_by_id = {c.feedback_id: c for c in classifications}
        finals: dict[str, dict] = {}
        rows = self.db.list_human_reviews(self.run_id)
        for row in rows:
            data = dict(row)
            if data["review_status"] == "pending" or data["final_theme_primary"] is None:
                continue
            finals[data["feedback_id"]] = {
                "sentiment": Sentiment(data["final_sentiment"]),
                "theme_primary": ThemePrimary(data["final_theme_primary"]),
                "need_type": NeedType(data["final_need_type"]),
                "severity": Severity(data["final_severity"]),
                "purchase_impact": PurchaseImpact(data["final_purchase_impact"]),
                "review_status": HumanReviewStatus(data["review_status"]),
            }
        for primary in classifications:
            if primary.feedback_id not in finals:
                review = by_id.get(primary.feedback_id)
                if review and review.human_review_required:
                    finals[primary.feedback_id] = {
                        "sentiment": primary.sentiment,
                        "theme_primary": primary.theme_primary,
                        "need_type": primary.need_type,
                        "severity": primary.severity,
                        "purchase_impact": primary.purchase_impact,
                        "review_status": HumanReviewStatus.PENDING,
                    }
                else:
                    finals[primary.feedback_id] = {
                        "sentiment": primary.sentiment,
                        "theme_primary": primary.theme_primary,
                        "need_type": primary.need_type,
                        "severity": primary.severity,
                        "purchase_impact": primary.purchase_impact,
                        "review_status": HumanReviewStatus.APPROVED,
                    }
        return finals

    def _load_clusters(self) -> list:
        from ridepulse.models import ClusterInfo
        rows = self.db.conn.execute(
            "SELECT * FROM clusters WHERE run_id=? ORDER BY cluster_id", (self.run_id,)
        ).fetchall()
        if not rows:
            return []
        clusters = []
        for row in rows:
            data = dict(row)
            clusters.append(ClusterInfo(
                cluster_id=data["cluster_id"],
                member_feedback_ids=self.db._loads(data["member_json"]),
                unique_source_record_count=data["unique_source_record_count"],
                unique_domain_count=data["unique_domain_count"],
                platform_count=data["platform_count"],
                language_count=data["language_count"],
                brand_count=data["brand_count"],
                max_severity=Severity(data["max_severity"]) if data["max_severity"] else Severity.S5,
                time_range_days=data["time_range_days"],
                is_noise=bool(data["is_noise"]),
                theme_primary=ThemePrimary(data["theme_primary"]) if data["theme_primary"] else None,
            ))
        return clusters

    def _load_cards(self) -> list:
        from ridepulse.models import EvidenceCard
        rows = self.db.conn.execute(
            "SELECT * FROM evidence_cards WHERE run_id=? ORDER BY card_id", (self.run_id,)
        ).fetchall()
        if not rows:
            return []
        cards = []
        for row in rows:
            data = dict(row)
            cards.append(EvidenceCard(
                card_id=data["card_id"],
                cluster_id=data["cluster_id"],
                title=data["title"],
                problem_statement=data["problem_statement"],
                priority_score=data["priority_score"],
                priority_level=data["priority_level"],
                confidence_level=data["confidence_level"],
                evidence_ids=self.db._loads(data["evidence_ids"]),
                platforms=self.db._loads(data["platforms"]),
                brands=self.db._loads(data["brands"]),
                languages=self.db._loads(data["languages"]),
                root_cause_hypotheses=self.db._loads(data["root_cause_hypotheses"]),
                counter_evidence=data["counter_evidence"],
                recommended_actions=self.db._loads(data["recommended_actions"]),
                suggested_owner=data["suggested_owner"],
                human_review_status=HumanReviewStatus(data["human_review_status"]),
                model_name=data["model_name"],
                prompt_version=data["prompt_version"],
            ))
        return cards

    def _set_state(self, state: PipelineState) -> None:
        self.state = state
        self.db.update_run_state(self.run_id, state.value)
