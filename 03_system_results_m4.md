# M4 系统结果交付 — RidePulse AI

> 交付人: 张中宝(队长) | 交付日期: 2026-08-13 | 对应文档16 节点 M4(系统结果)

## 1. 运行配置

| 项 | 值 |
|---|---|
| run_id | `RUN-20260813-211103` |
| 数据集 | DATASET v1(37 条正式反馈,2026-08-13 冻结) |
| 分类模型 | `deepseek-v4-flash`(第一轮,37/37) |
| 复判模型 | `deepseek-v4-pro`(独立第二轮,37/37) |
| 复判机制 | 双模型独立复判 → compare_and_judge 冲突检测 |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2`(384 维,local 模式) |
| 评分 | 纯代码计算(证据15 + 复现20 + 频率15 + 严重度20 + 可执行15 + 购买15),模型不参与 |

## 2. 结果统计

- 输入 37 → 有效 37 → 去重后 37(无重复)
- 分类 37/37(冲突 0)
- **双模型复判:一致 21 条,字段冲突 16 条**
- 人工复核队列:12 条 pending(冲突字段需裁决),25 条 approved
- 语义聚类:21 个需求簇(覆盖 37 条,跨平台/跨语言合并)
- 证据卡:21 张(`EC-2026-0001` ~ `EC-2026-0021`,全部 LLM 生成 + 代码校验)

## 3. 优先级分布(代码计算,满分 100)

| 级别 | 数量 | 分数区间 |
|---|---|---|
| P0(≥80) | 0 | — |
| P1(65-79) | 1 | 68 |
| P2(45-64) | 7 | 45-61 |
| P3(<45) | 13 | 18-37 |

最高分簇:设备与 App 同步异常(61 分,P2)——4 条证据,连接与同步类问题为当前最显著需求。

## 4. 评测结果(与 20 条 gold 标注比对)

配对 18/20(`F0030`/`F0031` 在 gold 标注中但未入选 DATASET v1 正式 37 条,已核对冯敬琴原始交付一致,属数据集版本差异):

| 指标 | 值 |
|---|---|
| theme_primary accuracy | 88.9% |
| theme_primary macro-F1 | 75.4% |
| need_type accuracy | 61.1% |
| severity accuracy | 50.0% |
| severity weighted kappa | 0.375 |
| purchase_impact accuracy | 5.6% |
| 人工复核率 | 55.6% |

完整指标见 `output/RUN-20260813-211103/metrics.json`。

## 5. 已知限制与人工复核指引

1. **severity 系统性高估一级**:9/9 错误均为模型比 gold 高一级(S1→S2、S2→S3、S3→S4),无低估。人工复核时对严重度建议下调一档。
2. **purchase_impact 口径差异**:gold 标注仅含 `influence`/`blocker` 两级,模型输出 17 条 `unknown`。准确率 5.6% 不代表模型随机错,而是标注口径不一致(数据治理需统一定义)。
3. **glm-5.2 网关 401**:网关 `api-share` 未对该 key 开放 `glm-5.2`,复判改用 `deepseek-v4-pro`(与主模型不同,双模型独立性保持)。
4. **人工复核队列**:`human_final_outputs.csv` 12 条 pending 需裁决(16 条冲突中 4 条裁决后与主分类一致)。

## 6. 产物清单(`output/RUN-20260813-211103/`)

- `model_outputs.csv` — 37 条第一轮分类
- `review_outputs.csv` — 37 条第二轮复判 + 冲突标记
- `human_final_outputs.csv` — 最终输出与人工复核队列
- `cluster_results.csv` — 21 个需求簇及成员
- `priority_scores.csv` — 逐簇评分明细
- `evidence_cards.json` / `evidence_cards.md` — 21 张证据卡
- `metrics.json` — 评测指标
- `run_report.md` / `run_summary.json` — 运行报告
