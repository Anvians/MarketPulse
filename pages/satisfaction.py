"""Customer Satisfaction. One review per order (the latest); negative = score 1-2."""
import streamlit as st

from analytics import satisfaction as sa
from components import charts, data, theme
from components.filters import current
from components.formatting import number, pct, score
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table

f = current()
page_header("Customer Satisfaction", "Review scores and what drives them. Reviews describe the whole order, so category and seller views are order-level.")

k = data.q(sa.calculate_satisfaction_kpis, f)
kpi_row([
    ("avg_review_score", score(k["avg_review_score"])),
    ("total_reviews", number(k["total_reviews"])),
    ("five_star_reviews", number(k["five_star"])),
    ("one_star_reviews", number(k["one_star"])),
    ("two_star_reviews", number(k["two_star"])),
    ("negative_review_rate", pct(k["negative_review_rate"])),
], per_row=3)

c1, c2 = st.columns(2)
with c1:
    d = data.q(sa.calculate_review_distribution, f)
    charts.chart_card("Reviews by score", charts.when(d, lambda: charts.column_fig(d, "score", "reviews")), d, "sat_dist")
with c2:
    t = data.q(sa.analyze_review_trends, f)
    charts.chart_card("Average review score by purchase month", charts.when(t, lambda: charts.line_fig(t, "year_month", {"Average score": "avg_review_score"}, "Score (1–5)")), t, "sat_trend",
                      "Sparse edge months have few reviews and are noisy.")

section("Delivery and satisfaction")
rel = data.q(sa.analyze_delivery_review_relationship, f)
cmp_ = data.q(sa.compare_late_vs_on_time_reviews, f)
c3, c4 = st.columns([2, 1])
with c3:
    charts.chart_card("Average review score by delivery timing", charts.when(rel, lambda: charts.column_fig(rel.sort_values("sort_key"), "bucket", "avg_review_score", y_title="Average score")), rel, "sat_delivery",
                      "Buckets compare actual delivery date with the estimated date.")
with c4:
    st.metric("On-time orders: average score", score(cmp_["on_time_avg"]), help=f"{cmp_['on_time_orders']:,} reviewed on-time orders.", border=True)
    st.metric("Late orders: average score", score(cmp_["late_avg"]), help=f"{cmp_['late_orders']:,} reviewed late orders.", border=True)
    st.caption("Association, not proof of cause: late orders may also differ in category, seller or region.")

tabs = st.tabs(["By category", "By seller", "By state", "By payment type", "Low-satisfaction categories", "Low-satisfaction sellers"])
with tabs[0]:
    c = data.q(sa.analyze_reviews_by_category, f)
    charts.chart_card("Lowest-scoring categories (min reviews applied in the table below)", None if c.empty else charts.bar_fig(c.sort_values("avg_review_score").head(12), "category", "avg_review_score"), c, "sat_cat")
with tabs[1]:
    data_table(data.q(sa.analyze_reviews_by_seller, f).head(200), "reviews_by_seller", "sat_sel")
with tabs[2]:
    s = data.q(sa.analyze_reviews_by_state, f)
    charts.chart_card("Average score by state", None if s.empty else charts.bar_fig(s.sort_values("avg_review_score"), "state", "avg_review_score"), s, "sat_state")
with tabs[3]:
    p = data.q(sa.analyze_reviews_by_payment, f)
    charts.chart_card("Average score by primary payment type", None if p.empty else charts.bar_fig(p, "payment_type", "avg_review_score", color_map={x: theme.entity_color("payment", x) for x in p["payment_type"]}), p, "sat_pay")
with tabs[4]:
    st.caption("Categories with enough reviews whose average score is below the threshold (see config/settings.py).")
    data_table(data.q(sa.identify_low_satisfaction_categories, f), "low_satisfaction_categories", "sat_lc")
with tabs[5]:
    data_table(data.q(sa.identify_low_satisfaction_sellers, f), "low_satisfaction_sellers", "sat_ls")
