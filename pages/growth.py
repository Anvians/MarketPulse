"""Growth Opportunities: observed rises, thin supply and cross-sell pairs. Nothing is forecast."""
import streamlit as st

from analytics import growth as gr
from components import charts, data
from components.filters import current
from components.insights import render_insights
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Growth Opportunities", "Where observed demand is rising, where local supply looks thin and which categories sell together. Historical comparison only; no forecasts.")

section("Findings")
render_insights(data.q(gr.generate_growth_insights, f), "No growth rule fired for the current filters (some need at least 6 full months of data).")

section("Categories with rising revenue", f"Last 3 non-sparse months vs the 3 before; at least {settings.CATEGORY_MIN_ORDERS} orders.")
gc = data.q(gr.identify_growth_categories, f)
charts.chart_card("Revenue change by category (%)", charts.when(gc, lambda: charts.bar_fig(gc.head(12), "category", "change_pct", pct=True)), gc, "gr_cat")

section("States with rising revenue")
gs = data.q(gr.identify_growth_states, f)
charts.chart_card("Revenue change by state (%)", charts.when(gs, lambda: charts.bar_fig(gs.head(12), "state", "change_pct", pct=True)), gs, "gr_state")

section("Thinly served states", f"States with ≥ {settings.SUPPLY_GAP_MIN_CUSTOMERS} customers and no local seller, or a customers-per-seller ratio in the top quartile.")
st.caption("Sellers can ship across states, so this points to onboarding ideas to check against delivery time and freight, not to proven unmet demand.")
data_table(data.q(gr.identify_underserved_states, f), "underserved_states", "gr_supply")

section("Categories bought together", f"Pairs seen in at least {settings.CROSS_SELL_MIN_PAIR_ORDERS} orders with lift above 1.")
st.caption("Lift compares how often the pair co-occurs with what independence would predict. Most orders contain one category, so pairs are few.")
data_table(data.q(gr.identify_cross_sell_pairs, f), "category_pairs", "gr_pairs")
