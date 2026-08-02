"""RidePulse AI — Streamlit 体验入口。

页面（文档15 §8）：
1. 数据采集与导入
2. 分析概览
3. 人工复核
4. 需求簇
5. 证据卡
6. 飞书交付
7. 评测

运行: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="RidePulse AI", page_icon="🚴", layout="wide")

st.title("RidePulse AI — 全球骑行用户需求雷达")

st.markdown(
    "### 工作台（开发中）\n\n"
    "系统骨架已就绪。核心流水线模块将在 8月3日-8月9日 逐步实现。\n\n"
    "当前状态：**Pipeline 编排未实现**"
)
