# 模型评测报告(RidePulse AI — M5 补全版)

> run_id: `RUN-20260813-211103` | 评测人: 数据治理(原冯敬琴职责,队长代执行) | 日期: 2026-08-14
> 数据集: `DATASET-v1.0-feng-20260806`(37 条正式反馈,2026-08-13 冻结)

## 1. 评测口径

- 系统最终分类(`model_outputs.csv`,第一轮)与 `annotation_gold.csv`(20 条 gold)按 feedback_id 配对。
- 配对 **18/20**(F0030/F0031 在 gold 中但未入选 DATASET v1 正式 37 条,属数据集版本差异,已核对原标注交付一致)。
- 指标:逐字段 Accuracy / Macro F1 / 逐类 P-R-F1 / severity 加权 Kappa(线性权)/ 人工复核率(confidence<0.65 口径)。

## 2. 汇总指标

| 字段 | Accuracy | Macro F1 | 逐类明细 |
|---|---|---|---|
| Theme (primary) | 88.9% | 75.4% | connectivity(P1.00/R1.00)、data_accuracy(P1.00/R1.00)、display_ux(P0.00/R0.00)、firmware(P1.00/R0.50)、hardware(P0.75/R1.00)、navigation(P1.00/R1.00) |
| Need type | 61.1% | 58.0% | feature_request(P1.00/R1.00)、incidental_failure(P0.00/R0.00)、real_need(P0.59/R1.00) |
| Severity | 50.0% | 37.2% | S1(P0.00/R0.00)、S2(P0.60/R0.38)、S3(P0.56/R0.71)、S4(P0.25/R1.00) |
| Purchase impact | 5.6% | 6.1% | blocker(P1.00/R0.10)、influence(P0.00/R0.00)、unknown(P0.00/R0.00) |
| severity 加权 Kappa | 0.375 | — | 线性权重 |
| 人工复核率(低置信度门控) | 55.6% | — | confidence<0.65 |

## 3. 方向性分析

- severity 错误 9 条,其中高估 9 条、低估 0 条 → **模型系统性高估一档**(与 M4 已知限制一致,人工复核时对 severity 下调一档参考)。
- purchase_impact 口径差异:gold 仅含 `influence`/`blocker` 两级,模型输出大量 `unknown`(37 条中 35 条),accuracy 5.6% 反映标注口径不一致而非模型随机(数据治理需统一定义)。

## 4. 错误案例

- 共 35 条字段级不一致,见 `error_cases.csv`(按字段:need_type×7、purchase_impact×17、severity×9、theme_primary×2)。

## 5. 图表

- `charts/acc_f1.png` — 四字段 Accuracy/Macro F1 对比
- `charts/severity_confusion.png` — severity 混淆矩阵(模型 vs gold)

## 6. 已知限制与披露

- 双人标注样本 20 条,低于 50 条计划目标,已披露(数据量约束,非流程缺漏)。
- 处理耗时与成本见 `usage_log.json`(逐次 LLM 调用 tokens/duration);总成本取决于所选 LLM 供应商计费,未在 metrics.json 固化。
- 评测基于第一轮分类;12 条冲突裁决回填后如需复评,重跑本脚本即可(paired 口径不变)。
