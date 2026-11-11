"""Render rule-based insights with their evidence and the rule that fired."""
from __future__ import annotations

import streamlit as st

from analytics.base import Insight

_RENDER = {"critical": st.error, "warning": st.warning, "positive": st.success, "info": st.info}


def render_insights(insights: list[Insight], empty_text: str = "No rule fired for the current filters.") -> None:
    if not insights:
        st.caption(empty_text)
        return
    for i in insights:
        _RENDER.get(i.severity, st.info)(f"**{i.title}**  \n{i.detail}")
        with st.expander("Why am I seeing this?", expanded=False):
            st.markdown(f"**Rule:** {i.rule}  \n**KPI:** `{i.kpi}`")
            st.json(i.evidence, expanded=False)
