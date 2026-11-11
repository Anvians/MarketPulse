"""Revenue Intelligence."""
import streamlit as st

from analytics import revenue as rv
from components import charts, data, theme
from components.filters import current
from components.formatting import money, pct_points
from components.insights import render_insights
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table

f = current()
page_header("Revenue Intelligence", "Where product revenue comes from and how it moves. Revenue is item price; freight is separate; not profit.")

k = data.q(rv.calculate_revenue_kpis, f)
kpi_row([
    ("total_revenue", money(k["total_revenue"], True)),
    ("freight_charges", money(k["freight_charges"], True)),
    ("avg_order_value", money(k["avg_order_value"])),
    ("revenue_per_customer", money(k["revenue_per_customer"])),
    ("revenue_growth", pct_points(k["revenue_growth_pct"], signed=True)),
    ("top_category_share", pct_points(k["top_category_share_pct"])),
], per_row=3)
st.caption(f"Top category: {k['top_category'] or 'n/a'}. Growth compares the latest and previous full month"
           + (f" ({k['revenue_growth_basis']})." if k["revenue_growth_basis"] else " (not enough full months)."))

m = data.q(rv.calculate_monthly_revenue, f)
aov = data.q(rv.calculate_average_order_value_trend, f)
c1, c2 = st.columns(2)
with c1:
    charts.chart_card("Monthly revenue", charts.when(m, lambda: charts.line_fig(m, "year_month", {"Revenue": "revenue", "Freight": "freight"}, "R$", money=True)),
                      m, "rev_monthly", "Months flagged is_sparse are near-empty edge months; growth is not computed across them.")
with c2:
    charts.chart_card("Average order value by month", charts.when(aov, lambda: charts.line_fig(aov, "year_month", {"Average order value": "avg_order_value"}, "R$", money=True)),
                      aov, "rev_aov", "Product revenue / distinct revenue orders (freight excluded).")

cat = data.q(rv.calculate_category_revenue_contribution, f)
st_ = data.q(rv.calculate_revenue_by_state, f, limit=12)
c3, c4 = st.columns(2)
with c3:
    top = cat.head(12)
    charts.chart_card("Revenue by category (top 12)", charts.when(top, lambda: charts.bar_fig(top, "category", "revenue", money=True)), cat, "rev_category")
with c4:
    charts.chart_card("Revenue by state (top 12)", charts.when(st_, lambda: charts.bar_fig(st_, "state", "revenue", money=True)), st_, "rev_state")

pay = data.q(rv.calculate_revenue_by_payment, f)
dist = data.q(rv.calculate_revenue_distribution, f)
c5, c6 = st.columns(2)
with c5:
    charts.chart_card("Revenue by primary payment type", charts.when(pay, lambda: charts.bar_fig(
        pay, "payment_type", "revenue", money=True, color_map={p: theme.entity_color("payment", p) for p in pay["payment_type"]})), pay, "rev_payment")
with c6:
    o = dist["orders"]
    s = dist["summary"]
    cap = (f"Median R$ {s['median']:,.2f}, mean R$ {s['mean']:,.2f}, 90th percentile R$ {s['p90']:,.2f} (n={s['count']:,})."
           if s["count"] else None)
    charts.chart_card("Distribution of order value", charts.when(o, lambda: charts.histogram_fig(o["order_value"].clip(upper=o["order_value"].quantile(0.99)), "Order value (R$, capped at the 99th percentile)")),
                      o, "rev_dist", cap)

section("Revenue opportunities", "Rules are stated on each finding; they point to where to look, not to causes or forecasts.")
opp = data.q(rv.identify_revenue_opportunities, f)
render_insights(rv.generate_revenue_recommendations(opp))
tabs = st.tabs(["Categories making 80% of revenue", "Low-performing categories", "Declining categories", "States making 80%", "Top-10 sellers"])
names = ["high_revenue_categories", "low_performing_categories", "declining_categories", "top_states", "seller_concentration"]
notes = ["Smallest set of top categories reaching 80% cumulative revenue.",
         "Revenue share < 1% and fewer than 30 orders.",
         "Revenue in the last 3 non-sparse months lower than in the 3 months before (needs 6 non-sparse months).",
         "Smallest set of states reaching 80% cumulative revenue.", "Top 10 sellers by revenue with cumulative share."]
for tab, name, note in zip(tabs, names, notes):
    with tab:
        st.caption(note)
        data_table(opp[name], name, f"rev_{name}")
