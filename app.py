"""RidePulse AI — Streamlit 体验入口(M4 成果展示工作台)。

页面:
1. 运行概览(统计卡 + 评测指标 + 优先级分布)
2. 需求簇(21 个需求簇明细)
3. 证据卡(21 张,含根因假设/建议动作/证据 URL)
4. 评测(指标表 + 字段级错误案例 + 图表)
5. 人工复核(双模型复判 + 12 条裁决记录)

运行: streamlit run app.py
本页面只读展示仓库内已提交的正式运行产物,不调用任何 LLM、不依赖密钥。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="RidePulse AI", page_icon="🚴", layout="wide")

RUN_DIR = Path("output") / "RUN-20260813-211103"
GITHUB_URL = "https://github.com/zzb-start/ridepulse-ai"

st.title("RidePulse AI — 全球骑行用户需求雷达")
st.caption("正式运行 RUN-20260813-211103 · DATASET v1(37 条真实反馈,2026-08-13 冻结,"
           "12 平台 / 24 来源页,中英双语)· 双模型复判(flash 主分类 + pro 复判)")

with st.expander("📖 怎么看这个工作台(30 秒导读)", expanded=False):
    st.markdown(
        "- **数据从哪来**:37 条真实公开用户反馈(App Store / Google Play / 论坛 / 媒体),"
        "每条含原文、来源 URL、时间,可回链,无虚构数据。\n"
        "- **流水线**:采集 → 标准化 → LLM 分类 → 第二模型独立复判 → 人工仲裁 → "
        "语义聚类 → 纯代码六维评分 → 证据卡。\n"
        "- **五个页签**:运行概览=总体数字;需求簇=21 个问题簇;证据卡=可交给产品经理的"
        "问题陈述+根因假设(标\"待验证\")+建议动作;评测=与双人标注 gold 比对的结果;"
        "人工复核=双模型冲突的逐条裁决记录。\n"
        "- **全部数据与代码**随 GitHub 仓库公开,评测可运行 `python -m ridepulse.cli "
        "evaluate --run-id RUN-20260813-211103 --gold data/verified/annotation_gold.csv` 复现。"
    )


@st.cache_data
def load_csv_opt(name: str) -> pd.DataFrame | None:
    """读取运行产物 CSV;文件不存在时返回 None(页面降级显示,不崩溃)。"""
    p = RUN_DIR / name
    if not p.exists():
        return None
    return pd.read_csv(p, encoding="utf-8-sig")


@st.cache_data
def load_json_opt(name: str):
    p = RUN_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data
def load_cards() -> list[dict] | None:
    p = RUN_DIR / "evidence_cards.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def metrics_rows(metrics: dict) -> list[tuple[str, str]]:
    """把 metrics.json 转成带中文标签的展示行。"""
    if not metrics:
        return []
    paired = metrics.get("paired_count", "-")
    tp = metrics.get("theme_primary") or {}
    nt = metrics.get("need_type") or {}
    sev = metrics.get("severity") or {}
    pi = metrics.get("purchase_impact") or {}
    rows = [
        ("配对样本数(gold 配对)", str(paired)),
        ("一级主题准确率 / macro-F1", f"{tp.get('accuracy', 0):.1%} / {tp.get('macro_f1', 0):.1%}"),
        ("需求五分类准确率", f"{nt.get('accuracy', 0):.1%}"),
        ("严重度准确率 / 加权 Kappa", f"{sev.get('accuracy', 0):.1%} / {metrics.get('severity_weighted_kappa', 0):.3f}"),
        ("购买影响准确率", f"{pi.get('accuracy', 0):.1%}"),
        ("人工复核率(门控生效)", f"{metrics.get('review_rate', 0):.1%}"),
    ]
    return rows


def show_metrics_table(metrics: dict) -> None:
    rows = metrics_rows(metrics)
    if rows:
        st.dataframe(
            pd.DataFrame(rows, columns=["指标", "值"]),
            width="stretch", hide_index=True,
        )


def main() -> None:
    metrics = load_json_opt("metrics.json")

    tab_overview, tab_clusters, tab_cards, tab_eval, tab_review = st.tabs(
        ["运行概览", "需求簇", "证据卡", "评测", "人工复核"]
    )

    # ---------- 1. 运行概览 ----------
    with tab_overview:
        st.subheader("总体结果")
        if metrics:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("正式反馈", "37", "DATASET v1")
            c2.metric("需求簇", "21", "覆盖全部样本")
            c3.metric("证据卡", "21", "EC-2026-0001~0021")
            tp = metrics.get("theme_primary") or {}
            c4.metric("一级主题准确率", f"{tp.get('accuracy', 0):.1%}",
                      f"macro-F1 {tp.get('macro_f1', 0):.1%}")
            c5.metric("严重度加权 Kappa", f"{metrics.get('severity_weighted_kappa', 0):.3f}", "线性加权")
            st.caption("评测口径:系统分类与双人标注 gold 按 feedback_id 配对(18/20);"
                       "Kappa 低与系统性高估一档有关,已在评测页与仓库文档如实披露。")
        else:
            st.info("metrics.json 未随运行产物提交,请检查仓库。")

        st.subheader("评测指标")
        if metrics:
            show_metrics_table(metrics)
        else:
            st.info("暂无指标数据。")

        st.subheader("优先级分布(纯代码六维评分,模型不参与)")
        st.caption("六维权重:证据 15 + 复现 20 + 频率 15 + 严重度 20 + 可执行 15 + 购买 15;"
                   "P1 最高,P3 最低。")
        prio = load_csv_opt("priority_scores.csv")
        if prio is not None:
            cols = [c for c in ["cluster_id", "priority_score", "priority_level",
                                "confidence_level", "penalties", "penalty_notes"] if c in prio.columns]
            st.dataframe(prio[cols], width="stretch", hide_index=True)
        else:
            st.info("priority_scores.csv 未随运行产物提交。")

    # ---------- 2. 需求簇 ----------
    with tab_clusters:
        st.subheader("21 个需求簇")
        st.caption("聚类方式:多语言向量嵌入(本地 MiniLM,384 维)→ 主题分桶 → "
                   "确定性凝聚聚类(cosine,阈值 0.5)。每行是一个问题簇,"
                   "member_feedback_ids 是该簇包含的反馈编号,可回链到来源台账。")
        clusters = load_csv_opt("cluster_results.csv")
        if clusters is not None:
            rename = {
                "cluster_id": "簇编号",
                "member_feedback_ids": "成员反馈",
                "unique_source_record_count": "来源条数",
                "unique_domain_count": "域名数",
                "platform_count": "平台数",
                "language_count": "语言数",
                "brand_count": "品牌数",
                "max_severity": "最高严重度",
                "time_range_days": "时间跨度(天)",
                "is_noise": "噪声标记",
                "theme_primary": "一级主题",
            }
            clusters = clusters.rename(columns={k: v for k, v in rename.items() if k in clusters.columns})
            st.dataframe(clusters, width="stretch", hide_index=True)
        else:
            st.info("cluster_results.csv 未随运行产物提交。")

    # ---------- 3. 证据卡 ----------
    with tab_cards:
        st.subheader("21 张需求证据卡(按优先级排序)")
        st.caption("每张卡包含:问题陈述 / 根因假设(一律标\"待验证\",不下定论)/ "
                   "建议动作(带责任团队)/ 证据 URL(不可回链的卡会被代码校验自动作废)。"
                   "业务审查结论见仓库 team_outputs/liang/business_review.csv。")
        cards = load_cards()
        if cards:
            cards = sorted(cards, key=lambda c: -(c.get("priority_score") or 0))
            for card in cards:
                with st.expander(
                    f"{card['card_id']} {card['title']} — P{card.get('priority_level', '-')} "
                    f"({card.get('priority_score', 0)}分)",
                    expanded=False,
                ):
                    st.write(f"**置信度**: {card.get('confidence_level', '-')} | "
                             f"**平台**: {card.get('platforms', '')} | **品牌**: {card.get('brands', '')} | "
                             f"**语言**: {card.get('languages', '')}")
                    st.write("**问题陈述**")
                    st.write(card.get("problem_statement", ""))
                    st.write("**根因假设(待验证)**")
                    for h in card.get("root_cause_hypotheses", []):
                        st.markdown(f"- {h}")
                    st.write("**建议动作**")
                    for a in card.get("recommended_actions", []):
                        act = a.get("action", a) if isinstance(a, dict) else a
                        owner = a.get("owner", "—") if isinstance(a, dict) else "—"
                        st.markdown(f"- {act}(owner: {owner})")
                    st.write("**证据(点击可回链原文)**")
                    for e in card.get("evidence", []):
                        url = e.get("source_url", e.get("url", ""))
                        sev = e.get("severity")
                        label = e.get("feedback_id", "")
                        if sev:
                            label += f" · 严重度 {sev}"
                        st.markdown(f"- [{label}]({url})")
        else:
            st.info("evidence_cards.json 未随运行产物提交。")

    # ---------- 4. 评测 ----------
    with tab_eval:
        st.subheader("评测结果(模型 vs 双人标注 gold)")
        st.caption("gold 为前期双人标注试点样本(20 条,低于 50 条计划目标,已在方案中披露);"
                   "配对 18/20,2 条因数据集版本差异未配对。")
        if metrics:
            show_metrics_table(metrics)
        else:
            st.info("暂无指标数据。")

        st.subheader("字段级错误案例(error_cases.csv)")
        st.caption("模型与 gold 不一致的字段明细:severity 9 条错误全部为系统性高估一档,"
                   "已写入人工复核规则;购买影响差异源于标注口径不一致,已如实披露。")
        errors = load_csv_opt("error_cases.csv")
        if errors is not None:
            st.dataframe(errors, width="stretch", hide_index=True)
        else:
            st.info("error_cases.csv 未随运行产物提交。")

        st.subheader("评测图表")
        charts_dir = RUN_DIR / "charts"
        if charts_dir.exists():
            col_a, col_b = st.columns(2)
            p_a, p_b = charts_dir / "acc_f1.png", charts_dir / "severity_confusion.png"
            with col_a:
                if p_a.exists():
                    st.image(str(p_a), caption="四字段准确率 / Macro-F1(模型 vs gold,配对 18)")
            with col_b:
                if p_b.exists():
                    st.image(str(p_b), caption="严重度混淆矩阵(行=gold,列=模型):非对角元集中在一侧,"
                                               "即系统性高估一档")

    # ---------- 5. 人工复核 ----------
    with tab_review:
        st.subheader("人工复核(双模型复判的冲突裁决)")
        st.caption("分类与复判字段级冲突不自动采信,进入人工队列;12 条冲突全部人工裁决,"
                   "逐条依据留档,可审计。")
        human = load_csv_opt("human_final_outputs.csv")
        if human is not None:
            st.dataframe(human, width="stretch", hide_index=True)
        else:
            st.info("human_final_outputs.csv 未随运行产物提交。")
        rec = RUN_DIR / "adjudication_record.csv"
        if rec.exists():
            st.subheader("裁决记录(adjudication_record.csv)")
            adjud = load_csv_opt("adjudication_record.csv")
            if adjud is not None:
                st.dataframe(adjud, width="stretch", hide_index=True)

    st.divider()
    st.caption(f"数据与代码:{GITHUB_URL} · 192 项自动化测试全部通过 · 本页不调用 LLM")


if __name__ == "__main__":
    main()
