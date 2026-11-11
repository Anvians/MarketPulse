"""Customer analytics.

A "customer" is a person (``customer_unique_id``). Only *revenue orders*
(not canceled/unavailable, >= 1 item) count as purchases.

Scope rules
-----------
* Counts, frequency, repeat status and revenue are computed on the purchases
  that fall **inside the active filters**. With a date filter, "repeat" means
  more than one purchase *within that window*.
* "New customer" is different: it uses each person's **first-ever** purchase
  (over all data, ignoring filters) and asks whether that first purchase lies
  in the filtered scope. So a returning buyer is never mislabelled "new" just
  because the date window starts after their first order.
* Lifetime revenue is *observed* revenue within the data, not a prediction.
  The marketplace has low repeat purchasing; nothing here inflates retention.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import (
    Filters,
    item_scope,
    order_scope,
    read_sql,
    safe_div,
    scalar,
    summarize_numeric,
)
from config import settings

FREQUENCY_SEGMENTS = ("one_time", "repeat", "loyal")  # 1 order, 2 orders, 3+ orders


def _frequency_segment(orders: int) -> str:
    return "one_time" if orders == 1 else ("repeat" if orders == 2 else "loyal")


def _purchases(engine: Engine, f: Filters | None) -> pd.DataFrame:
    """One row per revenue order in scope: customer, time, state, revenue."""
    s = item_scope(f)
    sql = (
        "SELECT o.order_id, o.customer_unique_id, o.purchase_ts, o.customer_state AS state, "
        "d.year_month, SUM(i.price) AS revenue\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\n"
        "GROUP BY o.order_id, o.customer_unique_id, o.purchase_ts, o.customer_state, d.year_month"
    )
    return read_sql(engine, sql, s.params)


# --------------------------------------------------------------------- counts
def calculate_total_customers(engine: Engine, f: Filters | None = None) -> int:
    """Distinct people with >= 1 revenue order in scope."""
    s = order_scope(f)
    return int(scalar(
        engine,
        f"SELECT COUNT(DISTINCT o.customer_unique_id) FROM {s.from_sql}\n{s.where('o.is_revenue_order')}",
        s.params,
    ) or 0)


def calculate_repeat_purchase_rate(engine: Engine, f: Filters | None = None) -> float | None:
    """People with > 1 distinct revenue order / people with >= 1 revenue order
    (fraction; None when there are no customers)."""
    s = order_scope(f)
    sql = (
        "WITH c AS (SELECT o.customer_unique_id, COUNT(*) AS n "
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')} GROUP BY 1)\n"
        "SELECT COUNT(*) FILTER (WHERE n > 1) AS repeaters, COUNT(*) AS total FROM c"
    )
    row = read_sql(engine, sql, s.params).iloc[0]
    return safe_div(row["repeaters"], row["total"])


def calculate_average_orders_per_customer(engine: Engine, f: Filters | None = None) -> float | None:
    """Revenue orders / distinct customers."""
    s = order_scope(f)
    sql = (
        f"SELECT COUNT(*) AS orders, COUNT(DISTINCT o.customer_unique_id) AS customers "
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}"
    )
    row = read_sql(engine, sql, s.params).iloc[0]
    return safe_div(row["orders"], row["customers"])


# ------------------------------------------------------------ new vs repeat
_FIRST_ORDERS_CTE = (
    "first_orders AS (SELECT customer_unique_id, MIN(purchase_ts) AS first_purchase_ts "
    "FROM fact_orders WHERE is_revenue_order GROUP BY 1)"
)


def identify_new_customers(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """People whose first-ever revenue order lies in the filtered scope.

    Columns: customer_unique_id, first_purchase_ts, first_month, state."""
    s = order_scope(f)
    sql = (
        f"WITH {_FIRST_ORDERS_CTE}\n"
        "SELECT DISTINCT o.customer_unique_id, fo.first_purchase_ts, "
        "to_char(fo.first_purchase_ts, 'YYYY-MM') AS first_month, o.customer_state AS state\n"
        f"FROM {s.from_sql}\n"
        "JOIN first_orders fo ON fo.customer_unique_id = o.customer_unique_id "
        "AND fo.first_purchase_ts = o.purchase_ts\n"
        f"{s.where('o.is_revenue_order')}\nORDER BY fo.first_purchase_ts"
    )
    return read_sql(engine, sql, s.params)


def calculate_monthly_customer_acquisition(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """New customers per month (month of first-ever purchase)."""
    new = identify_new_customers(engine, f)
    if new.empty:
        return pd.DataFrame(columns=["year_month", "new_customers"])
    out = new.groupby("first_month")["customer_unique_id"].nunique().reset_index()
    out.columns = ["year_month", "new_customers"]
    return out.sort_values("year_month").reset_index(drop=True)


def calculate_new_vs_returning(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per purchase month: customers buying for the first time ever (``new``) vs
    customers who had bought in an earlier month (``returning``). Customers who
    placed two orders in their first month count as ``new`` once."""
    s = order_scope(f)
    sql = (
        f"WITH {_FIRST_ORDERS_CTE}\n"
        "SELECT DISTINCT d.year_month, o.customer_unique_id, "
        "(to_char(fo.first_purchase_ts, 'YYYY-MM') = d.year_month) AS is_new\n"
        f"FROM {s.from_sql}\n"
        "JOIN first_orders fo ON fo.customer_unique_id = o.customer_unique_id\n"
        f"{s.where('o.is_revenue_order')}"
    )
    df = read_sql(engine, sql, s.params)
    if df.empty:
        return pd.DataFrame(columns=["year_month", "new_customers", "returning_customers"])
    grouped = df.groupby(["year_month", "is_new"])["customer_unique_id"].nunique().unstack(fill_value=0)
    out = pd.DataFrame({
        "year_month": grouped.index,
        "new_customers": grouped.get(True, 0),
        "returning_customers": grouped.get(False, 0),
    }).reset_index(drop=True)
    return out.sort_values("year_month").reset_index(drop=True)


# ------------------------------------------------------------ per-customer
def calculate_customer_revenue(
    engine: Engine, f: Filters | None = None, limit: int | None = None
) -> pd.DataFrame:
    """One row per customer: orders, revenue, avg_order_value, first/last purchase,
    state (of the latest order) and frequency_segment. Sorted by revenue desc."""
    p = _purchases(engine, f)
    cols = ["customer_unique_id", "orders", "revenue", "avg_order_value",
            "first_purchase_ts", "last_purchase_ts", "state", "frequency_segment"]
    if p.empty:
        return pd.DataFrame(columns=cols)
    p = p.sort_values("purchase_ts")
    g = p.groupby("customer_unique_id").agg(
        orders=("order_id", "nunique"), revenue=("revenue", "sum"),
        first_purchase_ts=("purchase_ts", "min"), last_purchase_ts=("purchase_ts", "max"),
        state=("state", "last"),
    ).reset_index()
    g["avg_order_value"] = g["revenue"] / g["orders"]
    g["frequency_segment"] = g["orders"].map(_frequency_segment)
    g = g.sort_values(["revenue", "customer_unique_id"], ascending=[False, True]).reset_index(drop=True)
    g = g[cols]
    return g.head(limit) if limit else g


def identify_repeat_customers(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Customers with > 1 revenue order in scope."""
    c = calculate_customer_revenue(engine, f)
    return c[c["orders"] > 1].reset_index(drop=True)


def identify_single_purchase_customers(engine: Engine, f: Filters | None = None) -> dict:
    """Count, share of customers and share of revenue of one-order customers."""
    c = calculate_customer_revenue(engine, f)
    if c.empty:
        return {"customers": 0, "customer_share": None, "revenue": 0.0, "revenue_share": None}
    one = c[c["orders"] == 1]
    return {
        "customers": int(len(one)),
        "customer_share": len(one) / len(c),
        "revenue": float(one["revenue"].sum()),
        "revenue_share": safe_div(one["revenue"].sum(), c["revenue"].sum()),
    }


def calculate_customer_frequency(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Distribution of orders per customer: orders, customers, customer_share."""
    c = calculate_customer_revenue(engine, f)
    if c.empty:
        return pd.DataFrame(columns=["orders", "customers", "customer_share"])
    out = c.groupby("orders").size().reset_index(name="customers")
    out["customer_share"] = out["customers"] / out["customers"].sum()
    return out


def calculate_customer_lifetime_revenue(engine: Engine, f: Filters | None = None) -> dict:
    """Observed revenue per customer within scope (mean/median/p90...). Not a
    forecast of future value."""
    c = calculate_customer_revenue(engine, f)
    return summarize_numeric(c["revenue"]) if not c.empty else summarize_numeric(pd.Series(dtype=float))


def identify_high_value_customers(
    engine: Engine, f: Filters | None = None, quantile: float = settings.HIGH_VALUE_QUANTILE
) -> pd.DataFrame:
    """Customers whose revenue is >= the ``quantile`` of customer revenue (default
    top 10%). Adds ``revenue_share_pct`` (share of total revenue)."""
    c = calculate_customer_revenue(engine, f)
    if c.empty:
        return c.assign(revenue_share_pct=pd.Series(dtype=float))
    threshold = c["revenue"].quantile(quantile)
    top = c[c["revenue"] >= threshold].copy()
    top["revenue_share_pct"] = 100 * top["revenue"] / c["revenue"].sum()
    return top.reset_index(drop=True)


def calculate_revenue_by_customer_type(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Revenue, customers and average revenue per frequency segment
    (one_time = 1 order, repeat = 2, loyal = 3+). RFM segments come in Milestone 5."""
    c = calculate_customer_revenue(engine, f)
    cols = ["frequency_segment", "customers", "revenue", "avg_revenue_per_customer", "revenue_share_pct"]
    if c.empty:
        return pd.DataFrame(columns=cols)
    g = c.groupby("frequency_segment").agg(customers=("customer_unique_id", "size"),
                                           revenue=("revenue", "sum")).reset_index()
    g["avg_revenue_per_customer"] = g["revenue"] / g["customers"]
    g["revenue_share_pct"] = 100 * g["revenue"] / g["revenue"].sum()
    order = {name: n for n, name in enumerate(FREQUENCY_SEGMENTS)}
    return g.sort_values("frequency_segment", key=lambda s: s.map(order)).reset_index(drop=True)


def calculate_customers_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Distinct customers, orders and revenue per customer state (state of each
    order; a person who moved is counted in each state they bought from)."""
    p = _purchases(engine, f)
    if p.empty:
        return pd.DataFrame(columns=["state", "customers", "orders", "revenue", "customer_share_pct"])
    g = p.groupby("state").agg(customers=("customer_unique_id", "nunique"),
                               orders=("order_id", "nunique"), revenue=("revenue", "sum")).reset_index()
    g["customer_share_pct"] = 100 * g["customers"] / g["customers"].sum()
    return g.sort_values(["customers", "state"], ascending=[False, True]).reset_index(drop=True)


def calculate_customer_revenue_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per-customer revenue (for histograms): customer_unique_id, revenue."""
    return calculate_customer_revenue(engine, f)[["customer_unique_id", "revenue"]]


def identify_customer_purchase_patterns(engine: Engine, f: Filters | None = None) -> dict:
    """Timing and value patterns of repeat buyers.

    ``avg_days_between_orders`` is the mean gap between consecutive orders of
    repeat customers; ``avg_days_to_second_order`` the mean gap from first to
    second order. Values are None when there are no repeat customers."""
    p = _purchases(engine, f)
    result: dict = {
        "repeat_customers": 0, "repeat_order_share": None,
        "avg_days_between_orders": None, "median_days_between_orders": None,
        "avg_days_to_second_order": None,
        "avg_order_value_repeat_customers": None, "avg_order_value_single_customers": None,
    }
    if p.empty:
        return result
    p = p.sort_values(["customer_unique_id", "purchase_ts"])
    counts = p.groupby("customer_unique_id")["order_id"].transform("nunique")
    repeat = p[counts > 1].copy()
    single = p[counts == 1]
    result["avg_order_value_single_customers"] = float(single["revenue"].mean()) if len(single) else None
    if repeat.empty:
        return result
    repeat["gap_days"] = repeat.groupby("customer_unique_id")["purchase_ts"].diff().dt.total_seconds() / 86400
    second = repeat.groupby("customer_unique_id").nth(1)
    result.update({
        "repeat_customers": int(repeat["customer_unique_id"].nunique()),
        "repeat_order_share": len(repeat) / len(p),
        "avg_days_between_orders": float(repeat["gap_days"].mean()),
        "median_days_between_orders": float(repeat["gap_days"].median()),
        "avg_days_to_second_order": float(second["gap_days"].mean()),
        "avg_order_value_repeat_customers": float(repeat["revenue"].mean()),
    })
    return result


def calculate_customer_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """All KPI-card values for the Customer Analytics page."""
    c = calculate_customer_revenue(engine, f)
    total = int(len(c))
    new = identify_new_customers(engine, f)
    repeat = int((c["orders"] > 1).sum()) if total else 0
    return {
        "total_customers": total,
        "new_customers": int(len(new)),
        "repeat_customers": repeat,
        "repeat_purchase_rate": safe_div(repeat, total),
        "avg_customer_revenue": float(c["revenue"].mean()) if total else None,
        "avg_orders_per_customer": float(c["orders"].mean()) if total else None,
        "observed_lifetime_revenue_median": float(c["revenue"].median()) if total else None,
    }
