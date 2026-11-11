"""Executive dashboard metrics and automatic insights.

KPI definitions
---------------
* Total revenue          = sum(item price) over revenue orders (excl. freight; not profit)
* Total orders           = distinct revenue orders
* Total customers        = distinct ``customer_unique_id`` with a revenue order
* Average order value    = total revenue / total orders
* Average customer rev.  = total revenue / total customers
* Average review score   = mean of the latest review of each revenue order that has one
* Repeat purchase rate   = customers with > 1 revenue order / customers
* On-time / late rate    = on-time (late) deliveries / delivered orders with valid dates
Rates are fractions in [0, 1]; ``None`` means not computable.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import (
    Filters,
    Insight,
    item_scope,
    order_scope,
    read_sql,
    revenue_by,
    safe_div,
    scalar,
)
from analytics.customers import calculate_repeat_purchase_rate
from analytics.logistics import (
    calculate_late_delivery_rate,
    calculate_on_time_delivery_rate,
)
from analytics.revenue import calculate_monthly_revenue, calculate_revenue_growth
from config import settings

__all__ = [
    "calculate_total_revenue", "calculate_total_orders", "calculate_total_customers",
    "calculate_average_order_value", "calculate_average_customer_revenue",
    "calculate_average_review_score", "calculate_repeat_purchase_rate",
    "calculate_on_time_delivery_rate", "calculate_late_delivery_rate",
    "get_monthly_revenue", "get_monthly_orders", "get_top_categories", "get_revenue_by_state",
    "get_payment_distribution", "get_order_status_distribution", "get_review_trend",
    "calculate_executive_kpis", "generate_executive_insights",
]


def _revenue_row(engine: Engine, f: Filters | None) -> pd.Series:
    s = item_scope(f)
    return read_sql(
        engine,
        "SELECT COALESCE(SUM(i.price), 0) AS revenue, COUNT(DISTINCT i.order_id) AS orders, "
        "COUNT(DISTINCT o.customer_unique_id) AS customers\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]


def calculate_total_revenue(engine: Engine, f: Filters | None = None) -> float:
    return float(_revenue_row(engine, f)["revenue"])


def calculate_total_orders(engine: Engine, f: Filters | None = None) -> int:
    return int(_revenue_row(engine, f)["orders"])


def calculate_total_customers(engine: Engine, f: Filters | None = None) -> int:
    return int(_revenue_row(engine, f)["customers"])


def calculate_average_order_value(engine: Engine, f: Filters | None = None) -> float | None:
    r = _revenue_row(engine, f)
    return safe_div(r["revenue"], r["orders"])


def calculate_average_customer_revenue(engine: Engine, f: Filters | None = None) -> float | None:
    r = _revenue_row(engine, f)
    return safe_div(r["revenue"], r["customers"])


def calculate_average_review_score(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean of one (latest) review per revenue order that has a review."""
    s = order_scope(f)
    return scalar(
        engine,
        "SELECT AVG(r.review_score)\n"
        f"FROM {s.from_sql}\nJOIN vw_order_review r ON r.order_id = o.order_id\n{s.where('o.is_revenue_order')}",
        s.params)


def get_monthly_revenue(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return calculate_monthly_revenue(engine, f)[["year_month", "revenue", "is_sparse"]]


def get_monthly_orders(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return calculate_monthly_revenue(engine, f)[["year_month", "orders", "is_sparse"]]


def get_top_categories(engine: Engine, f: Filters | None = None, top_n: int = 10) -> pd.DataFrame:
    return revenue_by(engine, f, "category", top_n)


def get_revenue_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "state")


def get_payment_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Revenue orders per primary payment type: payment_type, orders, revenue, order_share_pct."""
    p = revenue_by(engine, f, "payment")
    if p.empty:
        return p.assign(order_share_pct=pd.Series(dtype=float))
    p["order_share_pct"] = 100 * p["orders"] / p["orders"].sum()
    return p


def get_order_status_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """All orders in scope (any status): order_status, orders, share_pct."""
    s = order_scope(f)
    df = read_sql(engine, "SELECT o.order_status, COUNT(*) AS orders\n"
                          f"FROM {s.from_sql}\n{s.where()}\nGROUP BY 1 ORDER BY orders DESC, 1", s.params)
    df["share_pct"] = 100 * df["orders"] / df["orders"].sum() if not df.empty else pd.Series(dtype=float)
    return df


def get_review_trend(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Average review score and review count by purchase month (revenue orders)."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT d.year_month, AVG(r.review_score) AS avg_review_score, COUNT(r.review_score) AS reviews\n"
        f"FROM {s.from_sql}\nJOIN vw_order_review r ON r.order_id = o.order_id\n"
        f"{s.where('o.is_revenue_order')}\nGROUP BY 1 ORDER BY 1", s.params)


def calculate_executive_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """All nine KPI-card values."""
    r = _revenue_row(engine, f)
    return {
        "total_revenue": float(r["revenue"]),
        "total_orders": int(r["orders"]),
        "total_customers": int(r["customers"]),
        "avg_order_value": safe_div(r["revenue"], r["orders"]),
        "avg_customer_revenue": safe_div(r["revenue"], r["customers"]),
        "avg_review_score": calculate_average_review_score(engine, f),
        "repeat_purchase_rate": calculate_repeat_purchase_rate(engine, f),
        "on_time_delivery_rate": calculate_on_time_delivery_rate(engine, f),
        "late_delivery_rate": calculate_late_delivery_rate(engine, f),
    }


def generate_executive_insights(engine: Engine, f: Filters | None = None) -> list[Insight]:
    """Findings generated from the data by explicit rules (each Insight carries its rule)."""
    insights: list[Insight] = []
    monthly = calculate_monthly_revenue(engine, f)
    if monthly.empty:
        return [Insight("No sales in the selected scope", "No revenue orders match the active filters.",
                        "info", "total_revenue", "revenue orders in scope == 0")]

    best = monthly.sort_values(["revenue", "year_month"], ascending=[False, True]).iloc[0]
    insights.append(Insight(
        f"Highest revenue month: {best['year_month']}",
        f"{best['year_month']} generated {best['revenue']:,.2f} in product revenue from {int(best['orders']):,} orders.",
        "info", "monthly_revenue", "month with maximum product revenue",
        {"month": best["year_month"], "revenue": float(best["revenue"])}))

    cats = revenue_by(engine, f, "category", limit=1)
    if not cats.empty:
        c = cats.iloc[0]
        insights.append(Insight(
            f"Best-performing category: {c['category']}",
            f"{c['category']} contributes {c['revenue_share_pct']:.1f}% of product revenue.",
            "info", "category_revenue", "category with maximum product revenue",
            {"category": c["category"], "share_pct": float(c["revenue_share_pct"])}))

    states = revenue_by(engine, f, "state", limit=1)
    if not states.empty:
        st = states.iloc[0]
        insights.append(Insight(
            f"Highest revenue state: {st['state']}",
            f"{st['state']} accounts for {st['revenue_share_pct']:.1f}% of product revenue.",
            "info", "state_revenue", "state with maximum product revenue",
            {"state": st["state"], "share_pct": float(st["revenue_share_pct"])}))

    g = calculate_revenue_growth(engine, f)
    if g["available"] and g["growth_pct"] is not None:
        up = g["growth_pct"] >= 0
        note = (f" Sparse months excluded from the comparison: {', '.join(g['excluded_sparse_months'])}."
                if g["excluded_sparse_months"] else "")
        insights.append(Insight(
            f"Revenue {'grew' if up else 'declined'} {abs(g['growth_pct']):.1f}% ({g['previous_month']} to {g['latest_month']})",
            f"Product revenue moved from {g['previous_revenue']:,.2f} to {g['latest_revenue']:,.2f}. "
            f"This is observed historical change, not a forecast.{note}",
            "positive" if up else "warning", "revenue_growth",
            "latest vs previous non-sparse month", {k: g[k] for k in ("growth_pct", "latest_month", "previous_month")}))

    repeat = calculate_repeat_purchase_rate(engine, f)
    if repeat is not None:
        weak = repeat < settings.LOW_REPEAT_RATE
        insights.append(Insight(
            f"Customer retention is {'weak' if weak else 'moderate'}: {repeat:.1%} bought more than once",
            f"{repeat:.1%} of customers placed more than one order in scope."
            + (" Most revenue comes from one-time buyers, which makes acquisition cost and win-back the key levers."
               if weak else ""),
            "warning" if weak else "info", "repeat_purchase_rate",
            f"repeat rate < {settings.LOW_REPEAT_RATE:.0%} is flagged", {"repeat_rate": repeat}))

    late = calculate_late_delivery_rate(engine, f)
    if late is not None:
        flagged = late > settings.LATE_RATE_WARNING
        insights.append(Insight(
            f"Delivery performance {'needs attention' if flagged else 'is acceptable'}: {late:.1%} of orders arrived late",
            f"{late:.1%} of delivered orders arrived after the estimated date.",
            "warning" if flagged else "positive", "late_delivery_rate",
            f"late rate > {settings.LATE_RATE_WARNING:.0%} is flagged", {"late_rate": late}))

    reviews = calculate_average_review_score(engine, f)
    if reviews is not None and reviews < settings.LOW_REVIEW_THRESHOLD:
        insights.append(Insight(
            f"Average review score is low: {reviews:.2f}", "Customer satisfaction is below the alert threshold.",
            "warning", "avg_review_score", f"average review < {settings.LOW_REVIEW_THRESHOLD}", {"avg_review": reviews}))
    return insights
