"""证据卡生成模块。

实现要求（文档15 §7.14）：
1. 代码先生成结构化簇摘要和分数
2. 只把簇内允许引用的反馈传给模型
3. 代码验证所有引用 ID 都属于该簇
4. 每条核心发现至少一个 feedback_id
5. URL 由代码附加，不允许模型编 URL
6. 证据卡默认 human_review_status=pending
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ridepulse.models import (
    ClassificationResult,
    ClusterInfo,
    EvidenceCard,
    FeedbackRecord,
    HumanReviewStatus,
)

logger = logging.getLogger(__name__)

# 主题 -> 建议责任团队与可执行动作模板（确定性兜底，模型缺失时使用）
THEME_OWNER: dict[str, tuple[str, list[dict[str, str]]]] = {
    "connectivity": (
        "连接与同步团队",
        [
            {"action": "复现同步失败场景，检查上传协议与数据校验逻辑", "owner": "连接与同步团队"},
            {"action": "补充同步失败的重试与错误提示，避免静默丢失", "owner": "连接与同步团队"},
        ],
    ),
    "firmware": (
        "固件团队",
        [
            {"action": "排查固件稳定性问题（重启循环/更新失败）", "owner": "固件团队"},
            {"action": "增加版本回滚与升级失败保护机制", "owner": "固件团队"},
        ],
    ),
    "navigation": (
        "导航算法团队",
        [
            {"action": "复核导航路线规划与偏航重算逻辑", "owner": "导航算法团队"},
            {"action": "补充导航场景回归测试（夜间/陌生路线）", "owner": "导航算法团队"},
        ],
    ),
    "data_accuracy": (
        "数据团队",
        [
            {"action": "核对数据字段映射与第三方同步（Strava 等）的完整性与单位", "owner": "数据团队"},
        ],
    ),
    "hardware": (
        "硬件团队",
        [
            {"action": "排查硬件相关故障（按键/传感器/续航）", "owner": "硬件团队"},
        ],
    ),
    "display_ux": (
        "体验设计团队",
        [
            {"action": "评估屏幕与交互体验问题", "owner": "体验设计团队"},
        ],
    ),
    "after_sales": (
        "售后团队",
        [
            {"action": "核查售后响应流程与用户诉求闭环", "owner": "售后团队"},
        ],
    ),
    "price_value": (
        "产品团队",
        [
            {"action": "评估定价与价值感知问题", "owner": "产品团队"},
        ],
    ),
    "compatibility": (
        "兼容性团队",
        [
            {"action": "排查设备/配件/平台兼容性问题", "owner": "兼容性团队"},
        ],
    ),
    "feature_request": (
        "产品团队",
        [
            {"action": "评估需求进入产品路线图的优先级", "owner": "产品团队"},
        ],
    ),
    "packaging": (
        "供应链团队",
        [
            {"action": "核查包装与配件问题", "owner": "供应链团队"},
        ],
    ),
    "other": (
        "产品团队",
        [
            {"action": "人工梳理该问题簇的根因与责任团队", "owner": "产品团队"},
        ],
    ),
}


def _theme_label(theme: str) -> str:
    """主题枚举 -> 中文标签（用于确定性标题）。"""
    labels = {
        "connectivity": "连接同步",
        "firmware": "固件稳定性",
        "navigation": "导航可靠性",
        "data_accuracy": "数据准确性",
        "hardware": "硬件故障",
        "display_ux": "显示与交互",
        "after_sales": "售后服务",
        "price_value": "价格价值",
        "compatibility": "兼容性",
        "feature_request": "功能建议",
        "packaging": "包装配件",
        "other": "其他",
    }
    return labels.get(theme, theme)


def _aggregate_root_causes(classifications: list[ClassificationResult], cap: int = 3) -> list[str]:
    """聚合簇内成员根因假设（去重、截断）。"""
    seen: list[str] = []
    for classification in classifications:
        for hypothesis in classification.root_cause_hypotheses:
            if hypothesis not in seen:
                seen.append(hypothesis)
    return seen[:cap]


def _deterministic_card(cluster: ClusterInfo, members: list[FeedbackRecord],
                        classifications: list[ClassificationResult],
                        score: dict) -> dict:
    """确定性兜底卡内容：模型缺失/失败时由代码生成，保证流水线不中断。

    标题取簇内最高频 JTBD 目标短语，问题陈述取第一条证据原文（截断），
    不编造任何数据事实。
    """
    theme = cluster.theme_primary.value if cluster.theme_primary else "other"
    owner, default_actions = THEME_OWNER.get(theme, THEME_OWNER["other"])

    jtbds: list[str] = []
    for classification in classifications:
        jtbd = classification.jtbd
        if jtbd and jtbd not in jtbds:
            jtbds.append(jtbd)
    top_jtbd = jtbds[0] if jtbds else f"用户希望解决{_theme_label(theme)}相关问题"
    # 标题：主题 + 最高严重度 + 证据数，保持具体
    title = f"{_theme_label(theme)}问题簇：{top_jtbd[:30]}（{len(cluster.member_feedback_ids)}条证据）"

    first = members[0]
    problem_statement = first.original_text[:120]
    if len(first.original_text) > 120:
        problem_statement += "…"

    return {
        "title": title,
        "problem_statement": problem_statement,
        "root_cause_hypotheses": _aggregate_root_causes(classifications),
        "recommended_actions": default_actions,
        "suggested_owner": owner,
        "counter_evidence": None,
    }


def _llm_card(cluster: ClusterInfo, members: list[FeedbackRecord],
              classifications: list[ClassificationResult], score: dict,
              client: Any, prompt_version: str) -> dict | None:
    """用模型生成卡内容；失败时返回 None（调用方回退确定性模板）。"""
    try:
        member_texts = "\n".join(
            f"- FID {record.feedback_id}: {record.original_text[:100]}"
            for record in members[:10]
        )
        stats = (
            f"簇 {cluster.cluster_id}: {len(members)}条证据，"
            f"最高严重度 {cluster.max_severity.value}，优先级分数 {score['priority_score']}"
        )
        raw = client.complete_json(
            "你是一个需求分析助手。只依据给定证据生成证据卡内容，"
            "不得编造任何原文中不存在的根因或数字。只输出 JSON，键包括："
            "title, problem_statement, root_cause_hypotheses, recommended_actions, "
            "suggested_owner, counter_evidence。",
            f"{stats}\n\n证据原文（仅簇内成员）：\n{member_texts}",
        )
        return {
            "title": str(raw.get("title", "")).strip() or None,
            "problem_statement": str(raw.get("problem_statement", "")).strip() or None,
            "root_cause_hypotheses": list(raw.get("root_cause_hypotheses", []))[:3],
            "recommended_actions": list(raw.get("recommended_actions", []))[:5],
            "suggested_owner": str(raw.get("suggested_owner", "")).strip() or None,
            "counter_evidence": str(raw.get("counter_evidence", "")).strip() or None,
        }
    except Exception as exc:  # noqa: BLE001 — 模型失败回退确定性模板
        logger.warning("证据卡 LLM 生成失败（%s），回退确定性模板: %s", cluster.cluster_id, exc)
        return None


def generate_cards(clusters: list[ClusterInfo], records_by_id: dict[str, FeedbackRecord],
                   classifications: dict[str, ClassificationResult],
                   scores: dict[str, dict] | None = None,
                   client: Any = None, *, year: int = 2026) -> list[EvidenceCard]:
    """生成证据卡列表。

    clusters: 聚类结果
    records_by_id: {feedback_id: FeedbackRecord}
    classifications: {feedback_id: ClassificationResult}
    scores: {cluster_id: score_dict}，缺省时按空分数字典生成（分数由调用方补充）
    client: LLM 客户端；None / Fake 时使用确定性模板
    """
    if client is None or getattr(client, "model", "fake") == "fake-model":
        use_llm = False
    else:
        use_llm = True

    cards: list[EvidenceCard] = []
    for cluster in clusters:
        members = [
            records_by_id[fid] for fid in cluster.member_feedback_ids
            if fid in records_by_id
        ]
        member_classifications = [
            classifications[fid] for fid in cluster.member_feedback_ids
            if fid in classifications
        ]
        score = (scores or {}).get(cluster.cluster_id, {
            "priority_score": 0, "priority_level": "P3", "confidence_level": "low",
        })
        card_id = f"EC-{year}-{len(cards) + 1:04d}"

        content = None
        if use_llm:
            content = _llm_card(cluster, members, member_classifications, score,
                                client, prompt_version="evidence_v1")
        content = content or _deterministic_card(cluster, members, member_classifications, score)

        cards.append(
            EvidenceCard(
                card_id=card_id,
                cluster_id=cluster.cluster_id,
                title=content["title"],
                problem_statement=content["problem_statement"],
                priority_score=score["priority_score"],
                priority_level=score["priority_level"],
                confidence_level=score["confidence_level"],
                evidence_ids=cluster.member_feedback_ids,
                platforms=sorted({record.source_platform for record in members}),
                brands=sorted({record.brand for record in members}),
                languages=sorted({record.language for record in members}),
                root_cause_hypotheses=content["root_cause_hypotheses"],
                counter_evidence=content["counter_evidence"],
                recommended_actions=content["recommended_actions"],
                suggested_owner=content["suggested_owner"],
                human_review_status=HumanReviewStatus.PENDING,
                model_name=getattr(client, "model", None) if use_llm else None,
                prompt_version="evidence_v1" if use_llm else "deterministic_v1",
                created_at=datetime.now(),
            )
        )
    return cards


def validate_citation(card: EvidenceCard, cluster_members: set[str]) -> list[str]:
    """验证证据卡引用的 ID 是否都在簇内，返回违规 ID 列表。"""
    violations = [fid for fid in card.evidence_ids if fid not in cluster_members]
    return sorted(set(violations))
