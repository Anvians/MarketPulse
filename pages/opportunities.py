"""Business Opportunity Finder."""
import streamlit as st

from analytics import opportunities as op
from components import charts, data
from components.filters import current
from components.formatting import money, number
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Business Opportunity Finder", "Rule-based findings across products, logistics, sellers, freight, retention and satisfaction, ranked by the revenue they touch.")
st.info("Ranking uses **observed revenue** of the category, state or seller involved. It sizes what to look at; it is **not** a forecast of gain, "
        "and the data has no costs or experiments. Every row shows the rule that produced it.")

opps = data.q(op.find_business_opportunities, f)
if opps.empty:
    st.success("No rule fired for the current filters.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Findings", number(len(opps)), border=True, help="Rows produced by the rules below for the current filters.")
c2.metric("Areas with findings", number(opps["area"].nunique()), border=True)
c3.metric("Revenue touched by the top finding", money(opps["observed_revenue"].max(), True), border=True,
          help="Observed product revenue of the entity in the first row. Findings overlap, so revenue is not summed across rows.")

summary = op.summarize_opportunities(opps)
charts.chart_card("Findings by area", charts.bar_fig(summary, "area", "findings"), summary, "opp_areas",
                  "Revenue is not added up across areas because the same orders can appear in several findings.")

section("All findings")
areas = st.multiselect("Show areas", sorted(opps["area"].unique()), default=sorted(opps["area"].unique()), key="opp_areas_sel")
shown = opps[opps["area"].isin(areas)]
data_table(shown, "business_opportunities", "opp_table",
           column_config={"observed_revenue": st.column_config.NumberColumn("Observed revenue (R$)", format="%.0f"),
                          "evidence": st.column_config.TextColumn(width="large"), "rule": st.column_config.TextColumn(width="large")})
with st.expander("Thresholds used"):
    st.json({"min category orders": settings.CATEGORY_MIN_ORDERS, "min seller orders": settings.SELLER_MIN_ORDERS,
             "min state delivered orders": settings.STATE_MIN_ORDERS, "low review threshold": settings.LOW_REVIEW_THRESHOLD,
             "seller late-rate limit": settings.SELLER_HIGH_LATE_RATE, "bottleneck factor": settings.LOGISTICS_BOTTLENECK_FACTOR,
             "high freight ratio": settings.HIGH_FREIGHT_RATIO, "low repeat rate": settings.LOW_REPEAT_RATE}, expanded=False)
