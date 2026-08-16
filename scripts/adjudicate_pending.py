"""M4 遗留 12 条 pending 人工复核裁决 — 回填 human_final_outputs.csv 并生成裁决记录。

裁决原则(2026-08-14,队长代执行):
1. 有 gold 配对的条目(F0002/F0014/F0036/F0038/F0040):最终值以 gold 为准(gold 为双人仲裁标准答案);
2. 无 gold 的冲突字段:以复判模型与原始证据严重度为准;
   severity 参考 M4 已知限制(主模型系统性高估一档,9/9);
3. 未冲突字段保持流水线输出,不擅改。

用法: python scripts/adjudicate_pending.py --run-id RUN-20260813-211103
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

# feedback_id -> {field: (final_value, 依据)}
ADJUDICATION = {
    "F0002": {
        "sentiment": ("1", "gold"),
        "theme_primary": ("connectivity", "gold,与主模型一致"),
        "purchase_impact": ("influence", "gold"),
    },
    "F0003": {
        "severity": ("S2", "复判 S2;白屏可杀App恢复,无数据丢失;参考系统性高估提示"),
    },
    "F0005": {
        "need_type": ("real_need", "复判 real_need;上传失败为真实缺陷报告,unknown 不合理"),
    },
    "F0010": {
        "need_type": ("real_need", "复判 real_need;开发团队投诉非功能需求"),
        "purchase_impact": ("influence", "主模型 influence;论坛劝退影响购买决策"),
    },
    "F0013": {
        "severity": ("S4", "原始证据严重度 S4(evidence_cards EC-0001 F0013),主模型一致"),
    },
    "F0014": {
        "need_type": ("feature_request", "gold"),
        "severity": ("S2", "gold"),
        "purchase_impact": ("blocker", "gold"),
        "sentiment": ("1", "gold"),
    },
    "F0015": {
        "theme_primary": ("feature_request", "功能限制(无法直连Strava下载路线),主模型一致"),
        "need_type": ("feature_request", "主模型 feature_request;复判 real_need 不贴切"),
        "severity": ("S4", "原始证据严重度 S4(EC-0011 F0015),主模型一致"),
    },
    "F0016": {
        "need_type": ("real_need", "复判 real_need;屏幕反光是现有产品缺陷而非新功能请求"),
    },
    "F0032": {
        "severity": ("S2", "复判 S2;行业 API 政策新闻,非直接产品缺陷"),
    },
    "F0036": {
        "severity": ("S3", "gold,与主模型一致"),
        "sentiment": ("1", "gold"),
        "purchase_impact": ("influence", "gold"),
    },
    "F0038": {
        "sentiment": ("1", "gold"),
        "theme_primary": ("firmware", "gold,与复判一致"),
        "need_type": ("incidental_failure", "gold;故障致换机,非持续需求"),
        "severity": ("S2", "gold"),
    },
    "F0040": {
        "severity": ("S3", "gold,与复判一致"),
        "sentiment": ("1", "gold"),
        "purchase_impact": ("blocker", "gold"),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    run_dir = Path("output") / args.run_id
    path = run_dir / "human_final_outputs.csv"
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())

    changed, records = 0, []
    for row in rows:
        fid = row["feedback_id"]
        if row.get("review_status") != "pending" or fid not in ADJUDICATION:
            continue
        for field, (value, reason) in ADJUDICATION[fid].items():
            old = row[field]
            row[field] = value
            records.append(
                {
                    "feedback_id": fid,
                    "field": field,
                    "from": old,
                    "to": value,
                    "basis": reason,
                }
            )
        row["review_status"] = "resolved"
        changed += 1

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    rec_path = run_dir / "adjudication_record.csv"
    with open(rec_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["feedback_id", "field", "from", "to", "basis"]
        )
        writer.writeheader()
        writer.writerows(records)

    # 裁决记录 markdown(供队长/评审复核)
    md = [
        "# 人工复核裁决记录(12 条 pending)",
        "",
        f"> run_id: `{args.run_id}` | 裁决: 队长代执行 | 日期: 2026-08-14",
        "> 原则: ①有 gold 的条目以 gold 为准;②无 gold 冲突字段以复判模型+原始证据严重度为准,",
        ">  severity 参考主模型系统性高估一档的已知限制;③未冲突字段保持流水线输出。",
        "",
        "| feedback_id | 字段 | 原值 | 终值 | 依据 |",
        "|---|---|---|---|---|",
    ]
    for rec in records:
        md.append(
            f"| {rec['feedback_id']} | {rec['field']} | {rec['from']} | {rec['to']} | {rec['basis']} |"
        )
    md.append("")
    md.append(f"共裁决 {changed} 条,{len(records)} 处字段变更。变更明细同时见 `adjudication_record.csv`。")
    (run_dir / "adjudication_record.md").write_text("\n".join(md), encoding="utf-8")

    print(f"裁决 {changed} 条,变更 {len(records)} 处字段;已回填 {path}")
    print(f"记录: {rec_path.name} / adjudication_record.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
