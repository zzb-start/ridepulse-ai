# DATASET v1 冻结声明

> 冻结时间: 2026-08-13
> 冻结人: 张中宝(队长), 数据来源: 冯敬琴数据治理交付包(2026-08-06)
> 状态: 数据冻结(DATASET v1)

## 冻结文件

| 文件 | 内容 | 记录数 | SHA-256(前16位) |
|---|---|---|---|
| `feedback_verified.csv` | 已核验反馈主数据集(含标注列) | 37 | `02d8fceed71a4e26` |
| `source_ledger_verified.csv` | 来源台账 | 24 | `bc0500ca6ebe7033` |
| `annotation_gold.csv` | 双人仲裁金标(评测用) | 20 | `bafc79a37498f454` |
| `data_quality_report.md` | 数据质量报告(冯敬琴) | — | — |
| `dataset_summary.md` | 数据集摘要(冯敬琴) | — | — |

## 校验结论(2026-08-13, `cli validate`)

- `feedback_verified.csv`: **37 行全部通过字段级校验** (valid=37, invalid=0)
- 21 条 evidence_status 非 VERIFIED(部分核验)——保留状态标记,评分中按证据质量规则处理
- sentiment/theme_primary/severity 等列为数据标注列,由数据治理产出;
  离线基线模式(`offline_mode=True`)读取这些列,输出标记为
  `annotation-gold-v1 / offline-baseline`,**不用于比赛模型指标**

## 冻结后规则

1. 本目录文件为 DATASET v1,冻结后**不得修改**;如有修正,复制为新版本
   (如 `feedback_verified_v2.csv`)并更新本声明
2. Pipeline 运行的输入以本目录为准
3. 李昂的核验工作(来源核验/业务复核)以本数据为对象,不反向修改数据
