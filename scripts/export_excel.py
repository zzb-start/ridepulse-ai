"""导出 40 强附件 Excel(12 文档 §2.2 配套数据文件)。

- 02_真实反馈与来源_核验版.xlsx: 37 条正式数据(原始数据/分类标注/统计汇总)
- 05_样例数据分析.xlsx: 21 簇聚类 + 评测指标 + 优先级

用法: python scripts/export_excel.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

RUN_DIR = Path("output") / "RUN-20260813-211103"
OUT = Path("D:/0AI先锋/final_submission")


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(RUN_DIR / name, encoding="utf-8-sig")


def main() -> int:
    # ---- 数据版 ----
    verified = pd.read_csv(
        Path("data/verified/feedback_verified.csv"), encoding="utf-8-sig"
    )
    summary = pd.DataFrame(
        [
            {"指标": "正式反馈", "值": len(verified), "说明": "DATASET v1,2026-08-13冻结"},
            {"指标": "平台", "值": verified["source_platform"].nunique(),
             "说明": "12 平台(24 来源页)"},
            {"指标": "语言", "值": "中/英", "说明": f"zh {sum(verified['language']=='zh')} / en {sum(verified['language']=='en')}"},
            {"指标": "需求簇", "值": 21, "说明": "37 条 → 21 簇"},
            {"指标": "证据卡", "值": 21, "说明": "EC-2026-0001~0021"},
        ]
    )
    with pd.ExcelWriter(OUT / "02_真实反馈与来源_核验版.xlsx", engine="openpyxl") as w:
        verified.to_excel(w, sheet_name="原始数据与标注", index=False)
        summary.to_excel(w, sheet_name="统计汇总", index=False)

    # ---- 分析版 ----
    clusters = load_csv("cluster_results.csv")
    prio = load_csv("priority_scores.csv")
    metrics = json.loads((RUN_DIR / "metrics.json").read_text(encoding="utf-8"))
    metrics_rows = [
        {"指标": f"{k} accuracy", "值": v["accuracy"]} for k, v in metrics.items()
        if isinstance(v, dict) and "accuracy" in v
    ] + [{"指标": "severity_weighted_kappa", "值": metrics["severity_weighted_kappa"]}]
    metrics_df = pd.DataFrame(metrics_rows)
    cards = json.loads((RUN_DIR / "evidence_cards.json").read_text(encoding="utf-8"))
    cards_rows = [
        {
            "card_id": c["card_id"],
            "title": c["title"],
            "priority_score": c["priority_score"],
            "priority_level": c["priority_level"],
            "platforms": "|".join(c.get("platforms", [])),
            "confidence": c.get("confidence_level", ""),
        }
        for c in cards
    ]
    cards_df = pd.DataFrame(cards_rows)
    with pd.ExcelWriter(OUT / "05_样例数据分析.xlsx", engine="openpyxl") as w:
        clusters.to_excel(w, sheet_name="需求簇", index=False)
        prio.to_excel(w, sheet_name="优先级评分", index=False)
        metrics_df.to_excel(w, sheet_name="评测指标", index=False)
        cards_df.to_excel(w, sheet_name="证据卡汇总", index=False)

    print(f"已生成: {OUT/'02_真实反馈与来源_核验版.xlsx'}, {OUT/'05_样例数据分析.xlsx'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
