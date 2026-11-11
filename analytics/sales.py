"""Sales analytics: trends, seasonality, period comparison.

"Sales" = product revenue on revenue orders (excl. freight); "orders" = distinct
revenue orders. Growth figures are observed historical changes, not forecasts.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import (
    Filters,
    item_scope,
    read_sql,
    revenue_by,
    safe_div,
)
from analytics.revenue import calculate_monthly_revenue

_PERIODS = {"month": "month", "quarter": "quarter", "year": "year"}


# -------------------------------------------------------------------- series
def calculate_daily_sales(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per calendar day with sales: revenue, freight, orders, items."""
    return revenue_by(engine, f, "date")


def calculate_monthly_sales(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per month: revenue, orders, mom growth and sparse flag."""
    return calculate_monthly_revenue(engine, f)


def calculate_yearly_sales(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per calendar year: revenue, orders, ``months_with_sales`` (years may be partial)."""
    y = revenue_by(engine, f, "year")
    if y.empty:
        y["months_with_sales"] = pd.Series(dtype=int)
        return y
    months = revenue_by(engine, f, "month")
    months["calendar_year"] = months["year_month"].str[:4].astype(int)
    counts = months.groupby("calendar_year").size().rename("months_with_sales").reset_index()
    return y.merge(counts, on="calendar_year", how="left")


def calculate_sales_by_weekday(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per weekday (Mon..Sun, all seven present): revenue, orders, avg revenue per
    weekday occurrence is not computed here; shares show the weekly pattern."""
    w = revenue_by(engine, f, "weekday")
    base = pd.DataFrame({
        "iso_weekday": range(1, 8),
        "weekday_name": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    })
    out = base.merge(w.drop(columns=["weekday_name"], errors="ignore"), on="iso_weekday", how="left")
    for col in ("revenue", "freight", "orders", "items"):
        out[col] = out[col].fillna(0)
    total = out["revenue"].sum()
    out["revenue_share_pct"] = 100 * out["revenue"] / total if total else np.nan
    return out


def calculate_sales_seasonality(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Average monthly revenue for each calendar month across the years observed
    (``years_observed`` shows how many Januaries, Februaries... contribute). With
    ~2 years of data this is indicative, not a proven seasonal pattern."""
    m = revenue_by(engine, f, "month")
    if m.empty:
        return pd.DataFrame(columns=["calendar_month", "month_name", "avg_monthly_revenue", "years_observed"])
    m["calendar_month"] = m["year_month"].str[5:7].astype(int)
    g = m.groupby("calendar_month").agg(avg_monthly_revenue=("revenue", "mean"),
                                        avg_monthly_orders=("orders", "mean"),
                                        years_observed=("year_month", "nunique")).reset_index()
    g["month_name"] = pd.to_datetime(g["calendar_month"], format="%m").dt.month_name()
    return g[["calendar_month", "month_name", "avg_monthly_revenue", "avg_monthly_orders", "years_observed"]]


# ------------------------------------------------------------------ growth
def calculate_sales_growth(engine: Engine, f: Filters | None = None, period: str = "month") -> pd.DataFrame:
    """Period-over-period growth (``month`` = MoM, ``quarter`` = QoQ, ``year`` = YoY).

    Adds ``revenue_growth_pct`` and ``orders_growth_pct`` (NaN for the first
    period). Partial periods are not hidden: compare ``months_in_period``."""
    if period not in _PERIODS:
        raise ValueError("period must be 'month', 'quarter' or 'year'")
    if period == "month":
        df = calculate_monthly_revenue(engine, f)
        df["period"] = df["year_month"]
        df["revenue_growth_pct"] = df["mom_growth_pct"]
        df["orders_growth_pct"] = 100 * df["orders"].pct_change().where(~df["is_sparse"] & ~df["is_sparse"].shift(1, fill_value=False))
        df["months_in_period"] = 1
        return df[["period", "revenue", "orders", "revenue_growth_pct", "orders_growth_pct", "months_in_period", "is_sparse"]]
    base = revenue_by(engine, f, period)
    months = revenue_by(engine, f, "month")
    if base.empty:
        return pd.DataFrame(columns=["period", "revenue", "orders", "revenue_growth_pct", "orders_growth_pct", "months_in_period"])
    months["calendar_year"] = months["year_month"].str[:4].astype(int)
    months["calendar_quarter"] = (months["year_month"].str[5:7].astype(int) - 1) // 3 + 1
    keys = ["calendar_year", "calendar_quarter"] if period == "quarter" else ["calendar_year"]
    counts = months.groupby(keys).size().rename("months_in_period").reset_index()
    base = base.merge(counts, on=keys, how="left")
    base["period"] = (base["calendar_year"].astype(str) + "-Q" + base["calendar_quarter"].astype(str)
                      if period == "quarter" else base["calendar_year"].astype(str))
    base["revenue_growth_pct"] = 100 * base["revenue"].pct_change()
    base["orders_growth_pct"] = 100 * base["orders"].pct_change()
    return base[["period", "revenue", "orders", "revenue_growth_pct", "orders_growth_pct", "months_in_period"]]


def calculate_yoy_by_month(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Revenue of each calendar month vs the same month a year earlier (only months
    present in both years): year_month, revenue, prior_year_revenue, yoy_growth_pct."""
    m = revenue_by(engine, f, "month")[["year_month", "revenue"]]
    cols = ["year_month", "revenue", "prior_year_revenue", "yoy_growth_pct"]
    if m.empty:
        return pd.DataFrame(columns=cols)
    prior = m.assign(year_month=(m["year_month"].str[:4].astype(int) + 1).astype(str) + m["year_month"].str[4:])
    out = m.merge(prior.rename(columns={"revenue": "prior_year_revenue"}), on="year_month", how="inner")
    out["yoy_growth_pct"] = 100 * (out["revenue"] / out["prior_year_revenue"].replace(0, np.nan) - 1)
    return out[cols]


def _period_metrics(engine: Engine, f: Filters | None, start: date, end: date) -> dict:
    base = f or Filters()
    scoped = Filters(
        date_from=start, date_to=end, states=base.states, categories=base.categories,
        sellers=base.sellers, payment_types=base.payment_types, order_statuses=base.order_statuses)
    s = item_scope(scoped)
    row = read_sql(
        engine,
        "SELECT COALESCE(SUM(i.price), 0) AS revenue, COUNT(DISTINCT i.order_id) AS orders, "
        "COUNT(*) AS items, COALESCE(SUM(i.freight_value), 0) AS freight\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]
    return {"revenue": float(row["revenue"]), "orders": int(row["orders"]), "items": int(row["items"]),
            "freight": float(row["freight"]), "avg_order_value": safe_div(row["revenue"], row["orders"])}


def compare_period_performance(
    engine: Engine, f: Filters | None, period_a: tuple[date, date], period_b: tuple[date, date],
) -> pd.DataFrame:
    """Compare period A with baseline period B (other filters apply to both; the
    date filter in ``f`` is replaced by each period). Columns: metric, period_a,
    period_b, change, change_pct."""
    a = _period_metrics(engine, f, *period_a)
    b = _period_metrics(engine, f, *period_b)
    rows = []
    for metric in ("revenue", "orders", "items", "freight", "avg_order_value"):
        va, vb = a[metric], b[metric]
        change = None if va is None or vb is None else va - vb
        pct = None if not vb or va is None else 100 * (va / vb - 1)
        rows.append({"metric": metric, "period_a": va, "period_b": vb, "change": change, "change_pct": pct})
    return pd.DataFrame(rows)


def identify_peak_sales_periods(
    engine: Engine, f: Filters | None = None, top_n: int = 5, freq: str = "month",
) -> dict[str, pd.DataFrame]:
    """``peak``: the top ``top_n`` periods by revenue; ``declines``: the largest
    period-over-period revenue drops among non-sparse periods (``freq`` is
    ``"month"`` or ``"day"``)."""
    if freq == "month":
        t = calculate_monthly_revenue(engine, f)
        key, growth = "year_month", t["mom_growth_pct"] if not t.empty else pd.Series(dtype=float)
    elif freq == "day":
        t = calculate_daily_sales(engine, f)
        key = "full_date"
        # Day-over-day growth is not reported: days without sales make it misleading.
        growth = pd.Series(np.nan, index=t.index)
    else:
        raise ValueError("freq must be 'month' or 'day'")
    if t.empty:
        return {"peak": t, "declines": t}
    t = t.assign(growth_pct=growth.values)
    peak = t.sort_values(["revenue", key], ascending=[False, True]).head(top_n)
    declines = t[t["growth_pct"] < 0].sort_values("growth_pct").head(top_n)
    return {"peak": peak.reset_index(drop=True), "declines": declines.reset_index(drop=True)}


def calculate_average_items_per_order(engine: Engine, f: Filters | None = None) -> float | None:
    """Items / distinct revenue orders."""
    s = item_scope(f)
    row = read_sql(engine, "SELECT COUNT(*) AS items, COUNT(DISTINCT i.order_id) AS orders\n"
                           f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]
    return safe_div(row["items"], row["orders"])


def calculate_average_freight_value(engine: Engine, f: Filters | None = None) -> float | None:
    """Freight per revenue order (sum of freight / distinct orders)."""
    s = item_scope(f)
    row = read_sql(engine, "SELECT COALESCE(SUM(i.freight_value), 0) AS freight, "
                           "COUNT(DISTINCT i.order_id) AS orders\n"
                           f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]
    return safe_div(row["freight"], row["orders"])


def calculate_order_value_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per-order product revenue (order_id, order_value) for histograms."""
    from analytics.revenue import calculate_revenue_distribution
    return calculate_revenue_distribution(engine, f)["orders"]


def calculate_sales_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """KPI-card values for the Sales Analytics page.

    ``daily_avg_orders`` = orders / calendar days from the first to the last
    purchase in scope (days without sales count)."""
    s = item_scope(f)
    row = read_sql(
        engine,
        "SELECT COALESCE(SUM(i.price), 0) AS revenue, COUNT(DISTINCT i.order_id) AS orders, "
        "MIN(o.purchase_ts)::date AS first_day, MAX(o.purchase_ts)::date AS last_day\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]
    orders = int(row["orders"])
    days = None
    if orders and pd.notna(row["first_day"]):
        days = (pd.Timestamp(row["last_day"]) - pd.Timestamp(row["first_day"])).days + 1
    growth = calculate_monthly_revenue(engine, f)
    latest_growth = None
    if not growth.empty and growth["mom_growth_pct"].notna().any():
        latest_growth = float(growth["mom_growth_pct"].dropna().iloc[-1])
    return {
        "total_sales": float(row["revenue"]), "total_orders": orders,
        "avg_order_value": safe_div(row["revenue"], orders),
        "avg_items_per_order": calculate_average_items_per_order(engine, f),
        "avg_freight_value": calculate_average_freight_value(engine, f),
        "latest_monthly_growth_pct": latest_growth,
        "daily_avg_orders": safe_div(orders, days), "days_in_range": days,
    }
