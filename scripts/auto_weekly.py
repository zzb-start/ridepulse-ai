"""RidePulse 周更自动编排 — 让系统长期自动运转,人工只处理冲突裁决。

步骤(可用 --steps 指定子集,默认全部):
  selfcheck  探测 LLM API(先 /models,失败则最小 chat 调用);任何异常立即失败,不静默产出
  collect    对 data/auto/collect_targets.csv 的每个目标做增量采集(App Store RSS 公开接口),
             新评论按 FeedbackRecord 契约追加到 data/auto/feedback_pool.csv(游标去重、可回链)
  run        对 feedback_pool.csv 跑完整流水线(分类→复判→聚类→评分→证据卡);
             data/auto/human_decisions.csv 中已有人工裁决的冲突回填,其余保持 pending(评分扣分)
  report     写 output/<run_id>/auto_report.json 与 auto_conflicts.md(冲突明细,供工作流开 issue)

原则:不伪造数据;单目标采集失败只记录不中断;任何 LLM 异常让步骤失败(GitHub Actions 亮红),
绝不静默产出劣质数据。

用法: PYTHONPATH=src python scripts/auto_weekly.py [--steps selfcheck,collect,run,report]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from ridepulse.cli import _load_dotenv
from ridepulse.config import get_config
from ridepulse.database import Database
from ridepulse.pipeline import Pipeline

AUTO_DIR = Path("data/auto")
POOL_PATH = AUTO_DIR / "feedback_pool.csv"
TARGETS_PATH = AUTO_DIR / "collect_targets.csv"
CURSORS_PATH = AUTO_DIR / "cursors.json"
DECISIONS_PATH = AUTO_DIR / "human_decisions.csv"
LATEST_RUN_TXT = AUTO_DIR / "latest_run.txt"
VERIFIED_SEED = Path("data/verified/feedback_verified.csv")

# 与 feedback_verified.csv 一致的全字段表头(含标注列,自动采集行留空)
POOL_COLUMNS = [
    "feedback_id", "source_record_id", "ingest_batch_id", "source_platform",
    "source_type", "source_url", "source_permalink_level", "source_date",
    "source_date_raw", "source_date_precision", "accessed_at", "language",
    "market", "brand", "product_model", "firmware_version", "app_version",
    "original_text", "translated_text", "text_provenance", "translation_method",
    "archive_path", "archive_sha256", "evidence_status", "verification_note",
    "sentiment", "theme_primary", "theme_secondary", "need_type", "scenario",
    "user_type", "severity", "purchase_impact", "jtbd", "is_actionable",
    "is_constructive", "legacy_evidence_id", "text_sha256", "dataset_version",
]


def _now() -> datetime:
    return datetime.now()


# ------------------------------------------------------------
# selfcheck
# ------------------------------------------------------------

def selfcheck(config) -> dict:
    """探测 LLM API 是否可用:先 GET /models,失败退回最小 chat 调用。"""
    base = config.llm_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {config.llm_api_key}"}
    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{base}/models", headers=headers)
        if resp.status_code == 200:
            return {"ok": True, "method": "models", "base_url": base,
                    "model": config.llm_primary_model}
        resp = client.post(
            f"{base}/chat/completions", headers=headers,
            json={
                "model": config.llm_primary_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 4, "temperature": 0,
            },
        )
        if resp.status_code == 200:
            return {"ok": True, "method": "chat", "base_url": base,
                    "model": config.llm_primary_model}
        raise RuntimeError(
            f"LLM API 自检失败: HTTP {resp.status_code} — {resp.text[:200]}"
        )


# ------------------------------------------------------------
# collect
# ------------------------------------------------------------

def _seed_pool_if_missing() -> bool:
    """首次运行时用已核验的 DATASET v1(37 条)初始化反馈池。"""
    if POOL_PATH.exists():
        return False
    if VERIFIED_SEED.exists():
        POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
        POOL_PATH.write_bytes(VERIFIED_SEED.read_bytes())
        return True
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with POOL_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=POOL_COLUMNS).writeheader()
    return False


def _next_feedback_id(pool_rows: list[dict]) -> str:
    ids = [int(r["feedback_id"][1:]) for r in pool_rows if r.get("feedback_id", "").startswith("F")]
    return f"F{max(ids) + 1:04d}" if ids else "F0001"


def _entry_fields(entry: dict) -> dict:
    """从 RSS entry 提取评分/日期/版本(缺失时为 None)。"""
    def label(path: str) -> str | None:
        node = entry.get(path) or {}
        return (node.get("label") or "").strip() or None
    return {
        "rating": label("im:rating"),
        "updated": label("updated"),
        "app_version": label("im:version"),
    }


def _review_id(entry: dict) -> str:
    return ((entry.get("id") or {}).get("label") or "").rsplit("=", 1)[-1]


def _parse_date(raw: str | None) -> tuple[str | None, str | None]:
    """'2026-08-13T01:23:45-07:00' -> (source_date, source_date_raw)。"""
    if not raw:
        return None, None
    return raw[:10], raw


def collect(config) -> dict:
    """增量采集:每个目标按游标拉最新评论,新评论写入反馈池。"""
    from ridepulse.collectors.app_store_rss import AppStoreRSSConnector

    seeded = _seed_pool_if_missing()
    with POOL_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        pool_rows = list(csv.DictReader(f))
    existing_ids = {r["source_record_id"] for r in pool_rows}

    targets = list(csv.DictReader(TARGETS_PATH.open("r", encoding="utf-8-sig", newline="")))
    if not targets:
        raise RuntimeError(f"采集目标为空: {TARGETS_PATH}")

    cursors: dict = {}
    if CURSORS_PATH.exists():
        cursors = json.loads(CURSORS_PATH.read_text(encoding="utf-8"))

    new_rows: list[dict] = []
    report: list[dict] = []
    raw_run_id = f"RUN-{_now():%Y%m%d-%H%M%S}"
    accessed_at = date.today().isoformat()
    ingest_batch = f"AUTO-{_now():%Y%m%d}"
    next_id = _next_feedback_id(pool_rows)

    for target in targets:
        app_id = target["app_id"]
        entry_log = {"app_id": app_id, "storefront": target["storefront"],
                     "status": "ok", "new": 0}
        try:
            before = len(new_rows)
            connector = AppStoreRSSConnector(app_id=app_id, storefront=target["storefront"])
            reviews = connector.fetch(
                since=cursors.get(app_id), limit=50,
                run_id=raw_run_id, out_dir=str(config.output_dir / "auto_raw"),
            )
            # 从原始快照取评分/日期/版本(连接器列表只含正文与链接)
            snapshot = Path(config.output_dir) / "auto_raw" / raw_run_id / "raw" \
                / f"app_store_rss_{target['storefront']}_{app_id}.json"
            entry_by_id: dict[str, dict] = {}
            if snapshot.exists():
                feed = json.loads(snapshot.read_text(encoding="utf-8")).get("feed") or {}
                entry_by_id = {_review_id(e): _entry_fields(e) for e in (feed.get("entry") or [])}

            for review in reviews:
                rid = review.source_record_id
                if rid in existing_ids:
                    continue  # 已在池中(跨批次去重)
                fields = entry_by_id.get(rid, {})
                src_date, src_date_raw = _parse_date(fields.get("updated"))
                fallback_url = (
                    f"https://apps.apple.com/{target['storefront']}/app/"
                    f"{target['app_name']}/id{app_id}"
                )
                new_rows.append({
                    "feedback_id": _next_feedback_id(pool_rows + new_rows),
                    "source_record_id": rid,
                    "ingest_batch_id": ingest_batch,
                    "source_platform": "App Store",
                    "source_type": "app_store",
                    "source_url": review.url or fallback_url,
                    "source_permalink_level": "page_only",
                    "source_date": src_date or "",
                    "source_date_raw": src_date_raw or "",
                    "source_date_precision": "day" if src_date else "unknown",
                    "accessed_at": accessed_at,
                    "language": target["language"],
                    "market": target["market"],
                    "brand": target["brand"],
                    "product_model": target["product_model"] or "",
                    "firmware_version": "",
                    "app_version": fields.get("app_version") or "",
                    "original_text": review.raw_text,
                    "translated_text": "",
                    "text_provenance": "verbatim",
                    "translation_method": "not_needed",
                    "archive_path": "",
                    "archive_sha256": "",
                    "evidence_status": "unverified",
                    "verification_note": "自动采集(App Store RSS 公开接口),待人工核验",
                    "sentiment": "", "theme_primary": "", "theme_secondary": "",
                    "need_type": "", "scenario": "", "user_type": "", "severity": "",
                    "purchase_impact": "", "jtbd": "", "is_actionable": "",
                    "is_constructive": "", "legacy_evidence_id": "",
                    "text_sha256": "", "dataset_version": "auto-pool",
                })
                existing_ids.add(rid)
            entry_log["new"] = len(new_rows) - before
            # 以接口游标推进(仅当有新评论时连接器才写入 cursor)
            if connector.last_response.get("cursor"):
                cursors[app_id] = connector.last_response["cursor"]
        except Exception as exc:  # noqa: BLE001 — 单目标失败不影响其他目标
            entry_log["status"] = f"failed: {exc}"[:120]
        report.append(entry_log)

    if new_rows:
        with POOL_PATH.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=POOL_COLUMNS)
            writer.writerows(new_rows)
    CURSORS_PATH.write_text(json.dumps(cursors, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "seeded": seeded,
        "pool_rows_before": len(pool_rows),
        "new_rows": len(new_rows),
        "pool_rows_after": len(pool_rows) + len(new_rows),
        "targets": report,
        "next_feedback_id": next_id,
    }


# ------------------------------------------------------------
# run / report
# ------------------------------------------------------------

def _load_decisions() -> dict:
    """读取人工裁决 CSV -> {feedback_id: 决策字典}(供 Pipeline._step_human 回填)。"""
    if not DECISIONS_PATH.exists():
        return {}
    decisions: dict = {}
    for row in csv.DictReader(DECISIONS_PATH.open("r", encoding="utf-8-sig", newline="")):
        fid = row.get("feedback_id", "").strip()
        if not fid:
            continue
        decisions[fid] = {
            "sentiment": int(row["sentiment"]),
            "theme_primary": row["theme_primary"],
            "need_type": row["need_type"],
            "severity": row["severity"],
            "purchase_impact": row["purchase_impact"],
            "reviewer": "human",
            "note": row.get("note", ""),
        }
    return decisions


def run_pipeline(config) -> dict:
    """对反馈池跑完整流水线,写 latest_run.txt。"""
    if not POOL_PATH.exists():
        raise RuntimeError(f"反馈池不存在: {POOL_PATH}(先执行 collect 步骤)")
    decisions = _load_decisions()
    run_id = f"RUN-{_now():%Y%m%d-%H%M%S}"
    pipeline = Pipeline(run_id=run_id, db=Database(config.db_path), config=config)
    summary = pipeline.run(str(POOL_PATH), human_decisions=decisions)
    LATEST_RUN_TXT.write_text(run_id, encoding="utf-8")
    return {
        "run_id": run_id,
        "total_input": summary.total_input,
        "valid_count": summary.valid_count,
        "classified": summary.classified_count,
        "conflicts": summary.conflict_count,
        "human_review_required": summary.human_review_count,
        "clusters": summary.cluster_count,
        "cards": summary.card_count,
        "human_decisions_applied": len(decisions),
        "state": summary.state.value,
    }


def report(config) -> dict:
    """写 auto_report.json 与 auto_conflicts.md(冲突明细供开 issue 用)。"""
    run_id = LATEST_RUN_TXT.read_text(encoding="utf-8").strip()
    run_dir = config.output_dir / run_id
    primaries = {
        r["feedback_id"]: r for r in csv.DictReader(
            (run_dir / "model_outputs.csv").open("r", encoding="utf-8-sig", newline=""))
    }
    pool = {
        r["feedback_id"]: r for r in csv.DictReader(POOL_PATH.open("r", encoding="utf-8-sig", newline=""))
    }

    conflicts: list[dict] = []
    for rev in csv.DictReader((run_dir / "review_outputs.csv").open("r", encoding="utf-8-sig", newline="")):
        if rev.get("human_review_required", "").strip().lower() != "true":
            continue
        fid = rev["feedback_id"]
        primary = primaries.get(fid, {})
        src = pool.get(fid, {})
        conflicts.append({
            "feedback_id": fid,
            "conflict_fields": rev.get("conflict_fields", ""),
            "primary": {f: primary.get(f, "") for f in
                        ("sentiment", "theme_primary", "need_type", "severity", "purchase_impact")},
            "review": {f: rev.get(f"review_{f}", "") for f in
                       ("sentiment", "theme_primary", "need_type", "severity", "purchase_impact")},
            "text": (src.get("original_text") or "")[:120],
            "source_url": src.get("source_url", ""),
        })

    (run_dir / "auto_report.json").write_text(
        json.dumps({
            "run_id": run_id,
            "generated_at": _now().isoformat(timespec="seconds"),
            "conflict_count": len(conflicts),
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 自动流水线 · 人工复核提醒",
        "",
        f"> run_id: `{run_id}` | 时间: {_now():%Y-%m-%d %H:%M}",
        "> 双模型字段级冲突不自动采信,以下条目需要人工裁决。",
        "> 裁决方式:把结论写入 `data/auto/human_decisions.csv`(feedback_id + 五个字段),下次运行自动回填。",
        "",
        f"共 {len(conflicts)} 条待裁决:",
        "",
        "| feedback_id | 冲突字段 | 第一轮 | 复判 | 原文摘要 | 来源 |",
        "|---|---|---|---|---|---|",
    ]
    for c in conflicts:
        primary_cell = "; ".join(f"{k}={v}" for k, v in c["primary"].items() if v)
        review_cell = "; ".join(f"{k}={v}" for k, v in c["review"].items() if v)
        lines.append(
            f"| {c['feedback_id']} | {c['conflict_fields']} | {primary_cell} "
            f"| {review_cell} | {c['text']} | {c['source_url']} |"
        )
    lines.append("")
    lines.append("未裁决的冲突在优先级评分中按规则扣分,并在下次运行时再次提醒。")
    (run_dir / "auto_conflicts.md").write_text("\n".join(lines), encoding="utf-8")
    return {"run_id": run_id, "conflict_count": len(conflicts),
            "conflicts_file": str(run_dir / "auto_conflicts.md")}


# ------------------------------------------------------------
# 入口
# ------------------------------------------------------------

def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default="selfcheck,collect,run,report",
                        help="逗号分隔的步骤子集")
    args = parser.parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]

    config = get_config()
    summary: dict = {"steps": steps, "started_at": _now().isoformat(timespec="seconds")}
    try:
        if "selfcheck" in steps:
            if not config.llm_configured:
                raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY / LLM_PRIMARY_MODEL")
            summary["selfcheck"] = selfcheck(config)
        if "collect" in steps:
            summary["collect"] = collect(config)
        if "run" in steps:
            if summary.get("collect", {}).get("new_rows", 0) == 0 and LATEST_RUN_TXT.exists():
                print("无新数据且已有运行,跳过本轮流水线(如需强制重跑请手动执行)")
                summary["run"] = {"skipped": True, "reason": "no_new_rows"}
            else:
                summary["run"] = run_pipeline(config)
        if "report" in steps:
            if not LATEST_RUN_TXT.exists():
                raise RuntimeError("latest_run.txt 不存在(先执行 run 步骤)")
            summary["report"] = report(config)
        summary["ok"] = True
    except Exception as exc:  # noqa: BLE001 — 任何失败都要显式报错
        summary["ok"] = False
        summary["error"] = str(exc)[:500]
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
