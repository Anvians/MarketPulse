"""Customer Analytics. A customer is a person (customer_unique_id), not a per-order customer_id."""
import streamlit as st

from analytics import customers as cu
from analytics.system import search_customer, get_customer_orders
from components import charts, data, theme
from components.filters import current
from components.formatting import money, number, pct
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table

f = current()
page_header("Customer Analytics", "Who buys, how often and how much. Customers are people (customer_unique_id); lifetime figures are observed within the filtered period only.")

k = data.q(cu.calculate_customer_kpis, f)
kpi_row([
    ("total_customers", number(k["total_customers"])),
    ("new_customers", number(k["new_customers"])),
    ("repeat_customers", number(k["repeat_customers"])),
    ("repeat_purchase_rate", pct(k["repeat_purchase_rate"])),
    ("avg_customer_revenue", money(k["avg_customer_revenue"])),
    ("avg_orders_per_customer", number(k["avg_orders_per_customer"], 2)),
    ("observed_lifetime_revenue", money(k["observed_lifetime_revenue_median"])),
], per_row=4)

c1, c2 = st.columns(2)
with c1:
    nr = data.q(cu.calculate_new_vs_returning, f)
    charts.chart_card("New vs returning customers per month", charts.when(nr, lambda: charts.line_fig(
        nr, "year_month", {"New": "new_customers", "Returning": "returning_customers"}, "Customers",
        colors={"New": theme.entity_color("customer_kind", "new"), "Returning": theme.entity_color("customer_kind", "returning")})), nr, "cust_new_ret",
        "New = first-ever purchase in that month. Returning = bought before, in any earlier month.")
with c2:
    fr = data.q(cu.calculate_customer_frequency, f)
    charts.chart_card("Customers by number of orders", charts.when(fr, lambda: charts.column_fig(fr, "orders", "customers")), fr, "cust_freq")

c3, c4 = st.columns(2)
with c3:
    ct = data.q(cu.calculate_revenue_by_customer_type, f)
    charts.chart_card("Revenue share by purchase-frequency segment", charts.when(ct, lambda: charts.bar_fig(
        ct, "frequency_segment", "revenue_share_pct", pct=True, color_map={s: theme.entity_color("segment", s) for s in ct["frequency_segment"]})), ct, "cust_seg")
with c4:
    cr = data.q(cu.calculate_customer_revenue_distribution, f)
    charts.chart_card("Revenue per customer (capped at the 99th percentile)", charts.when(cr, lambda: charts.histogram_fig(cr["revenue"].clip(upper=cr["revenue"].quantile(0.99)), "Revenue per customer (R$)")), cr, "cust_rev_dist")

single = data.q(cu.identify_single_purchase_customers, f)
pat = data.q(cu.identify_customer_purchase_patterns, f)
section("Purchase behaviour")
c5, c6 = st.columns(2)
c5.metric("One-order customers", pct(single["customer_share"]), help=f"{single['customers']:,} people with exactly one revenue order in scope.", border=True)
c5.caption(f"They account for {pct(single['revenue_share'])} of revenue.")
c6.metric("Median days between orders (repeat buyers)", number(pat["median_days_between_orders"], 0), border=True,
          help="Median gap between consecutive revenue orders of customers with more than one order in scope.")
c6.caption(f"Average days to second order: {number(pat['avg_days_to_second_order'], 0)}. Avg order value: repeat {money(pat['avg_order_value_repeat_customers'])}, one-time {money(pat['avg_order_value_single_customers'])}.")

tabs = st.tabs(["Customers by state", "High-value customers", "Repeat customers", "Find a customer"])
with tabs[0]:
    cs = data.q(cu.calculate_customers_by_state, f)
    charts.chart_card("Customers by state (top 12)", charts.when(cs, lambda: charts.bar_fig(cs.head(12), "state", "customers")), cs, "cust_state")
with tabs[1]:
    st.caption("Top 10% of customers by revenue in scope.")
    data_table(data.q(cu.identify_high_value_customers, f).head(500), "high_value_customers", "cust_hv")
with tabs[2]:
    data_table(data.q(cu.identify_repeat_customers, f).head(500), "repeat_customers", "cust_rep")
with tabs[3]:
    term = st.text_input("Customer id, city or state", key="cust_search", help="Case-insensitive search; returns at most 50 matches.")
    if term.strip():
        res = data.q(search_customer, None, term.strip())
        data_table(res, "customer_search", "cust_search_tbl")
        if not res.empty:
            pick = st.selectbox("Show orders of", res["customer_unique_id"].tolist(), key="cust_pick")
            data_table(data.q(get_customer_orders, None, pick), "customer_orders", "cust_orders")
