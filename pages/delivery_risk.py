"""Delivery Risk: a late-delivery model with an honest evaluation."""
import pandas as pd
import streamlit as st

from analytics import delivery_model as dm
from components import charts, data
from components.filters import current
from components.formatting import pct
from components.layout import page_header, section
from components.tables import data_table
from config import settings

f = current()
page_header("Delivery Risk", "How likely is an order to arrive after its estimated date, judged from what is known at purchase time?")
st.info("The model is trained on the **oldest 75%** of delivered orders and evaluated on the **newest 25%**, so it is judged on a period it never saw. "
        "It uses no information that appears after the purchase. It scores risk to prioritise checks; it does not explain causes.")


@st.cache_data(ttl=settings.CACHE_TTL_SECONDS, show_spinner="Training the model…", max_entries=4)
def _train(filters):
    d = dm.load_delivery_dataset(data.engine(), filters)
    return dm.train_delivery_risk_model(d)


if st.button("Train / refresh model for current filters", type="primary", key="dr_train"):
    st.session_state["dr_key"] = f
if st.session_state.get("dr_key") != f:
    st.caption("Training uses the sidebar filters and takes a few seconds on the full data. Press the button to start.")
    st.stop()

res = _train(f)
if not res["available"]:
    st.warning(res["reason"])
    st.stop()

mt = res["metrics"]
main = mt["main_model"]
per = res["period"]
st.write(f"Trained on **{res['n_train']:,}** orders ({per['train_from']} to {per['train_to']}); tested on **{res['n_test']:,}** orders "
         f"({per['test_from']} to {per['test_to']}). Late rate in the test period: **{pct(mt['base_rate_test'])}**.")
if res["usable"]:
    st.success(f"{main} separates late from on-time orders clearly better than chance on unseen data.")
else:
    st.error("The model is **not informative enough** on unseen data (AUC < 0.60 or precision barely above the base rate). Do not use its scores.")

rows = [{"model": k, "ROC AUC": v["roc_auc"], "Average precision": v["average_precision"], "Brier score (lower is better)": v["brier"]}
        for k, v in mt.items() if isinstance(v, dict)]
section("Test-set performance", "ROC AUC: 0.5 = no better than chance, 1 = perfect. Average precision is compared with the base rate (a random ranking scores the base rate).")
data_table(pd.DataFrame(rows), "delivery_model_metrics", "dr_metrics")

c1, c2 = st.columns(2)
with c1:
    d = res["deciles"]
    charts.chart_card("Actual late rate by predicted-risk decile (test period)", charts.bar_fig(d.assign(late_pct=100 * d["actual_late_rate"], decile=d["decile"].astype(str)), "decile", "late_pct", horizontal=False, pct=True),
                      d, "dr_deciles", "Decile 10 = orders the model scored riskiest. A useful model has a clearly rising pattern.")
with c2:
    imp = res["importance"].head(10)
    charts.chart_card("What the model relies on (drop in AUC when shuffled)", charts.bar_fig(imp, "feature", "auc_drop"), res["importance"], "dr_imp",
                      "Importance shows reliance, not cause. Correlated features (e.g. state and distance) share credit.")

section("Try a scenario", "Risk estimate for one hypothetical order, from the trained model.")
opts = data.filter_options()
with st.form("dr_scenario"):
    a, b, c = st.columns(3)
    cs = a.selectbox("Customer state", opts["states"])
    ss = b.selectbox("Seller state", opts["states"])
    dist = c.number_input("Distance customer–seller (km)", 0.0, 4500.0, 500.0, 50.0)
    d1, d2, d3 = st.columns(3)
    est = d1.number_input("Estimated delivery time (days)", 1.0, 120.0, 20.0, 1.0)
    freight = d2.number_input("Freight (R$)", 0.0, 500.0, 20.0, 1.0)
    value = d3.number_input("Items value (R$)", 1.0, 20000.0, 100.0, 10.0)
    weight = st.number_input("Total weight (g)", 0.0, 100000.0, 1000.0, 100.0)
    go_ = st.form_submit_button("Estimate risk")
if go_:
    risk = dm.predict_risk(res["model"], dict(customer_state=cs, seller_state=ss, category="unknown", distance_km=dist, same_state=float(cs == ss), item_count=1, seller_count=1,
                                              items_value=value, freight_value=freight, freight_ratio=freight / value, total_weight_g=weight,
                                              estimated_delivery_days=est, purchase_month=6, purchase_weekday=3))
    st.metric("Estimated probability of arriving late", pct(risk), border=True, help=f"Compare with the overall late rate of {pct(mt['base_rate_train'])} in the training period.")
