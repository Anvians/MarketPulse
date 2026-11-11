"""Revenue Forecast with a visible backtest."""
import streamlit as st

from analytics import forecasting as fc
from components import charts, data, theme
from components.filters import current
from components.layout import page_header, section
from components.tables import data_table
import plotly.graph_objects as go

f = current()
page_header("Revenue Forecast", "A short-horizon projection of product revenue, shown together with how well the same method predicted recent months.")
st.warning("This projects **2016–2018 history** forward to illustrate the method; it says nothing about today's business. Seasonality is not modelled "
           "(about two years of data cannot support it), and large one-off peaks such as Black Friday are not anticipated.")

res = data.q(fc.forecast_revenue, f)
if not res["available"]:
    st.info(res["reason"])
    st.stop()

m = res["metrics"]
a, b, c = st.columns(3)
a.metric("Backtest error: model (MAPE)", f"{m['mape_model']:.1f}%" if m["mape_model"] is not None else "n/a", border=True,
         help=f"Mean absolute % error of one-month-ahead forecasts over the last {m['backtest_months']} months, each refit using only earlier months.")
b.metric("Backtest error: naive 'same as last month'", f"{m['mape_naive']:.1f}%" if m["mape_naive"] is not None else "n/a", border=True)
c.metric("Months of history used", str(res["n_months"]), border=True, help="Full months only; near-empty edge months are excluded.")
if m["beats_naive"]:
    st.success("The model beat the naive rule in the backtest, so the forecast carries some information beyond 'next month = this month'.")
else:
    st.error("The model did **not** beat the naive rule in the backtest. Treat the forecast as no better than 'next month = this month'.")

hist, fcst, bt = res["history"], res["forecast"], res["backtest"]
fig = go.Figure()
fig.add_scatter(x=hist["month"], y=hist["revenue"], name="Actual", mode="lines+markers", line=dict(color=theme.BLUE, width=2.5))
fig.add_scatter(x=fcst["month"], y=fcst["upper"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
fig.add_scatter(x=fcst["month"], y=fcst["lower"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(235,104,52,0.18)", name="Approx. 95% range", hoverinfo="skip")
fig.add_scatter(x=fcst["month"], y=fcst["forecast"], name="Forecast", mode="lines+markers", line=dict(color=theme.ORANGE, width=2.5, dash="dash"))
fig.update_yaxes(title_text="Revenue (R$)", tickprefix="R$ ")
fig.update_layout(template="marketpulse", height=400, paper_bgcolor=theme.SURFACE, plot_bgcolor=theme.SURFACE)
charts.chart_card("Monthly product revenue and forecast", fig, fcst, "fc_main",
                  "The range comes from the spread of backtest errors and is approximate. Revenue is product revenue, not profit.")

section("How the method did on recent months")
fig2 = go.Figure()
fig2.add_scatter(x=bt["month"], y=bt["actual"], name="Actual", mode="lines+markers", line=dict(color=theme.BLUE, width=2.5))
fig2.add_scatter(x=bt["month"], y=bt["model"], name="Model (one month ahead)", mode="lines+markers", line=dict(color=theme.ORANGE, width=2.5))
fig2.add_scatter(x=bt["month"], y=bt["naive"], name="Naive (last month)", mode="lines+markers", line=dict(color=theme.NEUTRAL, width=2, dash="dot"))
fig2.update_yaxes(title_text="Revenue (R$)", tickprefix="R$ ")
fig2.update_layout(template="marketpulse", height=340, paper_bgcolor=theme.SURFACE, plot_bgcolor=theme.SURFACE)
charts.chart_card("Backtest: predictions vs actual", fig2, bt, "fc_bt")
data_table(fcst, "revenue_forecast", "fc_tbl")
