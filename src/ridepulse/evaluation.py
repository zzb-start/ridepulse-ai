"""评测模块 — 模型与双人标注的对比指标。

指标：
- 每个分类字段准确率 / Macro F1
- severity 加权 Kappa
- 低置信度召回率 / 冲突门控召回率
- 人工复核率
"""

from __future__ import annotations

from ridepulse.models import ClassificationResult


def cohens_kappa(a: list, b: list) -> float:
    """Cohen's Kappa（分类一致性）。

    kappa = (po - pe) / (1 - pe)；pe == 1（完全一致）时返回 1.0。
    """
    if len(a) != len(b):
        raise ValueError("两个标注序列长度不一致")
    n = len(a)
    if n == 0:
        return 0.0

    labels = sorted({str(x) for x in set(a) | set(b)})
    if len(labels) <= 1:
        return 1.0 if n > 0 else 0.0

    observed = sum(1 for x, y in zip(a, b) if x == y) / n

    count_a = {label: 0 for label in labels}
    count_b = {label: 0 for label in labels}
    for x, y in zip(a, b):
        count_a[str(x)] += 1
        count_b[str(y)] += 1
    expected = sum(
        (count_a[label] / n) * (count_b[label] / n) for label in labels
    )

    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 6)


def _linear_weight(i: int, j: int, k: int) -> float:
    """线性权重: w = 1 - |i-j| / (k-1)。"""
    if k <= 1:
        return 1.0
    return 1.0 - abs(i - j) / (k - 1)


def weighted_kappa(a: list, b: list, weights: str = "linear") -> float:
    """加权 Kappa（用于 severity 等有序分类）。

    类别按值排序后计算；要求 a/b 中的值可排序（如 "S1".."S5" 或 1..5）。
    """
    if len(a) != len(b):
        raise ValueError("两个标注序列长度不一致")
    n = len(a)
    if n == 0:
        return 0.0

    categories = sorted({str(x) for x in set(a) | set(b)})
    if len(categories) <= 1:
        return 1.0

    index = {label: i for i, label in enumerate(categories)}
    k = len(categories)

    def weight(i: int, j: int) -> float:
        if weights == "linear":
            return _linear_weight(i, j, k)
        if weights == "quadratic":
            diff = abs(i - j) / (k - 1)
            return 1.0 - diff * diff
        raise ValueError(f"未知权重方式: {weights}（可选 linear / quadratic）")

    observed = 0.0
    for x, y in zip(a, b):
        observed += weight(index[str(x)], index[str(y)])
    observed /= n

    count_a = {label: 0 for label in categories}
    count_b = {label: 0 for label in categories}
    for x, y in zip(a, b):
        count_a[str(x)] += 1
        count_b[str(y)] += 1

    expected = 0.0
    for label_x in categories:
        for label_y in categories:
            prob = (count_a[label_x] / n) * (count_b[label_y] / n)
            expected += prob * weight(index[label_x], index[label_y])

    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 6)


# 评测字段：{模型输出字段: gold 字段}
EVALUATION_FIELDS = {
    "theme_primary": "theme_primary",
    "need_type": "need_type",
    "severity": "severity",
    "purchase_impact": "purchase_impact",
}


def evaluate_model(model_outputs: list[ClassificationResult], gold: list[dict]) -> dict:
    """模型输出 vs gold 标注评测。

    model_outputs: ClassificationResult 列表
    gold: 每项含 feedback_id 与 theme_primary/need_type/severity/purchase_impact 字段
    """
    gold_by_id = {row["feedback_id"]: row for row in gold}
    paired = [
        (result, gold_by_id[result.feedback_id])
        for result in model_outputs
        if result.feedback_id in gold_by_id
    ]
    if not paired:
        return {"error": "model_outputs 与 gold 无交集 feedback_id", "paired_count": 0}

    from sklearn.metrics import accuracy_score, f1_score

    result: dict = {"paired_count": len(paired)}
    for model_field, gold_field in EVALUATION_FIELDS.items():
        y_true = [row[gold_field] for _, row in paired]
        y_pred = [getattr(result_model, model_field) for result_model, _ in paired]
        # Enum -> 字符串值
        y_true = [v.value if hasattr(v, "value") else v for v in y_true]
        y_pred = [v.value if hasattr(v, "value") else v for v in y_pred]
        result[model_field] = {
            "accuracy": round(accuracy_score(y_true, y_pred), 6),
            "macro_f1": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 6),
        }

    severity_true = [row["severity"] for _, row in paired]
    severity_pred = [getattr(m, "severity") for m, _ in paired]
    severity_true = [v.value if hasattr(v, "value") else v for v in severity_true]
    severity_pred = [v.value if hasattr(v, "value") else v for v in severity_pred]
    result["severity_weighted_kappa"] = weighted_kappa(severity_pred, severity_true)

    # 人工复核率：模型认为需复核的比例（按 gold 样本口径）
    review_required = sum(1 for m, _ in paired if m.confidence < 0.65)
    result["review_rate"] = round(review_required / len(paired), 6)
    return result
