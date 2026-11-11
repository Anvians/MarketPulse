"""Sidebar: logo, global filters, data status and cache refresh."""
from __future__ import annotations

import streamlit as st

from analytics.base import Filters
from analytics.system import get_data_period
from components import data, filters as flt
from config import settings


def render_sidebar() -> Filters:
    with st.sidebar:
        f = flt.render_filters()
        st.divider()
        period = data.q(get_data_period)
        st.markdown(
            f'<div class="mp-status"><b>Data:</b> Olist marketplace, historical<br>'
            f'<b>Period:</b> {period["first_day"]} → {period["last_day"]}<br>'
            f'<b>Orders loaded:</b> {period["orders"]:,}<br>'
            f'<b>Currency:</b> Brazilian real ({settings.CURRENCY_SYMBOL})</div>', unsafe_allow_html=True)
        if st.button("Refresh data cache", width="stretch",
                     help="Clears cached query results (use after reloading the database)."):
            data.refresh()
            st.rerun()
    return f
