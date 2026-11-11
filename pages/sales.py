"""Sales Analytics."""
import streamlit as st

from analytics import sales as sl
from components import charts, data
from components.filters import current
from components.formatting import money, number, pct_points
from components.kpi_cards import kpi_row
from components.layout import page_header, section
from components.tables import data_table

f = current()
page_header("Sales Analytics", "Order and revenue patterns over time. Historical 2016–2018 data; growth is observed, not forecast.")

k = data.q(sl.calculate_sales_kpis, f)
kpi_row([
    ("total_revenue", money(k["total_sales"], True), "Total sales (product revenue)"),
    ("total_orders", number(k["total_orders"])),
    ("avg_order_value", money(k["avg_order_value"])),
    ("avg_items_per_order", number(k["avg_items_per_order"], 2)),
    ("avg_freight_value", money(k["avg_freight_value"])),
    ("monthly_growth", pct_points(k["latest_monthly_growth_pct"], signed=True)),
    ("daily_avg_orders", number(k["daily_avg_orders"], 1)),
], per_row=4)

daily = data.q(sl.calculate_daily_sales, f)
monthly = data.q(sl.calculate_monthly_sales, f)
charts.chart_card("Daily revenue", charts.when(daily, lambda: charts.line_fig(daily, "full_date", {"Revenue": "revenue"}, "R$", money=True)), daily, "sales_daily")

c1, c2 = st.columns(2)
with c1:
    charts.chart_card("Month-over-month revenue growth", charts.when(monthly.dropna(subset=["mom_growth_pct"]), lambda: charts.column_fig(monthly.dropna(subset=["mom_growth_pct"]), "year_month", "mom_growth_pct", y_title="% change", labels=False)),
                      monthly[["year_month", "revenue", "orders", "mom_growth_pct", "is_sparse"]], "sales_mom",
                      "Blank where a month or its predecessor is a near-empty edge month.")
with c2:
    yearly = data.q(sl.calculate_yearly_sales, f)
    charts.chart_card("Revenue by year", charts.when(yearly, lambda: charts.column_fig(yearly, "calendar_year", "revenue", money=True)), yearly, "sales_year",
                      "Years are partial (the data starts in late 2016 and ends in 2018); see months_with_sales.")

c3, c4 = st.columns(2)
with c3:
    wd = data.q(sl.calculate_sales_by_weekday, f)
    charts.chart_card("Orders by weekday", charts.when(wd, lambda: charts.column_fig(wd, "weekday_name", "orders")), wd, "sales_weekday")
with c4:
    se = data.q(sl.calculate_sales_seasonality, f)
    charts.chart_card("Seasonality: average revenue per calendar month", charts.when(se, lambda: charts.column_fig(se, "month_name", "avg_monthly_revenue", money=True, labels=False)), se, "sales_season",
                      "Averages over the years observed for each month (years_observed in the table); not adjusted for growth.")

yoy = data.q(sl.calculate_yoy_by_month, f)
charts.chart_card("Revenue vs the same month a year earlier", charts.when(yoy, lambda: charts.line_fig(yoy, "year_month", {"Revenue": "revenue", "Same month, prior year": "prior_year_revenue"}, "R$", money=True)),
                  yoy, "sales_yoy")

section("Order value distribution")
ov = data.q(sl.calculate_order_value_distribution, f)
charts.chart_card("Order value (capped at the 99th percentile)", charts.when(ov, lambda: charts.histogram_fig(ov["order_value"].clip(upper=ov["order_value"].quantile(0.99)), "Order value (R$)")), ov, "sales_ov")

section("Growth tables")
tabs = st.tabs(["Monthly (MoM)", "Quarterly (QoQ)", "Yearly (YoY)", "Peak and decline months"])
for tab, period in zip(tabs[:3], ("month", "quarter", "year")):
    with tab:
        data_table(data.q(sl.calculate_sales_growth, f, period=period), f"sales_growth_{period}", f"sales_g_{period}")
with tabs[3]:
    pk = data.q(sl.identify_peak_sales_periods, f)
    st.markdown("**Top months by revenue**")
    data_table(pk["peak"], "peak_months", "sales_peak")
    st.markdown("**Largest month-over-month declines**")
    data_table(pk["declines"], "decline_months", "sales_decl")
