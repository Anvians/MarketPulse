"""Logistics Analytics. Lateness = delivered DATE later than the estimated DATE."""
import streamlit as st

from analytics import logistics as lg
from components import charts, data, theme
from components.filters import current
from components.formatting import days, money, number, pct
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Logistics Analytics", "Delivery speed and reliability. Only delivered orders with consistent dates are counted.")

k = data.q(lg.calculate_logistics_kpis, f)
kpi_row([
    ("delivered_orders", number(k["delivered_orders"])),
    ("on_time_deliveries", number(k["on_time_deliveries"])),
    ("late_deliveries", number(k["late_deliveries"])),
    ("on_time_delivery_rate", pct(k["on_time_delivery_rate"])),
    ("late_delivery_rate", pct(k["late_delivery_rate"])),
    ("avg_delivery_time", days(k["avg_delivery_days"])),
    ("avg_delivery_delay", days(k["avg_delay_days"])),
    ("avg_freight_cost", money(k["avg_freight_cost"])),
], per_row=4)
st.caption(f"Orders with valid dates: {k['orders_with_valid_dates']:,}. Average delay of late orders only: {days(k['avg_delay_of_late_orders'])}. "
           "Delay is negative when orders arrive before the estimate.")

c1, c2 = st.columns(2)
tr = data.q(lg.get_delivery_trend, f)
with c1:
    charts.chart_card("Actual vs estimated delivery days by month", charts.when(tr, lambda: charts.line_fig(tr, "year_month", {"Actual": "avg_delivery_days", "Estimated": "avg_estimated_days"}, "Days")), tr, "log_trend")
with c2:
    charts.chart_card("Late-delivery rate by month (%)", charts.when(tr, lambda: charts.line_fig(tr.assign(late_pct=100 * tr["late_rate"]), "year_month", {"Late rate": "late_pct"}, "% of delivered orders", colors={"Late rate": theme.ORANGE})), tr, "log_late")

c3, c4 = st.columns(2)
dd = data.q(lg.calculate_delay_distribution, f)
with c3:
    charts.chart_card("Delivery delay vs estimate (days; negative = early)", charts.when(dd, lambda: charts.column_fig(dd, "delay_days", "orders", labels=False)), dd, "log_delay")
with c4:
    bs = data.q(lg.analyze_delivery_by_state, f)
    ok = bs[bs["orders"] >= settings.STATE_MIN_ORDERS] if not bs.empty else bs
    charts.chart_card(f"Late rate by state (states with ≥ {settings.STATE_MIN_ORDERS} orders)", charts.when(ok, lambda: charts.bar_fig(ok.assign(late_pct=100 * ok["late_rate"]).sort_values("late_pct", ascending=False).head(12), "state", "late_pct", pct=True)), bs, "log_state")

section("Freight")
c5, c6 = st.columns(2)
with c5:
    fc = data.q(lg.calculate_freight_by_category, f)
    charts.chart_card("Freight as a share of price, by category (top 12)", charts.when(fc, lambda: charts.bar_fig(fc.sort_values("freight_to_price", ascending=False).head(12), "category", "freight_to_price")), fc, "log_freight")
with c6:
    rel = data.q(lg.calculate_freight_delivery_relationship, f)
    st.markdown("**Freight vs delivery time**")
    if rel.get("n"):
        st.write(f"Spearman ρ = **{rel['spearman']:.2f}**, Pearson r = **{rel['pearson']:.2f}** (n = {rel['n']:,} orders).")
        st.caption("Correlation measures association only; it does not show that freight causes slower delivery.")
    else:
        st.info("Not enough orders to compute a correlation.")

section("Bottlenecks", f"States and sellers whose late rate is at least {settings.LOGISTICS_BOTTLENECK_FACTOR}× the overall rate.")
data_table(data.q(lg.identify_logistics_bottlenecks, f), "logistics_bottlenecks", "log_bn")
tabs = st.tabs(["Delivery ranking by state", "Late orders", "Sellers"])
with tabs[0]:
    data_table(data.q(lg.rank_delivery_performance, f), "delivery_ranking", "log_rank")
with tabs[1]:
    data_table(data.q(lg.identify_late_orders, f, limit=500), "late_orders", "log_late_tbl")
with tabs[2]:
    data_table(data.q(lg.analyze_delivery_by_seller, f).head(500), "delivery_by_seller", "log_sel")
