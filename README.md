# RidePulse AI 🌐🚴

## 全球骑行用户需求雷达

**简体中文 | [English](README.en.md)**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-203%20passed-brightgreen)](tests/)
[![Models](https://img.shields.io/badge/LLM-GPT--6%20family-412991)](https://platform.openai.com/docs/models)
[![Competition](https://img.shields.io/badge/2026%20AI%E5%85%88%E9%94%8B%E5%A4%A7%E8%B5%9B-%E8%BF%88%E9%87%91%E7%A7%91%E6%8A%80%E5%91%BD%E9%A2%98-orange)](https://www.magene.cn)

> **将全球、多语言、碎片化的骑行用户声音，转化为可追溯、可排序、可行动的产品机会。**

> **English summary** — RidePulse AI turns scattered, multilingual cycling user reviews into traceable, rankable product opportunities. The pipeline runs collect → normalize → classify → independent review (a **different** model, blind to the first pass) → human adjudication → cluster → code-only priority scoring → evidence cards. Every insight must cite an original record ID, URL and timestamp; a card that cannot be traced back is voided automatically. Runs on the OpenAI **GPT-6 family** across three tiers (`gpt-6-luna` / `gpt-6-sol` / `gpt-6-astra`). 203 tests passing, weekly CI automation live. → **[Full English README](README.en.md)**

---

## 📌 项目状态：完整流水线已跑通

系统已完成端到端验证（正式运行 `RUN-20260813-211103`，2026-08-13），不是概念演示：

| 环节 | 结果 |
|---|---|
| 输入 | 37 条真实反馈（DATASET v1，2026-08-13 冻结；12 平台 / 24 来源页；中文 5 条 / 英文 32 条） |
| 分类 | LLM 首轮分类 37/37，JSON Schema 约束输出 |
| 独立复判 | 第二模型全量复判 37/37（与首轮不同模型，双模型独立）；完全一致 21 条，字段级冲突 16 条 |
| 人工仲裁 | 12 条冲突全部人工裁决，逐条依据留档（`adjudication_record.csv`） |
| 语义聚类 | 21 个需求簇，覆盖全部样本，跨平台/跨语言合并 |
| 证据卡 | 21 张（EC-2026-0001 ~ EC-2026-0021），含问题陈述/根因假设/建议动作/证据 URL |
| 评测 | 与双人标注 gold 配对 18/20：theme_primary 准确率 88.9% / macro-F1 75.4% |
| 测试 | **203 项自动化测试全部通过** |
| 模型层 | OpenAI **GPT-6 系列**三层分工：`gpt-6-luna` 分类 / `gpt-6-sol` 复判 / `gpt-6-astra` 证据卡（见 [模型接入](#-模型接入gpt-6-系列)） |
| 长期运转 | 周更自动流水线(GitHub Actions)已上线:每周一 02:37 自动采集→分类→复判→聚类→评分→证据卡,代码推送即运行,冲突自动开 issue,失败自动告警(见 `data/auto/README.md`) |

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
| 分类 | ✅ | `gpt-6-luna` 首轮分类：情感 / 主题 / 场景 / 严重度 / 需求五分类 / JTBD / 购买影响等，低置信度字段标记待复核 |
| 独立复判 | ✅ | `gpt-6-sol` 全量复判（与首轮不同模型），字段级冲突检测；冲突进人工队列，**不自动输出确定结论** |
| 人工仲裁 | ✅ | 冲突逐条裁决并留档，可审计 |
| 聚类 | ✅ | 多语言向量嵌入（默认 `text-embedding-3-large` 3072 维；可切本地 paraphrase-multilingual-MiniLM）+ 主题分桶 + 确定性凝聚聚类（cosine） |
| 优先级评分 | ✅ | 纯代码六维加权（证据 15 + 复现 20 + 频率 15 + 严重度 20 + 可执行 15 + 购买 15），**模型不参与评分** |
| 证据卡 | ✅ | `gpt-6-astra` 生成 + 代码校验；强制引用原文 ID / URL / 时间，不可回链自动作废 |

### 核心设计原则

- ✅ **证据链驱动**：每条洞察强制引用原文 ID + URL + 时间，不可回链自动作废
- ✅ **模型分层**：代码能确定的不用模型，统计能聚类的不用推理；评分公式 100% 代码化
- ✅ **双模型复判 + 人工仲裁**：首轮与复判冲突不自动采信，进人工队列
- ✅ **根因假设而非定论**：模型只提假设，不替代产品经理确认
- ✅ **按任务配档而非统一顶配**：分类跑量用低成本档、复判要独立性用通用档、证据卡要长上下文综合用旗舰档（详见下节）
- ✅ **端点可替换**：三层模型名与 Base URL 全部走环境变量，换成任意 OpenAI 兼容端点只需改配置

---

## 🤖 模型接入（GPT-6 系列）

分类、复判、证据卡三步都调 OpenAI GPT-6，但**不是同一个档位**——按任务特性分三层，成本与能力对齐：

> **迁移说明**：早期版本的周更流水线跑在国产模型（MiniMax M3）上，全链路能跑通，但实测在跨语言语义边界判定与结构化输出稳定性上不如 GPT-6 系列——自适应思考默认开启时单条分类耗时 10.5s（关闭后 2.2s），输出还带 `<think>` 前缀需要额外剥离。默认模型因此整体迁到 GPT-6。

| 环节 | 默认模型 | 推理强度 | 为什么这么配 |
|---|---|---|---|
| 首轮分类 | `gpt-6-luna` | `low` | 单条调用、输出结构固定、一轮跑几十到上百次，量大但对单次推理深度要求不高 |
| 独立复判 | `gpt-6-sol` | `medium` | 复判的价值在"独立第二意见"，必须换模型；同时要能识别首轮的边界误判 |
| 证据卡 | `gpt-6-astra` | `high` | 一个簇要综合多条跨语言证据并严格受引用约束，105 万 token 上下文与更强综合能力直接决定卡片质量 |

**GPT-6 参数适配**（已内建，不需要使用者关心）：GPT-6 起采样参数 `temperature` / `top_p` 被移除，继续传会直接报错；推理深度改由 `reasoning_effort` 控制，合法值为 `low` / `medium` / `high` / `xhigh` / `max`，`none` 与 `minimal` 已取消。客户端按模型名自动判定能力：GPT-6 不发采样参数、把非法推理档位收敛到 `low`，并在服务端报"参数不支持"时剔除该参数重试一次，不会因为换模型把整条流水线跑挂。

每次运行的 `run_report.md` 与 `usage_log.json` 都会记下实际请求模型、回包模型、推理强度与思考 token 数——模型回包与请求不一致（端点静默映射）会被单独记一条告警。

Embedding 默认走同一端点的 `text-embedding-3-large`（3072 维）；CI 周更流水线用本地多语言模型，不额外消耗额度。

---

## 🧪 快速开始

```bash
# 安装
pip install -e .

# 环境变量（.env，不提交；模板见 .env.example）
#   OPENAI_API_KEY=sk-...            # 唯一必填项（也接受 LLM_API_KEY）
#   LLM_PRIMARY_MODEL=gpt-6-luna     # 首轮分类
#   LLM_REVIEW_MODEL=gpt-6-sol       # 独立复判（需与分类不同模型）
#   LLM_EVIDENCE_MODEL=gpt-6-astra   # 证据卡
#   这三个变量不写即用上述默认值；LLM_BASE_URL 默认 https://api.openai.com/v1

# 先确认接入是否通（--live 会真发一次最小请求，核对端点与回包模型名）
python -m ridepulse.cli check-llm --live

# 运行完整流水线（需配置 LLM；无密钥可用 --offline 演示基线）
python -m ridepulse.cli run --input data/verified/feedback_verified.csv

# 评测复现（与 gold 标注比对，复现 metrics.json）
python -m ridepulse.cli evaluate --run-id RUN-20260813-211103 --gold data/verified/annotation_gold.csv

# Streamlit 工作台（证据卡 / 运行概览 / 需求簇 / 评测 / 人工复核 5 个页面；侧边栏可切换数据版本）
streamlit run app.py

# 全量测试
pytest   # 203 passed
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
│   ├── verified/                          # DATASET v1（已冻结）
│   │   ├── feedback_verified.csv          # 37 条正式反馈（脱敏）
│   │   ├── source_ledger_verified.csv     # 来源台账（URL 可回链）
│   │   ├── annotation_gold.csv            # 双人标注 gold（评测用）
│   │   ├── DATASET_V1_FROZEN.md           # 冻结说明
│   │   ├── dataset_summary.md             # 数据统计
│   │   └── data_quality_report.md         # 数据质量报告
│   └── auto/                              # 周更自动流水线数据区（反馈池/游标/人工裁决）
├── prompts/
│   ├── classify_v1.md                     # 分类 Prompt
│   └── review_v1.md                       # 复判 Prompt
├── agents/                                # 提示词模板（understander / reviewer / governor）
├── docs/
│   ├── 01_problem_analysis.md             # 命题分析与行业洞察
│   ├── 02_solution_design.md              # 技术方案设计
│   └── 04_references.txt                  # 参考资料清单
├── scripts/                               # 周更编排 / 评测落盘 / 裁决回填 / PDF 构建 / Excel 导出
├── .github/workflows/weekly-pipeline.yml  # 周更自动流水线（定时 + push 触发）
├── tests/                                 # 203 项测试
├── output/RUN-20260813-211103/            # M4 正式运行全部产物
└── team_outputs/liang/                    # 业务审查交付（审查框架与模板：李昂；逐卡执行：队长）
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
| 来源核验与业务审查 | 李昂 | 澳门科技大学 · 工商管理 | 骑行爱好者视角、产品商业化、竞品研究 |
| 数据治理与评测 | 冯敬琴 | 四川师范大学 · 地理信息科学 | GIS、Python 数据分析、可视化 |

三人背景构成"行业判断—数据验证—产品落地"的闭环：队长负责系统架构与总集成，骑行负责人提供垂直领域视角与业务审查，数据负责人保证标注质量与评测严谨性。

---

## 📚 参考资料

- [`docs/01_problem_analysis.md`](docs/01_problem_analysis.md) — 命题分析与行业洞察
- [`docs/02_solution_design.md`](docs/02_solution_design.md) — 技术方案设计
- [`docs/04_references.txt`](docs/04_references.txt) — 完整参考资料清单（PeopleForBikes / road.cc / The Verge / BGE-M3 论文等）
- 完整来源台账（S01-S20，含原文摘录与访问日期）见 `data/verified/source_ledger_verified.csv`

---

## 📄 许可证与竞赛说明

本项目为 2026 AI先锋未来人才大赛参赛作品（迈金科技命题）。代码部分采用 MIT 许可证。原始敏感数据（`data/raw/`）与密钥（`.env`）不提交；DATASET v1 正式数据已脱敏并随仓库提供。

> ⚠️ **安全状态**：本项目尚未经过正式安全审查。核心数据流是「不可信的外部评论文本 → LLM → 下游决策」，提示注入是真实攻击面。威胁模型与待审查范围见 [`SECURITY.md`](SECURITY.md)。

---

*RidePulse AI — 让每一个骑行用户的声音都能被听见、被追溯、被行动。*
