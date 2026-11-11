"""Customer Segmentation: RFM rules, k-means clusters and cohort retention."""
import streamlit as st

from analytics import cohorts as co
from analytics import segmentation as sg
from components import charts, data
from components.filters import current
from components.formatting import number, pct
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Customer Segmentation", "Who the customers are by Recency, Frequency and Monetary value, and whether they come back. Customers are people (customer_unique_id).")
st.info("Recency is measured from the day after the **last purchase in the filtered data**, not from today, because the data is historical. "
        "Segments are fixed rules (shown below), not a prediction.")

rfm = data.q(sg.calculate_rfm, f)
if rfm.empty:
    st.info("No customers for the current filters.")
    st.stop()

summary = sg.summarize_segments(rfm)
c1, c2, c3 = st.columns(3)
c1.metric("Customers", number(len(rfm)), border=True, help="Distinct customer_unique_id with at least one revenue order in the filters.")
c2.metric("Repeat customers (2+ orders)", pct((rfm["frequency"] >= 2).mean()), border=True, help="Share of customers with 2 or more revenue orders in the filters.")
c3.metric("Median recency (days)", number(rfm["recency_days"].median(), 0), border=True, help="Median days from each customer's last purchase to the day after the last purchase in scope.")

section("RFM segments", "Scores: recency and monetary are quintiles (5 = best); frequency is 1 / 2 / 3 for 1 / 2 / 3+ orders because most customers buy once.")
with st.expander("Segment rules"):
    for name, rule in sg.SEGMENT_RULES:
        st.markdown(f"- **{name}**: {rule}")
a, b = st.columns(2)
with a:
    charts.chart_card("Share of customers by segment (%)", charts.bar_fig(summary, "segment", "customer_share_pct", pct=True), summary, "seg_cust")
with b:
    charts.chart_card("Share of revenue by segment (%)", charts.bar_fig(summary, "segment", "revenue_share_pct", pct=True), summary, "seg_rev")
data_table(summary, "rfm_segments", "seg_tbl")
with st.expander("Customer-level RFM table (first 5,000 customers by revenue)"):
    data_table(rfm.sort_values("monetary", ascending=False).head(5000), "rfm_customers", "seg_customers")

section("Data-driven clusters (k-means)", "K-means on log-scaled R, F, M. The number of clusters is the best silhouette score between 2 and 6. Clusters are numbered and described only by their averages.")
cl = sg.cluster_customers(rfm)
if not cl["available"]:
    st.info("Not enough customers (or no variation) to cluster for the current filters.")
else:
    st.write(f"**k = {cl['k']}** clusters, silhouette = **{cl['silhouette']:.2f}** (closer to 1 = better separated; below ~0.25 means weak structure).")
    p = cl["profile"]
    x, y = st.columns(2)
    with x:
        charts.chart_card("Customers per cluster (%)", charts.bar_fig(p.assign(cluster=p["cluster"].astype(str)), "cluster", "customer_share_pct", pct=True), p, "seg_k_share")
    with y:
        import pandas as pd
        sc = pd.DataFrame({"k": list(cl["scores"]), "silhouette": list(cl["scores"].values())})
        charts.chart_card("Silhouette score by number of clusters", charts.line_fig(sc, "k", {"Silhouette": "silhouette"}, "Silhouette"), sc, "seg_k_sil")
    data_table(p, "cluster_profiles", "seg_k_tbl")

section("Cohort retention", f"Of the customers who first bought in a month, the share who bought again k months later. Cohorts under {settings.COHORT_MIN_SIZE} customers are not shown as percentages.")
t = data.q(co.calculate_cohort_retention, f)
if t.empty:
    st.info("No purchases for the current filters.")
else:
    s1, s3 = co.summarize_retention(t, 1), co.summarize_retention(t, 3)
    m1, m2, m3 = st.columns(3)
    m1.metric("Retention after 1 month", pct(s1["retention"]), border=True, help=f"Customer-weighted over {s1['cohorts_used']} cohorts large enough and old enough. A second order in the same month does not count.")
    m2.metric("Retention after 3 months", pct(s3["retention"]), border=True, help=f"Over {s3['cohorts_used']} cohorts.")
    m3.metric("Cohorts shown", number(int((t["months_since"] == 0).sum() - t[t["months_since"] == 0]["is_small"].sum())), border=True)
    mat = co.cohort_matrix(t, 12).dropna(how="all")
    charts.chart_card("Retention % by cohort and months since first purchase", charts.when(mat, lambda: charts.heatmap_fig(mat, "Retention %", 420)),
                      t, "seg_cohort", "Grey/missing cells: cohort too small, or the month is beyond the last month in the data.")
