"""RidePulse AI — Streamlit 体验入口(M4 成果展示工作台)。

页面:
1. 运行概览(统计卡 + 评测指标)
2. 需求簇与优先级
3. 证据卡(21 张)
4. 评测明细与错误案例
5. 人工复核状态

运行: streamlit run app.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="RidePulse AI", page_icon="🚴", layout="wide")

RUN_DIR = Path("output") / "RUN-20260813-211103"

st.title("RidePulse AI — 全球骑行用户需求雷达")
st.caption(f"正式运行 {RUN_DIR.name} · DATASET v1(37 条,2026-08-13 冻结)· 双模型复判(flash 主分类 + pro 复判)")


@st.cache_data
def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(RUN_DIR / name, encoding="utf-8-sig")


@st.cache_data
def load_json(name: str) -> dict:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


@st.cache_data
def load_cards() -> list[dict]:
    return json.loads((RUN_DIR / "evidence_cards.json").read_text(encoding="utf-8"))


def main() -> None:
    tab_overview, tab_clusters, tab_cards, tab_eval, tab_review = st.tabs(
        ["运行概览", "需求簇", "证据卡", "评测", "人工复核"]
    )

    with tab_overview:
        metrics = load_json("metrics.json")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("正式反馈", "37", "DATASET v1")
        c2.metric("需求簇", "21", "覆盖全部样本")
        c3.metric("证据卡", "21", "EC-2026-0001~0021")
        c4.metric("theme accuracy", f"{metrics['theme_primary']['accuracy']:.1%}",
                  f"macro-F1 {metrics['theme_primary']['macro_f1']:.1%}")
        c5.metric("severity κ", f"{metrics['severity_weighted_kappa']:.3f}", "线性加权")

        st.subheader("评测指标(gold 配对 18/20)")
        st.json(metrics)

        st.subheader("优先级分布")
        prio = load_csv("priority_scores.csv")
        st.dataframe(prio, use_container_width=True, hide_index=True)

    with tab_clusters:
        clusters = load_csv("cluster_results.csv")
        st.dataframe(clusters, use_container_width=True, hide_index=True)

    with tab_cards:
        cards = load_cards()
        st.caption(f"共 {len(cards)} 张证据卡,按优先级排序")
        for card in cards:
            with st.expander(
                f"{card['card_id']} {card['title']} — P{card.get('priority_level', '-')} "
                f"({card.get('priority_score', 0)}分)",
                expanded=False,
            ):
                st.write(f"**置信度**: {card.get('confidence_level', '-')} | "
                         f"**平台**: {card.get('platforms', '')} | **品牌**: {card.get('brands', '')}")
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
                st.write("**证据**")
                for e in card.get("evidence", []):
                    url = e.get("source_url", e.get("url", ""))
                    st.markdown(f"- [{e.get('feedback_id', '')}]({url}) · 严重度 {e.get('severity', '')}")

    with tab_eval:
        st.subheader("指标(matched 18/20)")
        st.dataframe(pd.DataFrame([metrics]), use_container_width=True, hide_index=True)
        st.subheader("字段级错误案例(error_cases.csv)")
        errors = load_csv("error_cases.csv")
        st.dataframe(errors, use_container_width=True, hide_index=True)

    with tab_review:
        st.subheader("人工复核状态(12 条冲突已裁决,adjudication_record.csv)")
        human = load_csv("human_final_outputs.csv")
        st.dataframe(human, use_container_width=True, hide_index=True)
        rec = RUN_DIR / "adjudication_record.csv"
        if rec.exists():
            st.subheader("裁决记录")
            st.dataframe(load_csv("adjudication_record.csv"), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
