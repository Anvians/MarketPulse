"""Geographic Intelligence (customer state; offline Brazil map)."""
import streamlit as st

from analytics import geography as ge
from components import charts, data
from components.filters import current
from components.formatting import number, pct_points
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Geographic Intelligence", "Where customers and sellers are, and how revenue, delivery and satisfaction differ by state.")

k = data.q(ge.calculate_geography_kpis, f)
kpi_row([
    ("total_states", number(k["total_states"])),
    ("customer_cities", number(k["customer_cities"])),
    ("seller_cities", number(k["seller_cities"])),
    ("top_revenue_state", k["top_revenue_state"] or "n/a"),
    ("top_customer_state", k["top_customer_state"] or "n/a"),
], per_row=5)
st.caption(f"Top revenue state share: {pct_points(k['top_revenue_state_share_pct'])}; top customer state share: {pct_points(k['top_customer_state_share_pct'])}.")

summ = data.q(ge.calculate_state_summary, f)
metrics = {"Revenue": ("revenue", True), "Orders": ("orders", False), "Customers": ("customers", False),
           "Late-delivery rate": ("late_rate", False), "Average review score": ("avg_review_score", False),
           "Average delivery days": ("avg_delivery_days", False), "Average freight per order": ("avg_freight_per_order", True)}
choice = st.radio("Map metric", list(metrics), horizontal=True, key="geo_metric")
col, is_money = metrics[choice]
if summ.empty:
    st.info("No data for the current filters.")
else:
    m = summ.dropna(subset=[col])
    charts.chart_card(f"{choice} by customer state", charts.when(m, lambda: charts.choropleth_fig(m, "state", col, choice, money=is_money)), m[["state", col]], "geo_map",
                      "States with no value for the metric (e.g. no delivered orders) are left unshaded, not zero.")

c1, c2 = st.columns(2)
with c1:
    rg = data.q(ge.calculate_revenue_by_region, f)
    charts.chart_card("Revenue by region", charts.when(rg, lambda: charts.bar_fig(rg, "region", "revenue", money=True)), rg, "geo_region", "IBGE macro-regions.")
with c2:
    dist = data.q(ge.calculate_customer_seller_distribution, f)
    charts.chart_card("Customers per seller, by state (top 12 by customers)", charts.when(dist, lambda: charts.bar_fig(dist.sort_values("customers", ascending=False).head(12), "state", "customers_per_seller")), dist, "geo_cps",
                      "Higher = more customers per local seller; sellers in a state may serve customers elsewhere.")

section("State summary", f"Late rate and delivery time use states' delivered orders; treat states with fewer than {settings.STATE_MIN_ORDERS} orders with care.")
data_table(summ, "state_summary", "geo_summary")
tabs = st.tabs(["States making 80% of revenue", "Recent revenue change by state"])
with tabs[0]:
    data_table(data.q(ge.identify_top_revenue_regions, f), "top_revenue_states", "geo_top")
with tabs[1]:
    st.caption("Last 3 non-sparse months vs the 3 before. Observed history, not a forecast.")
    data_table(data.q(ge.identify_growth_regions, f), "state_revenue_change", "geo_growth")
