# RidePulse AI 数据契约 v1（M1 冻结版）

> **冻结日期**：2026-08-02 12:00
> **冻结人**：张中宝（队长）
> **状态**：🔒 **FROZEN — M1 后不得随意修改字段**
> **配套文件**：`DATA_CONTRACT_v1.json`（结构化版本，代码可读）
>
> 本文件是三人协作的数据唯一依据。任何模块不得另建一套字段命名。
> 李昂按此字段建立来源核验表，冯敬琴按此字段建立 Schema 映射，队长按此字段写 Pydantic 模型和数据库。

---

## 1. 试点范围（M1 冻结）

| 项 | 冻结内容 |
|---|---|
| 试点产品 | 骑行码表（C506/C606/C706）+ OnelapFit App |
| 重点问题 | 同步可靠性、App/固件稳定性、导航可靠性 |
| 语言 | 中文（zh）、英文（en） |
| 采集方式 | 标准 CSV + 至少一个合规公开应用商店连接器 |
| 系统输出 | 需求簇、优先级、证据卡、人工复核、飞书待办 |
| **不做** | 全球全平台实时爬虫、企业内部系统直连、生产级实时告警、自动根因定论 |

---

## 2. ID 规则（M1 冻结）

| ID 类型 | 格式 | 示例 |
|---|---|---|
| feedback_id | `F` + 四位数字 | `F0001` |
| source_record_id | 字符串，同一来源页面中的同一条用户发言唯一 | `SR-APPSTORE-0001` |
| cluster_id | `CL-` + 四位数字 | `CL-0001` |
| card_id | `EC-` + 年份 + `-` + 四位数字 | `EC-2026-0001` |
| run_id | `RUN-` + 8位日期 + `-` + 6位时间 | `RUN-20260802-120000` |
| ingest_batch_id | `BATCH-` + 8位日期 + `-` + 6位时间 | `BATCH-20260802-120000` |

**重要规则**：
1. 同一来源页面中的同一条用户发言只有一个 `source_record_id`。
2. 同一发言拆成多个问题时可有多个 `feedback_id`，但 `source_record_id` 相同。
3. 评分时按 `source_record_id` 去重计算频次，**不得把同一帖子的多条问题当作多个独立用户**。

---

## 3. FeedbackRecord（反馈记录字段）

每条反馈必须包含以下字段。**必填** 15 个，**选填** 10 个。

### 3.1 必填字段（15个）

| 字段 | 类型 | 说明 |
|---|---|---|
| `feedback_id` | string | 唯一反馈ID，格式 F0001 |
| `source_record_id` | string | 同一原帖拆分的多条反馈共享此ID |
| `ingest_batch_id` | string | 导入批次 |
| `source_platform` | string | 来源平台名称（App Store / Google Play / 京东 / 知乎 / B站 / 美骑网等） |
| `source_type` | enum | `app_store` / `ecommerce` / `forum` / `social` / `support` / `news` / `other` |
| `source_url` | string | 最接近原始内容的URL，**必须 HTTPS** |
| `source_permalink_level` | enum | `exact_record`（精确到单条）/ `page_only`（页面级）/ `archive_only` / `unverified` |
| `source_date_precision` | enum | `day` / `month` / `year` / `unknown` |
| `accessed_at` | date | 核验/访问日期 YYYY-MM-DD |
| `language` | string | ISO 639-1，如 zh / en / de / ja |
| `brand` | string | 品牌（Magene / Garmin / Wahoo 等） |
| `original_text` | string | **逐字原文，不得修改、不得改写** |
| `text_provenance` | enum | `verbatim`（逐字原文）/ `paraphrased`（摘要改写）/ `unverified` |
| `translation_method` | enum | `not_needed` / `human` / `ai` / `unverified` |
| `evidence_status` | enum | `verified` / `partially_verified` / `unverified` / `rejected` |

### 3.2 选填字段（10个）

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_date` | date / null | 原始日期 YYYY-MM-DD，无法确定则 null（不伪造） |
| `source_date_raw` | string / null | 页面原始日期文本 |
| `market` | string | 国家或地区，未知填 `unknown` |
| `product_model` | string / null | 产品型号（C606 等），未出现则 null |
| `firmware_version` | string / null | 固件版本，未出现则 null |
| `app_version` | string / null | App版本，未出现则 null |
| `translated_text` | string / null | 中文译文，**不覆盖原文** |
| `archive_path` | string / null | 本地截图/存档相对路径 |
| `archive_sha256` | string / null | 存档文件 SHA-256 |
| `verification_note` | string / null | 核验说明与边界 |

### 3.3 证据状态判定规则

| 情况 | text_provenance | evidence_status |
|---|---|---|
| 页面存在完全相同原文 | verbatim | verified |
| 外语原文可逐字核对，另有忠实中文翻译 | verbatim；translation_method=human 或 ai | verified |
| 只有内容摘要，找不到逐字原文 | paraphrased | partially_verified |
| 页面可打开但找不到对应内容 | unverified | unverified |
| 链接失效且无存档 | unverified | rejected |

> ⚠️ 不得为了保持样本数量而把 `unverified` 改成 `verified`。

---

## 4. ClassificationResult（AI 分类输出字段）

第一轮分类模型的输出，严格遵循此结构：

| 字段 | 类型/枚举 | 必填 | 说明 |
|---|---|---|---|
| `feedback_id` | string | 是 | 关联反馈ID |
| `sentiment` | 1-5 | 是 | 1=强烈负面 2=负面 3=中性 4=正面 5=强烈正面 |
| `theme_primary` | enum（12种） | 是 | `connectivity` `firmware` `navigation` `data_accuracy` `hardware` `display_ux` `after_sales` `price_value` `compatibility` `feature_request` `packaging` `other` |
| `theme_secondary` | 上述enum数组 | 否 | 二级主题可多选 |
| `need_type` | enum（6种） | 是 | `real_need` `feature_request` `operation_misunderstanding` `incidental_failure` `emotional_complaint` `unknown` |
| `scenario` | enum（7种） | 否 | `training` `commuting` `racing` `leisure` `indoor` `maintenance` `unknown` |
| `user_type` | enum（5种） | 否 | `beginner` `enthusiast` `competitive` `casual` `unknown`；**不能从一句评论猜测** |
| `severity` | S1-S5 | 是 | 见下方严重度定义 |
| `purchase_impact` | enum（4种） | 否 | `blocker` `influence` `no_impact` `unknown`；**只有明确购买/换购/退货表达才能非unknown** |
| `jtbd` | string（≥10字） | 是 | 格式：用户希望[动作]以达成[目标] |
| `root_cause_hypotheses` | array（≤3条） | 否 | 根因假设，**待验证** |
| `is_actionable` | boolean | 是 | 是否包含可行动信息 |
| `is_constructive` | boolean | 是 | 是否包含建设性建议 |
| `confidence` | 0.0-1.0 | 是 | 分类置信度 |
| `rationale` | string（≤200字） | 是 | 分类理由 |
| `model_name` | string | 是 | 模型名 |
| `prompt_version` | string | 是 | Prompt版本 |

### 4.1 严重度定义

| 等级 | 定义 | 示例 |
|---|---|---|
| S1 | 安全关键 | 导航失效致迷路（陌生路线/夜间）、健康风险、夜间灯光失效 |
| S2 | 核心功能不可用 | 无法开机、无法记录数据、App无法启动 |
| S3 | 功能严重受损 | 数据字段丢失、单次骑行≥3次断连、循环重启但可恢复 |
| S4 | 使用体验下降 | 屏幕不可读、触控延迟、续航不足 |
| S5 | 轻度不便 | 功能建议、美观、非核心功能 |

> ⚠️ **导航不自动等于 S1**，必须结合具体危险场景（陌生路线/夜间/安全依赖）。

### 4.2 need_type 需求五分类（核心设计）

| 枚举 | 含义 |
|---|---|
| `real_need` | 真实需求（功能缺失或缺陷） |
| `feature_request` | 功能建议（期望新功能） |
| `operation_misunderstanding` | 操作误解（用户不会用） |
| `incidental_failure` | 偶发故障（网络超时等） |
| `emotional_complaint` | 情绪抱怨（无明确问题） |
| `unknown` | 无法判断 |

> 同一"同步失败"表述，五分类可区分是功能缺失、用户不会操作、还是偶发网络超时——不同分类对应完全不同的产品动作。

---

## 5. ReviewResult（独立复判输出字段）

| 字段 | 类型/枚举 | 必填 | 说明 |
|---|---|---|---|
| `feedback_id` | string | 是 | 关联反馈ID |
| `review_sentiment` | 1-5 | 是 | 复判情感 |
| `review_theme_primary` | enum | 是 | 复判一级主题 |
| `review_need_type` | enum | 是 | 复判需求五分类 |
| `review_severity` | S1-S5 | 是 | 复判严重度 |
| `review_purchase_impact` | enum | 是 | 复判购买影响 |
| `review_jtbd` | string | 是 | 复判JTBD |
| `review_confidence` | 0.0-1.0 | 是 | 复判置信度 |
| `conflict_fields` | array | 否 | 冲突字段名列表 |
| `review_status` | `agreed`/`conflict`/`failed` | 是 | 对比状态 |
| `human_review_required` | boolean | 是 | 是否进入人工复核 |
| `model_name` | string | 是 | 复判模型名 |
| `prompt_version` | string | 是 | Prompt版本 |

**冲突规则**（对比字段：sentiment / theme_primary / need_type / severity / purchase_impact）：
1. 任一核心字段不同 → 记录 `conflict_fields`
2. `theme_primary`、`need_type` 或 `severity` 冲突 → **必须人工复核**
3. 情感相差 2 级以上 → **必须人工复核**
4. 两轮都低置信度 → **必须人工复核**
5. 第二轮调用失败 → **必须人工复核**

---

## 6. EvidenceCard（证据卡字段）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `card_id` | string | 是 | EC-2026-0001 |
| `cluster_id` | string | 是 | 关联需求簇 CL-0001 |
| `title` | string | 是 | 具体问题标题，**不得写空泛"建议优化"** |
| `problem_statement` | string | 是 | 只描述证据支持的问题 |
| `priority_score` | integer(0-100) | 是 | **代码计算，模型不得参与** |
| `priority_level` | P0/P1/P2/P3 | 是 | P0≥80，P1=65-79，P2=45-64，P3<45 |
| `confidence_level` | high/medium/low | 是 | 置信度等级 |
| `evidence_ids` | array | 是（≥1） | 引用反馈ID，必须都在本簇内 |
| `platforms` | array | 否 | 涉及平台 |
| `brands` | array | 否 | 涉及品牌 |
| `languages` | array | 否 | 涉及语言 |
| `root_cause_hypotheses` | array | 否 | 待验证假设 |
| `counter_evidence` | string/null | 否 | 反证和替代解释 |
| `recommended_actions` | array | 否 | 可执行动作（含 action/suggested_owner/expected_result/validation_metric/effort_size） |
| `suggested_owner` | string/null | 否 | 建议责任团队 |
| `human_review_status` | pending/approved/corrected/rejected | 否 | 默认 pending |

---

## 7. AnnotationRecord（双人标注字段）

李昂（liang）和冯敬琴（feng）独立标注使用：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `feedback_id` | string | 是 | 正式ID F0001 |
| `annotator_id` | string | 是 | `liang` 或 `feng` |
| `sentiment` | 1-5 | 是 | 情感 |
| `theme_primary` | enum | 是 | 一级主题 |
| `need_type` | enum | 是 | 需求五分类 |
| `severity` | S1-S5 | 是 | 严重度 |
| `purchase_impact` | enum | 是 | 购买影响 |
| `jtbd` | string | 是 | JTBD |
| `annotation_note` | string/null | 否 | 标注说明 |
| `annotated_at` | datetime | 是 | 标注时间 |

**盲标文件（annotation_batch_blind.csv）只能包含**：
`feedback_id`、`original_text`、`source_platform`、`source_date`、`language`、`brand`、`product_model`
**绝不能包含**任何人的标签结果。

---

## 8. 双人标注规则（提醒）

1. 不看旧标签，不与对方讨论答案。
2. 导航不自动等于 S1。
3. 只有明确换购、退货、放弃使用才判断 purchase_impact 非 unknown。
4. 不确定时写 annotation_note。
5. 每人至少 50 条独立标注。

---

## 9. 修改规则

M1 冻结后不得随意修改字段。确需修改时，队长必须**同时通知李昂和冯敬琴**，并更新本文件版本号。
