"""Page chrome shared by all pages: header, historical-data banner, empty states."""
from __future__ import annotations

import streamlit as st

from components import filters as flt
from config import settings


def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.markdown(f'<div class="mp-sub">{subtitle}</div>', unsafe_allow_html=True)
    f = flt.current()
    st.markdown(
        f'<div class="mp-banner"><b>Historical data (2016–2018).</b> {settings.DATA_PERIOD_NOTICE.split(". ", 1)[1]} '
        f'&nbsp;|&nbsp; Active filters: {f.describe()}</div>', unsafe_allow_html=True)


def require_data(df, message: str = "No data for the current filters.") -> bool:
    """True when ``df`` has rows; otherwise shows ``message`` and returns False."""
    if df is None or len(df) == 0:
        st.info(message)
        return False
    return True


def section(title: str, help_text: str | None = None) -> None:
    st.subheader(title, help=help_text)
