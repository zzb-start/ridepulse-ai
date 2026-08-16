# data/auto — 周更自动流水线的数据区

> 让系统长期自动运转,人工只做一件事:裁决双模型冲突。

## 文件说明

| 文件 | 作用 |
|---|---|
| `feedback_pool.csv` | 主反馈池(全字段契约同 `feedback_verified.csv`)。初始为 37 条核验版 DATASET v1,自动采集的新评论追加进来(evidence_status=unverified,待人工核验) |
| `collect_targets.csv` | 采集目标(App Store RSS 公开接口):app_id / 地区 / 品牌 / 型号 / 语言 |
| `cursors.json` | 每个目标的评论 ID 游标,增量采集不重复入库 |
| `human_decisions.csv` | 人工裁决(可选):双模型冲突的最终结论,下次运行自动回填 |
| `latest_run.txt` | 最近一次自动运行 ID(流水线自动写) |

## 运转流程

1. GitHub Actions 每周一北京时间 02:37 自动触发(或 Actions 页手动 Run workflow)
2. `scripts/auto_weekly.py` 四步:API 自检 → 增量采集 → 全链路运行 → 冲突报告
3. 新运行产物自动 commit,push 后在线工作台自动重建,侧边栏可切换查看
4. 有冲突时自动开 issue(标签 `ridepulse-auto`);任何步骤失败,工作流亮红并自动开告警 issue

## 人工只做两件事

- **裁决冲突**:打开自动生成的 issue,把结论写入 `human_decisions.csv`
  (feedback_id + sentiment/theme_primary/need_type/severity/purchase_impact + note),
  下次运行自动回填;未裁决的冲突在评分中扣分并在下轮再次提醒
- **核验新数据**:新采集行 evidence_status=unverified,建议定期抽查来源链接
  (每条都带可回链的 App Store 评论 URL)

## 首次启用

仓库 Settings → Secrets and variables → Actions → New repository secret:

| Secret | 填什么 |
|---|---|
| `LLM_BASE_URL` | OpenAI 兼容 API 地址,如 MiniMax 官方 `https://api.minimaxi.com/v1`(国内)/ `https://api.minimax.io/v1`(国际);换供应商代码零改动 |
| `LLM_API_KEY` | 官方 API key(只存 Secrets,绝不进代码) |
| `LLM_PRIMARY_MODEL` | 主分类模型名,如 `MiniMax-M3`(以官方平台实际可用为准) |
| `LLM_REVIEW_MODEL` | 复判模型名,与主模型不同以保持双模型独立性(订阅含 MiniMax-M2/Text-01 可选用;仅 M3 时填 `MiniMax-M3`,独立性降级) |

嵌入默认走本地多语言模型(CI 内缓存,不消耗 API 费用)。
