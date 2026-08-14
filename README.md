# RidePulse AI 🌐🚴

## 全球骑行用户需求雷达

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Competition](https://img.shields.io/badge/2026%20AI%E5%85%88%E9%94%8B%E5%A4%A7%E8%B5%9B-%E8%BF%88%E9%87%91%E7%A7%91%E6%8A%80%E5%91%BD%E9%A2%98-orange)](https://www.magene.cn)

> **将全球、多语言、碎片化的骑行用户声音，转化为可追溯、可排序、可行动的产品机会。**

---

## 📌 项目状态：完整流水线已跑通

系统已完成端到端验证（正式运行 `RUN-20260813-211103`，2026-08-13），不是概念演示：

| 环节 | 结果 |
|---|---|
| 输入 | 37 条真实反馈（DATASET v1，2026-08-13 冻结；12 平台 / 24 来源页；中文 5 条 / 英文 32 条） |
| 分类 | LLM 首轮分类 37/37（deepseek-v4-flash），JSON Schema 约束输出 |
| 独立复判 | 第二模型全量复判 37/37（deepseek-v4-pro）；完全一致 21 条，字段级冲突 16 条 |
| 人工仲裁 | 12 条冲突全部人工裁决，逐条依据留档（`adjudication_record.csv`） |
| 语义聚类 | 21 个需求簇，覆盖全部样本，跨平台/跨语言合并 |
| 证据卡 | 21 张（EC-2026-0001 ~ EC-2026-0021），含问题陈述/根因假设/建议动作/证据 URL |
| 评测 | 与双人标注 gold 配对 18/20：theme_primary 准确率 88.9% / macro-F1 75.4% |
| 测试 | **192 项自动化测试全部通过** |

完整结果、指标口径与已知限制见 [`03_system_results_m4.md`](03_system_results_m4.md) 与 `output/RUN-20260813-211103/`（模型输出、复判、裁决记录、聚类、优先级、证据卡、评测报告与图表，均已随仓库提交）。

---

## 📖 项目背景

迈金科技（Magene）是中国领先的智能骑行科技企业，旗下包含 Magene、Onelap（顽鹿）、EXAR 等品牌，产品覆盖 GPS 智能码表、功率计、智能骑行台和传感器（据迈金官方公开资料，服务全球 100 多个国家和地区）。

用户反馈分散在 App Store、Google Play、论坛、社交媒体与客服工单中——海量、多语言、碎片化。企业不缺数据，缺的是把碎片化声音从"结果语言"转化为"根因假设"、形成可追溯产品决策证据的能力。2025 年 Garmin 缓存文件缺陷致数千台 Edge 设备变砖、2024 年 Strava API 限令破坏第三方应用集成——行业标杆同样在"用户声音失察"上付出代价，这正是 RidePulse AI 要解决的问题。

---

## 🏗️ 系统架构（已实现）

```
采集 → 标准化 → 分类 → 独立复判 → 人工仲裁 → 聚类 → 优先级评分 → 证据卡
```

| 阶段 | 实现 | 说明 |
|------|------|------|
| 采集 | ✅ | 公开合规渠道（应用商店 RSS / 论坛 / 媒体），保留 URL / 时间 / 平台 / 语言 |
| 标准化 | ✅ | 字段校验、脱敏、翻译、来源台账，非法记录拒收 |
| 分类 | ✅ | LLM 首轮分类：情感 / 主题 / 场景 / 严重度 / 需求五分类 / JTBD / 购买影响等，低置信度字段标记待复核 |
| 独立复判 | ✅ | 第二模型全量复判，字段级冲突检测；冲突进人工队列，**不自动输出确定结论** |
| 人工仲裁 | ✅ | 冲突逐条裁决并留档，可审计 |
| 聚类 | ✅ | 多语言向量嵌入（本地 paraphrase-multilingual-MiniLM，384 维）+ 主题分桶 + 确定性凝聚聚类（cosine） |
| 优先级评分 | ✅ | 纯代码六维加权（证据 15 + 复现 20 + 频率 15 + 严重度 20 + 可执行 15 + 购买 15），**模型不参与评分** |
| 证据卡 | ✅ | LLM 生成 + 代码校验；强制引用原文 ID / URL / 时间，不可回链自动作废 |

### 核心设计原则

- ✅ **证据链驱动**：每条洞察强制引用原文 ID + URL + 时间，不可回链自动作废
- ✅ **模型分层**：代码能确定的不用模型，统计能聚类的不用推理；评分公式 100% 代码化
- ✅ **双模型复判 + 人工仲裁**：首轮与复判冲突不自动采信，进人工队列
- ✅ **根因假设而非定论**：模型只提假设，不替代产品经理确认
- ✅ **模型无关架构**：分类 / 复判 / 证据卡均不绑定特定模型供应商，可灵活替换（Embedding 支持本地 / API 双模式，可切换 BGE-M3 等）

---

## 🧪 快速开始

```bash
# 安装
pip install -e .

# 环境变量（.env，不提交）：LLM_BASE_URL / LLM_API_KEY / LLM_PRIMARY_MODEL / LLM_REVIEW_MODEL / EMBEDDING_MODE=local

# 运行完整流水线（需配置 LLM；无密钥可用 --offline 演示基线）
python -m ridepulse.cli run --input data/verified/feedback_verified.csv

# 评测复现（与 gold 标注比对，复现 metrics.json）
python -m ridepulse.cli evaluate --run-id RUN-20260813-211103 --gold data/verified/annotation_gold.csv

# Streamlit 工作台（运行概览 / 需求簇 / 证据卡 / 评测 / 人工复核 5 个页面）
streamlit run app.py

# 全量测试
pytest   # 192 passed
```

> 正式运行产物已随仓库提交：`output/RUN-20260813-211103/`（`model_outputs.csv` / `review_outputs.csv` / `human_final_outputs.csv` / `cluster_results.csv` / `priority_scores.csv` / `evidence_cards.json` / `metrics.json` / `error_cases.csv` / `charts/` 等）。

---

## 📁 仓库结构

```
ridepulse-ai/
├── README.md                              # 本文件
├── 03_system_results_m4.md                # M4 系统结果交付说明（配置/统计/评测/限制）
├── DATA_CONTRACT_v1.md / .json            # 分类标签体系与字段级数据契约
├── src/ridepulse/                         # 核心包
│   ├── pipeline.py                        # 全链路编排
│   ├── classify.py / review.py            # 双模型分类与独立复判
│   ├── clustering.py / embedding.py       # 主题分桶聚类与多语言向量嵌入
│   ├── scoring.py                         # 六维优先级评分（纯代码）
│   ├── evidence.py                        # 证据卡生成与校验
│   ├── evaluation.py                      # 评测指标（Accuracy/F1/Kappa）
│   ├── dedup.py / normalize.py / ingest.py / validation.py
│   ├── database.py / delivery.py / feishu_client.py
│   ├── collectors/                        # 公开连接器（App Store RSS 等）
│   ├── llm_client.py / config.py / models.py
│   └── cli.py                             # validate / collect / run / resume / evaluate / push-feishu
├── app.py                                 # Streamlit 工作台（5 个页面）
├── data/
│   ├── classification_schema.json         # 分类 JSON Schema v1.0
│   └── verified/                          # DATASET v1（已冻结）
│       ├── feedback_verified.csv          # 37 条正式反馈（脱敏）
│       ├── source_ledger_verified.csv     # 来源台账（URL 可回链）
│       ├── annotation_gold.csv            # 双人标注 gold（评测用）
│       ├── DATASET_V1_FROZEN.md           # 冻结说明
│       ├── dataset_summary.md             # 数据统计
│       └── data_quality_report.md         # 数据质量报告
├── prompts/
│   ├── classify_v1.md                     # 分类 Prompt
│   └── review_v1.md                       # 复判 Prompt
├── docs/
│   ├── 01_problem_analysis.md             # 命题分析与行业洞察
│   ├── 02_solution_design.md              # 技术方案设计
│   └── 04_references.txt                  # 参考资料清单
├── scripts/                               # 评测落盘 / 裁决回填 / PDF 构建 / Excel 导出
├── tests/                                 # 192 项测试
├── output/RUN-20260813-211103/            # M4 正式运行全部产物
└── team_outputs/liang/                    # 业务盲审与事实核验交付（M5）
```

---

## 📊 评测与已知限制（诚实披露）

与 20 条双人标注 gold 比对（配对 18/20，`F0030`/`F0031` 属数据集版本差异）：

| 指标 | 值 |
|---|---|
| theme_primary accuracy / macro-F1 | 88.9% / 75.4% |
| need_type accuracy | 61.1% |
| severity accuracy | 50.0%（加权 Kappa 0.375） |
| purchase_impact accuracy | 5.6%（标注口径差异，见下） |
| 人工复核率 | 55.6%（低置信度与冲突字段进入人工队列） |

- **severity 系统性高估一档**：9/9 错误均为模型比 gold 高一级，无低估——已写入人工复核规则，对严重度建议下调一档复核
- **purchase_impact 口径差异**：gold 仅含 `influence`/`blocker` 两级，模型输出含 `unknown`——是标注口径不一致而非随机错误，数据治理需统一定义
- **复核率 55.6% 是门控机制在设计上生效**：双模型复判 + 人工仲裁保证"不确定即送审"，不追求"低复核率"的表面指标

---

## 👥 团队

| 角色 | 姓名 | 学校 | 核心能力 |
|------|------|------|---------|
| 队长 / 系统与总集成 | 张中宝 | 山东外国语职业技术大学 · 软件工程技术 | AI 架构、数学建模、软件项目 |
| 来源核验与业务审查 | 李昂 | 澳门科技大学 · 工商管理 | 多年骑行经验、产品商业化、竞品研究 |
| 数据治理与评测 | 冯敬琴 | 四川师范大学 · 地理信息科学 | GIS、Python 数据分析、可视化 |

三人背景构成"行业判断—数据验证—产品落地"的闭环：队长负责系统架构与总集成，骑行负责人提供垂直领域的真实体感与业务审查，数据负责人保证标注质量与评测严谨性。

---

## 📚 参考资料

- [`docs/01_problem_analysis.md`](docs/01_problem_analysis.md) — 命题分析与行业洞察
- [`docs/02_solution_design.md`](docs/02_solution_design.md) — 技术方案设计
- [`docs/04_references.txt`](docs/04_references.txt) — 完整参考资料清单（PeopleForBikes / road.cc / The Verge / BGE-M3 论文等）
- 完整来源台账（S01-S20，含原文摘录与访问日期）见 `data/verified/source_ledger_verified.csv`

---

## 📄 许可证与竞赛说明

本项目为 2026 AI先锋未来人才大赛参赛作品（迈金科技命题）。代码部分采用 MIT 许可证。原始敏感数据（`data/raw/`）与密钥（`.env`）不提交；DATASET v1 正式数据已脱敏并随仓库提供。

---

*RidePulse AI — 让每一个骑行用户的声音都能被听见、被追溯、被行动。*
