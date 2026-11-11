"""MarketPulse - Streamlit entry point.  Run:  streamlit run app.py

This file is the frame every page runs inside: page config, theme, the global
sidebar filters and navigation. Pages themselves live in ``pages/``.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="MarketPulse", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

from components import data, theme  # noqa: E402
from components.sidebar import render_sidebar  # noqa: E402
from config import settings  # noqa: E402

theme.inject_css()
st.logo(str(settings.PROJECT_ROOT / "assets" / "logo.svg"))

ready, message = data.database_ready()
if not ready:
    st.title("MarketPulse")
    st.error(f"The analytics database is not available. {message}")
    st.markdown(
        "1. Start PostgreSQL and check the `DB_*` values in `.env`.\n"
        "2. Download the dataset into `data/raw/` (see `data/README.md`).\n"
        "3. Run `python -m ingestion.run_pipeline`, then reload this page.")
    st.stop()

render_sidebar()

# Only pages that are built appear in the navigation (no placeholder pages).
PAGES = {
    "Overview": [
        st.Page("pages/executive.py", title="Executive Dashboard", icon=":material/dashboard:", default=True),
    ],
    "Revenue & Sales": [
        st.Page("pages/revenue.py", title="Revenue Intelligence", icon=":material/payments:"),
        st.Page("pages/sales.py", title="Sales Analytics", icon=":material/trending_up:"),
        st.Page("pages/products.py", title="Product Performance", icon=":material/inventory_2:"),
    ],
    "Customers": [
        st.Page("pages/customers.py", title="Customer Analytics", icon=":material/groups:"),
        st.Page("pages/segmentation.py", title="Customer Segmentation", icon=":material/category:"),
        st.Page("pages/satisfaction.py", title="Customer Satisfaction", icon=":material/sentiment_satisfied:"),
    ],
    "Operations": [
        st.Page("pages/sellers.py", title="Seller Performance", icon=":material/storefront:"),
        st.Page("pages/logistics.py", title="Logistics Analytics", icon=":material/local_shipping:"),
        st.Page("pages/geography.py", title="Geographic Intelligence", icon=":material/map:"),
    ],
    "Advanced Analytics": [
        st.Page("pages/forecast.py", title="Revenue Forecast", icon=":material/query_stats:"),
        st.Page("pages/delivery_risk.py", title="Delivery Risk", icon=":material/warning:"),
        st.Page("pages/stat_tests.py", title="Statistical Tests", icon=":material/functions:"),
        st.Page("pages/review_text.py", title="Review Text Analysis", icon=":material/chat:"),
    ],
    "Opportunities": [
        st.Page("pages/opportunities.py", title="Business Opportunity Finder", icon=":material/lightbulb:"),
        st.Page("pages/growth.py", title="Growth Opportunities", icon=":material/rocket_launch:"),
    ],
    "System": [
        st.Page("pages/reports.py", title="Business Reports", icon=":material/description:"),
        st.Page("pages/data_quality.py", title="Data Quality & Information", icon=":material/fact_check:"),
    ],
}
st.navigation(PAGES, expanded=True).run()
