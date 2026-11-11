"""Statistical Tests: significance plus effect size, with plain-language readings."""
import streamlit as st

from analytics import stats_tests as stt
from components import data
from components.filters import current
from components.layout import page_header, section
from components.tables import data_table

f = current()
page_header("Statistical Tests", "Are the differences seen in the dashboards bigger than chance, and do they matter? Delivered orders with valid dates only.")
st.info("With tens of thousands of orders almost any difference is 'statistically significant'. Read the **effect size** first: it says whether a difference is big enough to matter. "
        "Tests show association, never cause.")

df = data.q(stt.load_order_facts, f)
if df.empty:
    st.info("No delivered orders for the current filters.")
    st.stop()

section("Confidence intervals", "95% intervals show how precisely the headline numbers are estimated from these orders.")
ci = stt.confidence_intervals(df)
data_table(ci, "confidence_intervals", "st_ci")

section("Tests")
for r in stt.run_all_tests(df):
    with st.container(border=True):
        st.markdown(f"**{r['test']}**")
        if not r["available"]:
            st.caption(r["reason"])
            continue
        a, b, c = st.columns(3)
        a.metric("p-value", "< 0.001" if r["p_value"] < 0.001 else f"{r['p_value']:.3f}", help="Probability of a difference at least this large if there were truly none. Small p says 'unlikely to be chance', not 'important'.")
        b.metric("Effect size", f"{r['effect_size']:.3f}", help=r["effect_name"])
        c.metric("Magnitude", r["magnitude"].capitalize())
        st.write(r["reading"])
        if "late_rate_by_payment" in r:
            data_table(r["late_rate_by_payment"], "late_rate_by_payment", "st_pay")
st.caption("Several tests are shown, and no multiple-comparison correction is applied; do not lean on a single borderline p-value.")
