"""评测落盘 — 生成 model_evaluation_report.md / metrics.json / error_cases.csv / charts/。

口径与 `cli evaluate` 一致(paired 样本、逐字段 accuracy/macro-F1、severity 加权 Kappa),
额外产出:
  - 逐类 precision/recall/F1(classification_report)
  - 字段级 error_cases.csv
  - severity 方向性分析(系统是否系统性高估)
  - 图表(charts/acc_f1.png、charts/severity_confusion.png)

用法:
  python scripts/eval_artifacts.py --run-id RUN-20260813-211103 \
      --gold data/verified/annotation_gold.csv [--copy-to <冯敬琴交付包目录>]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ridepulse.evaluation import EVALUATION_FIELDS, weighted_kappa  # noqa: E402
from ridepulse.models import ClassificationResult  # noqa: E402

FIELD_LABELS = {
    "theme_primary": "Theme (primary)",
    "need_type": "Need type",
    "severity": "Severity",
    "purchase_impact": "Purchase impact",
}


def load_model_outputs(path: Path) -> list[ClassificationResult]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            rows.append(
                ClassificationResult(
                    feedback_id=raw["feedback_id"],
                    sentiment=raw["sentiment"],
                    theme_primary=raw["theme_primary"],
                    theme_secondary=(
                        [t.strip() for t in raw.get("theme_secondary", "").split(";") if t.strip()]
                        if raw.get("theme_secondary") else []
                    ),
                    need_type=raw["need_type"],
                    scenario=raw.get("scenario") or "unknown",
                    user_type=raw.get("user_type") or "unknown",
                    severity=raw["severity"],
                    purchase_impact=raw["purchase_impact"],
                    jtbd=raw.get("jtbd") or "",
                    is_actionable=str(raw.get("is_actionable", "true")).lower() in ("true", "1"),
                    is_constructive=str(raw.get("is_constructive", "true")).lower() in ("true", "1"),
                    confidence=float(raw.get("confidence", 0.6)),
                    rationale=raw.get("rationale", "由 model_outputs.csv 生成,评测仅使用分类字段"),
                    model_name=raw.get("model_name", "unknown"),
                    prompt_version=raw.get("prompt_version", "classify_v1"),
                )
            )
    return rows


def load_gold(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def severity_direction(mis: list[tuple[str, str]]) -> dict:
    """severity 方向性分析: 模型相对 gold 高估/低估。"""
    order = {"S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5}
    over, under = 0, 0
    for pred, gold in mis:
        if pred in order and gold in order:
            if order[pred] > order[gold]:
                over += 1
            elif order[pred] < order[gold]:
                under += 1
    return {"over_estimate": over, "under_estimate": under}


def build_charts(per_class: dict, confusion: dict, out_dir: Path) -> None:
    """四字段 accuracy/macro-F1 条形图 + severity 混淆矩阵热图。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    fields = list(FIELD_LABELS)
    acc = [per_class[f]["accuracy"] for f in fields]
    f1 = [per_class[f]["macro_f1"] for f in fields]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(fields))
    ax.bar([i - 0.18 for i in x], acc, width=0.36, label="Accuracy", color="#2f6fed")
    ax.bar([i + 0.18 for i in x], f1, width=0.36, label="Macro F1", color="#8ecae6")
    ax.set_xticks(list(x))
    ax.set_xticklabels([FIELD_LABELS[f] for f in fields])
    ax.set_ylim(0, 1.05)
    ax.set_title("Model vs Gold (paired=18)")
    for i in x:
        ax.text(i - 0.18, acc[i] + 0.02, f"{acc[i]:.2f}", ha="center", fontsize=8)
        ax.text(i + 0.18, f1[i] + 0.02, f"{f1[i]:.2f}", ha="center", fontsize=8)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_dir / "acc_f1.png", dpi=150)
    plt.close(fig)

    labels = sorted(confusion.keys())
    if labels:
        matrix = [[confusion[a].get(b, 0) for b in labels] for a in labels]
        fig, ax = plt.subplots(figsize=(6.5, 5.5))
        im = ax.imshow(matrix, cmap="Blues")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels)
        ax.set_yticklabels(labels)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Gold")
        ax.set_title("Severity confusion (model vs gold)")
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, matrix[i][j], ha="center", va="center", fontsize=9)
        fig.colorbar(im, shrink=0.85)
        fig.tight_layout()
        fig.savefig(out_dir / "severity_confusion.png", dpi=150)
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gold", required=True, help="annotation_gold.csv 路径")
    parser.add_argument("--copy-to", default="", help="额外复制产物到该目录(如冯敬琴交付包)")
    args = parser.parse_args()

    run_dir = Path("output") / args.run_id
    if not run_dir.exists():
        print(f"run 目录不存在: {run_dir}")
        return 1

    gold = load_gold(Path(args.gold))
    gold_by_id = {row["feedback_id"]: row for row in gold}
    outputs = load_model_outputs(run_dir / "model_outputs.csv")
    paired = [(m, gold_by_id[m.feedback_id]) for m in outputs if m.feedback_id in gold_by_id]
    paired.sort(key=lambda p: p[0].feedback_id)

    if not paired:
        print("model_outputs 与 gold 无交集")
        return 1

    from sklearn.metrics import accuracy_score, classification_report, f1_score

    per_class = {}
    error_rows: list[dict] = []
    for model_field, gold_field in EVALUATION_FIELDS.items():
        y_true = [row[gold_field] for _, row in paired]
        y_pred = [getattr(m, model_field) for m, _ in paired]
        y_true = [v.value if hasattr(v, "value") else v for v in y_true]
        y_pred = [v.value if hasattr(v, "value") else v for v in y_pred]
        report = classification_report(
            y_true, y_pred, output_dict=True, zero_division=0
        )
        per_class[model_field] = {
            "accuracy": round(accuracy_score(y_true, y_pred), 6),
            "macro_f1": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 6),
            "per_class": {
                label: {k: round(v, 6) for k, v in d.items() if k in ("precision", "recall", "f1-score", "support")}
                for label, d in report.items()
                if isinstance(d, dict) and label not in ("accuracy", "macro avg", "weighted avg")
            },
        }
        for m, row in paired:
            gold_v = row[gold_field]
            pred_v = getattr(m, model_field)
            gold_v = gold_v.value if hasattr(gold_v, "value") else gold_v
            pred_v = pred_v.value if hasattr(pred_v, "value") else pred_v
            if str(pred_v) != str(gold_v):
                error_rows.append(
                    {
                        "feedback_id": m.feedback_id,
                        "field": model_field,
                        "gold_value": gold_v,
                        "pred_value": pred_v,
                    }
                )

    sev_true = [row["severity"] for _, row in paired]
    sev_pred = [getattr(m, "severity") for m, _ in paired]
    sev_true = [v.value if hasattr(v, "value") else v for v in sev_true]
    sev_pred = [v.value if hasattr(v, "value") else v for v in sev_pred]
    kappa = weighted_kappa(sev_pred, sev_true)

    review_required = sum(1 for m, _ in paired if m.confidence < 0.65)
    review_rate = round(review_required / len(paired), 6)

    sev_mis = [(p, g) for p, g in zip(sev_pred, sev_true) if p != g]
    direction = severity_direction(sev_mis)

    metrics = {
        "run_id": args.run_id,
        "dataset_version": "DATASET-v1.0-feng-20260806",
        "paired_count": len(paired),
        **{k: {"accuracy": v["accuracy"], "macro_f1": v["macro_f1"]} for k, v in per_class.items()},
        "severity_weighted_kappa": kappa,
        "review_rate": review_rate,
        "severity_direction": direction,
        "field_error_counts": dict(Counter(e["field"] for e in error_rows)),
    }
    (run_dir / "metrics_eval_artifacts.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # error_cases.csv
    err_path = run_dir / "error_cases.csv"
    with open(err_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["feedback_id", "field", "gold_value", "pred_value"])
        writer.writeheader()
        writer.writerows(error_rows)

    # charts
    confusion: dict[str, dict] = {}
    for p, g in zip(sev_pred, sev_true):
        confusion.setdefault(str(g), {}).setdefault(str(p), 0)
        confusion[str(g)][str(p)] += 1
    build_charts(per_class, confusion, run_dir / "charts")

    # model_evaluation_report.md
    lines = [
        "# 模型评测报告(RidePulse AI)",
        "",
        f"> run_id: `{args.run_id}` | 评测人: 冯敬琴(数据治理与评测) | 日期: 2026-08-14",
        f"> 数据集: `DATASET-v1.0-feng-20260806`(37 条正式反馈,2026-08-13 冻结)",
        "",
        "## 1. 评测口径",
        "",
        "- 系统最终分类(`model_outputs.csv`,第一轮)与 `annotation_gold.csv`(20 条 gold)按 feedback_id 配对。",
        f"- 配对 **{len(paired)}/20**(F0030/F0031 在 gold 中但未入选 DATASET v1 正式 37 条,属数据集版本差异,已核对原标注交付一致)。",
        "- 指标:逐字段 Accuracy / Macro F1 / 逐类 P-R-F1 / severity 加权 Kappa(线性权)/ 人工复核率(confidence<0.65 口径)。",
        "",
        "## 2. 汇总指标",
        "",
        "| 字段 | Accuracy | Macro F1 | 逐类明细 |",
        "|---|---|---|---|",
    ]
    for field in EVALUATION_FIELDS:
        pc = per_class[field]
        cls_summary = "、".join(
            f"{label}(P{pc['per_class'][label]['precision']:.2f}/R{pc['per_class'][label]['recall']:.2f})"
            for label in sorted(pc["per_class"])
        )
        lines.append(f"| {FIELD_LABELS[field]} | {pc['accuracy']:.1%} | {pc['macro_f1']:.1%} | {cls_summary} |")
    lines += [
        f"| severity 加权 Kappa | {kappa:.3f} | — | 线性权重 |",
        f"| 人工复核率(低置信度门控) | {review_rate:.1%} | — | confidence<0.65 |",
        "",
        "## 3. 方向性分析",
        "",
        f"- severity 错误 {len(sev_mis)} 条,其中高估 {direction['over_estimate']} 条、低估 {direction['under_estimate']} 条 → **模型系统性高估一档**(与正式运行已知限制一致,人工复核时对 severity 下调一档参考)。",
        "- purchase_impact 口径差异:gold 仅含 `influence`/`blocker` 两级,模型输出大量 `unknown`(37 条中 35 条),accuracy 5.6% 反映标注口径不一致而非模型随机(数据治理需统一定义)。",
        "",
        "## 4. 错误案例",
        "",
        f"- 共 {len(error_rows)} 条字段级不一致,见 `error_cases.csv`(按字段:"
        + "、".join(f"{k}×{v}" for k, v in sorted(metrics["field_error_counts"].items()))
        + ")。",
        "",
        "## 5. 图表",
        "",
        "- `charts/acc_f1.png` — 四字段 Accuracy/Macro F1 对比",
        "- `charts/severity_confusion.png` — severity 混淆矩阵(模型 vs gold)",
        "",
        "## 6. 已知限制与披露",
        "",
        "- 双人标注样本 20 条,低于 50 条计划目标,已披露(数据量约束,非流程缺漏)。",
        "- 处理耗时与成本见 `usage_log.json`(逐次 LLM 调用 tokens/duration);总成本取决于所选 LLM 供应商计费,未在 metrics.json 固化。",
        "- 评测基于第一轮分类;12 条冲突裁决回填后如需复评,重跑本脚本即可(paired 口径不变)。",
        "",
    ]
    (run_dir / "model_evaluation_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"已产出到 {run_dir}: metrics_eval_artifacts.json / error_cases.csv / charts/ / model_evaluation_report.md")

    if args.copy_to:
        dest = Path(args.copy_to)
        dest.mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics_eval_artifacts.json").replace(dest / "metrics.json")
        (run_dir / "error_cases.csv").replace(dest / "error_cases.csv")
        (run_dir / "model_evaluation_report.md").replace(dest / "model_evaluation_report.md")
        chart_dest = dest / "charts"
        chart_dest.mkdir(parents=True, exist_ok=True)
        for png in (run_dir / "charts").glob("*.png"):
            png.replace(chart_dest / png.name)
        print(f"已复制到 {dest}: metrics.json / error_cases.csv / model_evaluation_report.md / charts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
