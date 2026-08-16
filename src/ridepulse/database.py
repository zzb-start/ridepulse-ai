"""SQLite 数据库层 — 全系统状态持久化。

使用 Python 标准库 sqlite3，不依赖 ORM。
表结构定义：
runs / raw_sources / connector_state / feedback / classifications / reviews /
human_reviews / clusters / cluster_members / evidence_cards / deliveries / audit_events
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path


def _adapt_date(value: date) -> str:
    """Python 3.12+: sqlite3 默认日期适配器已弃用，注册自定义适配器。"""
    return value.isoformat()


def _adapt_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


sqlite3.register_adapter(date, _adapt_date)
sqlite3.register_adapter(datetime, _adapt_datetime)


def _now() -> str:
    """统一时间戳格式（UTC ISO 8601）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL DEFAULT 'CREATED',
    total_input INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    deduped_count INTEGER NOT NULL DEFAULT 0,
    classified_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    human_review_count INTEGER NOT NULL DEFAULT 0,
    cluster_count INTEGER NOT NULL DEFAULT 0,
    card_count INTEGER NOT NULL DEFAULT 0,
    delivered_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    connector_name TEXT,
    platform TEXT,
    url TEXT,
    raw_text TEXT,
    fetched_at TEXT,
    snapshot_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connector_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    cursor TEXT,
    last_fetch_at TEXT,
    last_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL UNIQUE,
    source_record_id TEXT NOT NULL,
    ingest_batch_id TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_permalink_level TEXT NOT NULL,
    source_date TEXT,
    source_date_raw TEXT,
    source_date_precision TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    language TEXT NOT NULL,
    market TEXT DEFAULT 'unknown',
    brand TEXT NOT NULL,
    product_model TEXT,
    firmware_version TEXT,
    app_version TEXT,
    original_text TEXT NOT NULL,
    translated_text TEXT,
    text_provenance TEXT NOT NULL,
    translation_method TEXT NOT NULL,
    archive_path TEXT,
    archive_sha256 TEXT,
    evidence_status TEXT NOT NULL,
    verification_note TEXT,
    normalized_text TEXT,
    duplicate_group_id TEXT,
    content_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    sentiment INTEGER NOT NULL,
    theme_primary TEXT NOT NULL,
    theme_secondary TEXT NOT NULL DEFAULT '[]',
    need_type TEXT NOT NULL,
    scenario TEXT NOT NULL DEFAULT 'unknown',
    user_type TEXT NOT NULL DEFAULT 'unknown',
    severity TEXT NOT NULL,
    purchase_impact TEXT NOT NULL DEFAULT 'unknown',
    jtbd TEXT NOT NULL,
    root_cause_hypotheses TEXT NOT NULL DEFAULT '[]',
    is_actionable INTEGER NOT NULL,
    is_constructive INTEGER NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    review_sentiment INTEGER NOT NULL,
    review_theme_primary TEXT NOT NULL,
    review_need_type TEXT NOT NULL,
    review_severity TEXT NOT NULL,
    review_purchase_impact TEXT NOT NULL,
    review_jtbd TEXT NOT NULL,
    review_confidence REAL NOT NULL,
    conflict_fields TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL,
    human_review_required INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    primary_json TEXT,
    review_json TEXT,
    conflict_fields TEXT NOT NULL DEFAULT '[]',
    final_sentiment INTEGER,
    final_theme_primary TEXT,
    final_need_type TEXT,
    final_severity TEXT,
    final_purchase_impact TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL UNIQUE,
    theme_primary TEXT,
    member_json TEXT NOT NULL DEFAULT '[]',
    unique_source_record_count INTEGER NOT NULL DEFAULT 0,
    unique_domain_count INTEGER NOT NULL DEFAULT 0,
    platform_count INTEGER NOT NULL DEFAULT 0,
    language_count INTEGER NOT NULL DEFAULT 0,
    brand_count INTEGER NOT NULL DEFAULT 0,
    max_severity TEXT,
    time_range_days INTEGER,
    is_noise INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (cluster_id, feedback_id)
);

CREATE TABLE IF NOT EXISTS evidence_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    card_id TEXT NOT NULL UNIQUE,
    cluster_id TEXT NOT NULL,
    title TEXT NOT NULL,
    problem_statement TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_level TEXT NOT NULL,
    confidence_level TEXT NOT NULL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    platforms TEXT NOT NULL DEFAULT '[]',
    brands TEXT NOT NULL DEFAULT '[]',
    languages TEXT NOT NULL DEFAULT '[]',
    root_cause_hypotheses TEXT NOT NULL DEFAULT '[]',
    counter_evidence TEXT,
    recommended_actions TEXT NOT NULL DEFAULT '[]',
    suggested_owner TEXT,
    human_review_status TEXT NOT NULL DEFAULT 'pending',
    model_name TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    delivery_target TEXT NOT NULL DEFAULT 'feishu',
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    remote_record_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);
"""


class Database:
    """SQLite 数据库封装。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        """建表 — 可重复运行（CREATE TABLE IF NOT EXISTS）。"""
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------
    # 通用辅助
    # ------------------------------------------------------------

    @staticmethod
    def _dumps(value: object) -> str:
        """JSON 序列化（用于存储 list/dict 字段，datetime 等转字符串）。"""
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _loads(value: str | None) -> object:
        if not value:
            return []
        return json.loads(value)

    # ------------------------------------------------------------
    # runs
    # ------------------------------------------------------------

    def create_run(self, run_id: str) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO runs (run_id, state, started_at, created_at, updated_at)
               VALUES (?, 'CREATED', ?, ?, ?)""",
            (run_id, now, now, now),
        )
        self.conn.commit()

    def update_run_state(self, run_id: str, state: str, error_message: str | None = None) -> None:
        now = _now()
        if error_message:
            self.conn.execute(
                "UPDATE runs SET state=?, error_message=?, updated_at=? WHERE run_id=?",
                (state, error_message, now, run_id),
            )
        else:
            self.conn.execute(
                "UPDATE runs SET state=?, updated_at=? WHERE run_id=?",
                (state, now, run_id),
            )
        self.conn.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return row

    def complete_run(self, run_id: str) -> None:
        now = _now()
        self.conn.execute(
            "UPDATE runs SET state='COMPLETED', completed_at=?, updated_at=? WHERE run_id=?",
            (now, now, run_id),
        )
        self.conn.commit()

    def count_feedback(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE run_id=?", (run_id,)
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------
    # feedback
    # ------------------------------------------------------------

    def insert_feedback(self, run_id: str, record: dict) -> None:
        """插入一条反馈记录。record 为 FeedbackRecord.model_dump()。"""
        now = _now()
        self.conn.execute(
            """INSERT OR REPLACE INTO feedback (
                run_id, feedback_id, source_record_id, ingest_batch_id,
                source_platform, source_type, source_url, source_permalink_level,
                source_date, source_date_raw, source_date_precision, accessed_at,
                language, market, brand, product_model, firmware_version, app_version,
                original_text, translated_text, text_provenance, translation_method,
                archive_path, archive_sha256, evidence_status, verification_note,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                record["feedback_id"],
                record["source_record_id"],
                record["ingest_batch_id"],
                record["source_platform"],
                record["source_type"].value if hasattr(record["source_type"], "value") else record["source_type"],
                record["source_url"],
                record["source_permalink_level"].value if hasattr(record["source_permalink_level"], "value") else record["source_permalink_level"],
                record.get("source_date"),
                record.get("source_date_raw"),
                record["source_date_precision"].value if hasattr(record["source_date_precision"], "value") else record["source_date_precision"],
                record["accessed_at"],
                record["language"],
                record.get("market") or "unknown",
                record["brand"],
                record.get("product_model"),
                record.get("firmware_version"),
                record.get("app_version"),
                record["original_text"],
                record.get("translated_text"),
                record["text_provenance"].value if hasattr(record["text_provenance"], "value") else record["text_provenance"],
                record["translation_method"].value if hasattr(record["translation_method"], "value") else record["translation_method"],
                record.get("archive_path"),
                record.get("archive_sha256"),
                record["evidence_status"].value if hasattr(record["evidence_status"], "value") else record["evidence_status"],
                record.get("verification_note"),
                now,
                now,
            ),
        )
        self.conn.commit()

    def list_feedback(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM feedback WHERE run_id=? ORDER BY feedback_id", (run_id,)
        ).fetchall()

    def get_feedback(self, feedback_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM feedback WHERE feedback_id=?", (feedback_id,)
        ).fetchone()

    def set_duplicate_group(self, feedback_id: str, group_id: str | None) -> None:
        self.conn.execute(
            "UPDATE feedback SET duplicate_group_id=?, updated_at=? WHERE feedback_id=?",
            (group_id, _now(), feedback_id),
        )
        self.conn.commit()

    def update_feedback_derived(self, feedback_id: str, *, normalized_text: str,
                                content_sha256: str, duplicate_group_id: str | None) -> None:
        """写入派生字段：规范化文本、内容指纹与重复组。"""
        self.conn.execute(
            """UPDATE feedback SET normalized_text=?, content_sha256=?,
               duplicate_group_id=?, updated_at=? WHERE feedback_id=?""",
            (normalized_text, content_sha256, duplicate_group_id, _now(), feedback_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------
    # classifications / reviews / human_reviews
    # ------------------------------------------------------------

    def insert_classification(self, run_id: str, result: dict) -> None:
        now = _now()
        self.conn.execute(
            """INSERT OR REPLACE INTO classifications (
                run_id, feedback_id, sentiment, theme_primary, theme_secondary,
                need_type, scenario, user_type, severity, purchase_impact, jtbd,
                root_cause_hypotheses, is_actionable, is_constructive, confidence,
                rationale, model_name, prompt_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result["feedback_id"],
                result["sentiment"].value if hasattr(result["sentiment"], "value") else result["sentiment"],
                result["theme_primary"].value if hasattr(result["theme_primary"], "value") else result["theme_primary"],
                self._dumps([t.value if hasattr(t, "value") else t for t in result.get("theme_secondary", [])]),
                result["need_type"].value if hasattr(result["need_type"], "value") else result["need_type"],
                result["scenario"].value if hasattr(result["scenario"], "value") else result["scenario"],
                result["user_type"].value if hasattr(result["user_type"], "value") else result["user_type"],
                result["severity"].value if hasattr(result["severity"], "value") else result["severity"],
                result["purchase_impact"].value if hasattr(result["purchase_impact"], "value") else result["purchase_impact"],
                result["jtbd"],
                self._dumps(result.get("root_cause_hypotheses", [])),
                1 if result["is_actionable"] else 0,
                1 if result["is_constructive"] else 0,
                result["confidence"],
                result["rationale"],
                result["model_name"],
                result["prompt_version"],
                now,
                now,
            ),
        )
        self.conn.commit()

    def insert_review(self, run_id: str, result: dict) -> None:
        now = _now()
        self.conn.execute(
            """INSERT OR REPLACE INTO reviews (
                run_id, feedback_id, review_sentiment, review_theme_primary,
                review_need_type, review_severity, review_purchase_impact,
                review_jtbd, review_confidence, conflict_fields, review_status,
                human_review_required, model_name, prompt_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result["feedback_id"],
                result["review_sentiment"].value if hasattr(result["review_sentiment"], "value") else result["review_sentiment"],
                result["review_theme_primary"].value if hasattr(result["review_theme_primary"], "value") else result["review_theme_primary"],
                result["review_need_type"].value if hasattr(result["review_need_type"], "value") else result["review_need_type"],
                result["review_severity"].value if hasattr(result["review_severity"], "value") else result["review_severity"],
                result["review_purchase_impact"].value if hasattr(result["review_purchase_impact"], "value") else result["review_purchase_impact"],
                result["review_jtbd"],
                result["review_confidence"],
                self._dumps(result.get("conflict_fields", [])),
                result["review_status"].value if hasattr(result["review_status"], "value") else result["review_status"],
                1 if result["human_review_required"] else 0,
                result["model_name"],
                result["prompt_version"],
                now,
                now,
            ),
        )
        self.conn.commit()

    def list_human_reviews(self, run_id: str, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute(
                "SELECT * FROM human_reviews WHERE run_id=? AND review_status=?",
                (run_id, status),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM human_reviews WHERE run_id=?", (run_id,)
        ).fetchall()

    def insert_human_review_pending(self, run_id: str, feedback_id: str, *,
                                    primary_json: dict | None = None,
                                    review_json: dict | None = None,
                                    conflict_fields: list[str] | None = None) -> None:
        """插入待人工复核记录（已存在则忽略，避免重复）。"""
        now = _now()
        self.conn.execute(
            """INSERT OR IGNORE INTO human_reviews
               (run_id, feedback_id, primary_json, review_json, conflict_fields,
                review_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                run_id,
                feedback_id,
                self._dumps(primary_json) if primary_json is not None else None,
                self._dumps(review_json) if review_json is not None else None,
                self._dumps(conflict_fields or []),
                now,
                now,
            ),
        )
        self.conn.commit()

    def update_human_review(
        self,
        run_id: str,
        feedback_id: str,
        *,
        status: str,
        note: str | None = None,
        reviewer: str | None = None,
        final: dict | None = None,
    ) -> None:
        now = _now()
        self.conn.execute(
            """UPDATE human_reviews SET
                final_sentiment=?, final_theme_primary=?, final_need_type=?,
                final_severity=?, final_purchase_impact=?,
                review_status=?, review_note=?, reviewer=?, reviewed_at=?, updated_at=?
               WHERE run_id=? AND feedback_id=?""",
            (
                (final or {}).get("sentiment"),
                (final or {}).get("theme_primary"),
                (final or {}).get("need_type"),
                (final or {}).get("severity"),
                (final or {}).get("purchase_impact"),
                status,
                note,
                reviewer,
                now,
                now,
                run_id,
                feedback_id,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------
    # clusters / evidence_cards / deliveries / audit
    # ------------------------------------------------------------

    def insert_cluster(self, run_id: str, cluster: dict) -> None:
        now = _now()
        self.conn.execute(
            """INSERT OR REPLACE INTO clusters (
                run_id, cluster_id, theme_primary, member_json,
                unique_source_record_count, unique_domain_count, platform_count,
                language_count, brand_count, max_severity, time_range_days, is_noise,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                cluster["cluster_id"],
                cluster.get("theme_primary"),
                self._dumps(cluster.get("member_feedback_ids", [])),
                cluster.get("unique_source_record_count", 0),
                cluster.get("unique_domain_count", 0),
                cluster.get("platform_count", 0),
                cluster.get("language_count", 0),
                cluster.get("brand_count", 0),
                cluster.get("max_severity"),
                cluster.get("time_range_days"),
                1 if cluster.get("is_noise") else 0,
                now,
                now,
            ),
        )
        for fid in cluster.get("member_feedback_ids", []):
            self.conn.execute(
                """INSERT OR IGNORE INTO cluster_members
                   (run_id, cluster_id, feedback_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, cluster["cluster_id"], fid, now, now),
            )
        self.conn.commit()

    def insert_evidence_card(self, run_id: str, card: dict) -> None:
        now = _now()
        self.conn.execute(
            """INSERT OR REPLACE INTO evidence_cards (
                run_id, card_id, cluster_id, title, problem_statement,
                priority_score, priority_level, confidence_level, evidence_ids,
                platforms, brands, languages, root_cause_hypotheses, counter_evidence,
                recommended_actions, suggested_owner, human_review_status,
                model_name, prompt_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                card["card_id"],
                card["cluster_id"],
                card["title"],
                card["problem_statement"],
                card["priority_score"],
                card["priority_level"],
                card["confidence_level"],
                self._dumps(card.get("evidence_ids", [])),
                self._dumps(card.get("platforms", [])),
                self._dumps(card.get("brands", [])),
                self._dumps(card.get("languages", [])),
                self._dumps(card.get("root_cause_hypotheses", [])),
                card.get("counter_evidence"),
                self._dumps(card.get("recommended_actions", [])),
                card.get("suggested_owner"),
                card.get("human_review_status", "pending"),
                card.get("model_name"),
                card.get("prompt_version"),
                now,
                now,
            ),
        )
        self.conn.commit()

    def get_evidence_card(self, card_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM evidence_cards WHERE card_id=?", (card_id,)
        ).fetchone()

    def list_evidence_cards(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM evidence_cards WHERE run_id=? ORDER BY priority_score DESC",
            (run_id,),
        ).fetchall()

    def update_card_status(self, card_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE evidence_cards SET human_review_status=?, updated_at=? WHERE card_id=?",
            (status, _now(), card_id),
        )
        self.conn.commit()

    def insert_delivery(
        self,
        run_id: str,
        *,
        object_type: str,
        object_id: str,
        status: str = "pending",
    ) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO deliveries
               (run_id, object_type, object_id, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, object_type, object_id, status, now, now),
        )
        self.conn.commit()

    def audit(
        self,
        run_id: str,
        *,
        actor: str,
        action: str,
        object_type: str | None = None,
        object_id: str | None = None,
        before: object = None,
        after: object = None,
    ) -> None:
        """审计日志：记录谁/做了什么/修改前后摘要/时间。"""
        self.conn.execute(
            """INSERT INTO audit_events
               (run_id, actor, action, object_type, object_id, before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                actor,
                action,
                object_type,
                object_id,
                self._dumps(before) if before is not None else None,
                self._dumps(after) if after is not None else None,
                _now(),
            ),
        )
        self.conn.commit()
