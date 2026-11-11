"""Product Performance."""
import streamlit as st

from analytics import products as pr
from components import charts, data
from components.filters import current
from components.formatting import money, number, score
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Product Performance", "Categories and products by revenue, units, price and review score. No stock data exists, so nothing here speaks to inventory.")

k = data.q(pr.calculate_product_kpis, f)
kpi_row([
    ("products_sold", number(k["products_sold"])),
    ("product_categories", number(k["categories"])),
    ("avg_product_price", money(k["avg_product_price"])),
    ("top_revenue_category", k["top_revenue_category"] or "n/a"),
    ("best_selling_category", k["best_selling_category"] or "n/a"),
    ("avg_product_review_score", score(k["avg_product_review_score"])),
], per_row=3)

c1, c2 = st.columns(2)
with c1:
    t = data.q(pr.get_top_categories_by_revenue, f, top_n=10)
    charts.chart_card("Top 10 categories by revenue", charts.when(t, lambda: charts.bar_fig(t, "category", "revenue", money=True)), t, "prod_top_rev")
with c2:
    q_ = data.q(pr.get_categories_by_quantity, f, top_n=10)
    charts.chart_card("Top 10 categories by units sold", charts.when(q_, lambda: charts.bar_fig(q_, "category", "items")), q_, "prod_top_units")

c3, c4 = st.columns(2)
with c3:
    b = data.q(pr.get_bottom_categories_by_revenue, f, top_n=10)
    charts.chart_card("Bottom 10 categories by revenue", charts.when(b, lambda: charts.bar_fig(b, "category", "revenue", money=True)), b, "prod_bot_rev")
with c4:
    pp = data.q(pr.calculate_product_price_distribution, f)
    charts.chart_card("Item price distribution (capped at the 99th percentile)", charts.when(pp, lambda: charts.histogram_fig(pp["price"].clip(upper=pp["price"].quantile(0.99)), "Item price (R$)")), pp, "prod_price")

section("Category performance matrix",
        f"Categories with at least {settings.CATEGORY_MIN_ORDERS} orders are placed by revenue and review score relative to the median of judged categories. Others are 'Insufficient data'.")
mx = data.q(pr.build_product_performance_matrix, f)
if not mx.empty:
    judged = mx[mx["quadrant"] != "Insufficient data"]
    fig = charts.scatter_fig(judged, "revenue", "avg_review_score", "category", size="orders", x_title="Revenue (R$)", y_title="Average review score",
                             x_ref=float(judged["revenue"].median()) if len(judged) else None, y_ref=float(judged["avg_review_score"].median()) if len(judged) else None)
    charts.chart_card("Revenue vs review score by category", fig if len(judged) else None, mx, "prod_matrix",
                      "Dashed lines are the medians of judged categories. Bubble size = orders.")
else:
    st.info("No categories for the current filters.")

tabs = st.tabs(["Top products", "Slowest products", "Underperforming categories", "High-freight products", "Worth promoting", "Weight & size"])
with tabs[0]:
    data_table(data.q(pr.get_top_selling_products, f, top_n=20), "top_products", "prod_t1")
with tabs[1]:
    st.caption("Many products sold exactly once, so ties are common here.")
    data_table(data.q(pr.get_bottom_selling_products, f, top_n=20), "slow_products", "prod_t2")
with tabs[2]:
    st.caption("Categories with enough orders that breach a stated rule; the reasons column names the rule.")
    data_table(data.q(pr.identify_underperforming_categories, f), "underperforming_categories", "prod_t3")
with tabs[3]:
    st.caption(f"Products whose freight is at least {settings.HIGH_FREIGHT_RATIO:.0%} of their price.")
    data_table(data.q(pr.get_products_with_high_freight, f), "high_freight_products", "prod_t4")
with tabs[4]:
    st.caption("Categories with high review scores but below-median revenue (quadrant 'Grow / promote').")
    data_table(data.q(pr.get_products_worth_promoting, f), "worth_promoting", "prod_t5")
with tabs[5]:
    a = data.q(pr.calculate_product_attribute_summary, f)
    st.write(f"Products sold: **{a['products']:,}** · missing weight: **{a['missing_weight']:,}** · missing dimensions: **{a['missing_dimensions']:,}**")
    w = data.q(pr.calculate_product_weight_distribution, f).dropna(subset=["weight_g"])
    charts.chart_card("Weight of sold products (capped at the 99th percentile)", charts.when(w, lambda: charts.histogram_fig(w["weight_g"].clip(upper=w["weight_g"].quantile(0.99)), "Weight (g)")), w, "prod_weight")
