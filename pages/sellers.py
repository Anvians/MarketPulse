"""Seller Performance."""
import streamlit as st

from analytics import sellers as se
from components import charts, data
from components.filters import current
from components.formatting import money, number, pct, score
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Seller Performance", "Revenue, delivery and satisfaction by seller, plus a transparent weighted scorecard.")

k = data.q(se.calculate_seller_kpis, f)
kpi_row([
    ("total_sellers", number(k["total_sellers"])),
    ("sellers_with_orders", number(k["sellers_with_orders"])),
    ("avg_orders_per_seller", number(k["avg_orders_per_seller"], 1)),
    ("avg_seller_revenue", money(k["avg_seller_revenue"])),
    ("avg_seller_review_score", score(k["avg_seller_review_score"])),
    ("seller_late_rate", pct(k["seller_late_delivery_rate"])),
], per_row=3)

c1, c2 = st.columns(2)
with c1:
    r = data.q(se.rank_sellers_by_revenue, f, 10)
    charts.chart_card("Top 10 sellers by revenue", charts.when(r, lambda: charts.bar_fig(r, "seller_id", "revenue", money=True)), r, "sel_rev",
                      "Seller ids are anonymised hashes in the source data.")
with c2:
    st_ = data.q(se.calculate_seller_revenue_by_state, f)
    charts.chart_card("Revenue by seller state", charts.when(st_, lambda: charts.bar_fig(st_.sort_values("revenue", ascending=False).head(12), "state", "revenue", money=True)), st_, "sel_state")

section("Seller scorecard", "A weighted percentile score; the weights, tiers and minimum orders are shown below and live in config/settings.py.")
meth = se.scorecard_methodology()
with st.expander("How the score is computed"):
    st.markdown(
        "Each component is the seller's **percentile rank** among scored sellers (0–1); the score is the weighted sum × 100.\n\n"
        + "\n".join(f"- {name}: weight {w:.0%}" for name, w in meth["weights"].items())
        + f"\n\nOnly sellers with at least **{meth['min_orders']}** orders are scored. Tiers: "
        + ", ".join(f"{t['tier']} ≥ {t['min_score']:.0f}" for t in meth["tiers"]) + ".")
card = data.q(se.generate_seller_scorecard, f)
if card.empty:
    st.info(f"No seller has at least {settings.SELLER_MIN_ORDERS} orders for the current filters, so no scorecard can be built.")
else:
    tiers = card["tier"].value_counts().reindex([t for _, t in settings.SELLER_TIERS]).fillna(0).astype(int).reset_index()
    tiers.columns = ["tier", "sellers"]
    charts.chart_card("Scored sellers by tier", charts.column_fig(tiers, "tier", "sellers"), tiers, "sel_tiers")
    data_table(card, "seller_scorecard", "sel_card")

tabs = st.tabs(["All sellers", "Underperforming sellers", "Find a seller"])
with tabs[0]:
    data_table(data.q(se.seller_table, f).head(1000), "sellers", "sel_all")
with tabs[1]:
    st.caption(f"Sellers with at least {settings.SELLER_MIN_ORDERS} orders that breach a stated rule (see reasons).")
    data_table(data.q(se.identify_underperforming_sellers, f), "underperforming_sellers", "sel_under")
with tabs[2]:
    term = st.text_input("Seller id, city or state", key="sel_search")
    if term.strip():
        data_table(data.q(se.search_sellers, None, term.strip()), "seller_search", "sel_search_tbl")
