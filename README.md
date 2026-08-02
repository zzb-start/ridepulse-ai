# RidePulse AI 🌐🚴

## 全球骑行用户需求雷达

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Competition](https://img.shields.io/badge/2026%20AI%E5%85%88%E9%94%8B%E5%A4%A7%E8%B5%9B-%E8%BF%88%E9%87%91%E7%A7%91%E6%8A%80%E5%91%BD%E9%A2%98-orange)](https://www.magene.cn)

> **将全球、多语言、碎片化的骑行用户声音，转化为可追溯、可排序、可行动的产品机会。**

---

## 📖 项目背景

迈金科技（Magene）是中国领先的智能骑行科技企业，旗下包含Magene、Onelap（顽鹿）、EXAR等品牌，产品覆盖GPS智能码表、功率计、智能骑行台和传感器，服务全球100多个国家和地区。

用户反馈分散在App Store、Google Play、Reddit、电商平台、骑行社区和客服工单中——数量庞大、多语言、碎片化。RidePulse AI拟借助AI技术，实现用户反馈收集、分析、归类及洞察输出的智能化升级。

---

## 🎯 方案概述

**RidePulse AI** 拟实现一套Agent流水线系统，将碎片化用户声音转化为可追溯的需求证据卡：

```
采集 → 治理 → 理解 → 发现 → 证据审校 → 交付闭环
```

### 核心理念

- ❌ 不是"评论情绪摘要"
- ❌ 不是"把数据丢给ChatGPT"
- ✅ **证据链驱动**：每条洞察强制引用原文ID + URL + 时间
- ✅ **模型分层**：代码能确定的不用模型，统计能聚类的不用推理
- ✅ **实验闭环**：从用户声音到产品待办，再到结果验证回流

---

## 🏗️ 系统架构（方案设计阶段）

| Agent | 职责 | 技术选型（拟采用） |
|-------|------|---------|
| ① 采集Agent | 连接多平台数据源，保留URL/时间/SKU/版本 | Python + API/HTML解析 |
| ② 治理Agent | MinHash去重 + BGE-M3语义去重 + 语言识别 + 垃圾过滤 | MinHash + BGE-M3 + langID |
| ③ 理解Agent | 轻量模型 + JSON Schema → 情感/主题/场景/严重度/JTBD | 豆包/通义（模型可替换） |
| ④ 发现Agent | BGE-M3向量 + HDBSCAN聚类 + 版本/时间异常检测 | BGE-M3 + UMAP + HDBSCAN |
| ⑤ 证据审校Agent | 六维加权评分 + 高推理模型生成证据卡（强制引用ID） | Claude/GPT（仅处理高分簇） |
| ⑥ 交付Agent | 飞书多维表格自动写入 → 待办/实验/验证回流 | 飞书开放API |

> ⚠️ **阶段声明**：上述架构为方案设计。当前仓库仅包含确定性基线MVP（无LLM调用），用于验证证据合约、分组逻辑、评分基线和人工复核门控。

---

## 🚀 核心创新点

| 创新点 | 说明 | 区别于 |
|--------|------|--------|
| **证据链** | 每条洞察引用原文ID/URL/时间，不可回链自动作废 | 大模型幻觉 |
| **跨平台校正** | 电商/应用市场/内容平台/垂直社区/客服分层计权 | 单一热帖偏差 |
| **沉默需求发现** | 严重度×可行动性×购买影响独立于频次评分 | 只看声量 |
| **双模型复判+人工仲裁** | 独立复判与首轮分类冲突时触发人工仲裁，不自动输出确定结论 | 单模型黑箱 |
| **实验闭环** | 证据卡→飞书待办→实验→结果回流优化模型 | 一次性报告 |

---

## 📊 试点目标（拟在试点阶段验证）

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| 处理效率 | 单千条工时减少 ≥70% | 人工vs. AI A/B对照 |
| 发现时延 | 批处理 <4h，高风险 <15min | 系统日志 |
| 采纳率 | Top-20 被PM采纳 ≥70% | 双人盲审 |
| 可追溯率 | 100%洞察可回链 | 自动校验 |
| 行动转化 | 30天内进入PRD ≥30% | 飞书状态字段 |

> ⚠️ 以上均为试点目标值，非已实现结果。数值须取得迈金现有VOC流程基线后校准。

---

## 📁 仓库目录

```
ridepulse-ai/
├── README.md                              # 本文件
├── LICENSE
├── docs/
│   ├── 01_problem_analysis.md             # 命题分析与行业洞察
│   ├── 02_solution_design.md              # 技术方案设计
│   └── 04_references.txt                  # 参考资料清单
├── data/
│   ├── classification_schema.json         # 分类JSON Schema v1.0
│   └── verified_evidence_sample.json      # 已验证的样例证据数据
├── agents/
│   ├── understander/
│   │   └── classification_prompt.md       # 理解Agent Prompt模板
│   ├── reviewer/
│   │   └── evidence_card_template.md      # 证据审校Agent Prompt模板
│   └── governor/
│       └── translation_prompt.md          # 翻译Agent Prompt模板
├── scripts/
│   ├── __init__.py
│   └── run_mvp.py                         # 确定性基线MVP（无LLM）
├── tests/
│   └── test_run_mvp.py                    # MVP基线测试
├── output/
│   └── evidence_cards.md                  # MVP基线输出示例
└── images/
    └── README.md                          # 图片资源说明（待制作）
```

> 📌 本仓库公开展示方案架构、分类体系和Prompt设计方法。完整数据（41条反馈样本、来源台账、双人标注记录）见团队参赛提交的配套CSV文件。

---

## 🧪 快速开始

### 环境要求

```bash
# Python 3.10+
pip install -r requirements.txt  # 拟在正式试点阶段提供
```

### 运行确定性基线MVP

```bash
# 对样例证据数据运行确定性基线（无LLM/Embedding调用）
python scripts/run_mvp.py --input data/verified_evidence_sample.json --output output/evidence_cards.md
```

> 当前基线MVP为确定性规则引擎——**不使用LLM，不使用Embedding模型**。它证明的是证据合约、分组逻辑、评分公式和人工复核门控的正确性。完整的多Agent流水线（含双模型复判、跨语言聚类、证据卡自动生成）为方案设计，拟在试点阶段实现。

---

## 👥 团队

| 角色 | 姓名 | 学校 | 核心能力 |
|------|------|------|---------|
| 队长/AI架构师 | 张中宝 | 山东外国语职业技术大学 · 软件工程技术 | Claude/GPT/Codex、数学建模、软件项目 |
| 骑行与商业 | 李昂 | 澳门科技大学 · 工商管理 | 多年骑行经验、产品商业化、竞品研究 |
| 数据负责人 | 冯敬琴 | 四川师范大学 · 地理信息科学 | GIS、Python数据分析、可视化 |

三人背景构成"行业判断—数据验证—产品落地"的闭环：队长深度AI架构→骑行负责人垂直骑行领域→数据负责人严谨分析验证。

---

## 📚 参考资料

详见 [`docs/04_references.txt`](docs/04_references.txt)

核心来源：
- PeopleForBikes — 2024 U.S. Bicycling Participation Study
- Strava — Year In Sport: Trend Report 2025
- road.cc — Garmin "Blue Triangle of Death" (Jan 2025)
- The Verge — Strava API Debacle (Nov 2024)
- ResearchAndMarkets — Cycle Computer Market Report 2025
- BGE-M3: BAAI (2024)
- 迈金科技官网 — magene.cn

完整来源台账（含20条来源的原文摘录、结论边界和访问日期）见参赛提交文件《来源与证据台账.csv》。

---

## 📄 许可证

本项目为2026 AI先锋未来人才大赛参赛作品。代码部分采用MIT许可证。

---

*RidePulse AI — 让每一个骑行用户的声音都能被听见、被追溯、被行动。*
