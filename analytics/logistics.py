"""Logistics analytics.

Delivery performance uses only orders with ``has_valid_delivery_dates``:
status ``delivered``, purchase / delivery / estimated dates present and delivery
not before purchase. "Late" compares dates (delivered date > estimated date).
Rates are fractions. Freight is order-level here; for per-category freight see
:func:`calculate_freight_by_category` (item level).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from analytics import sellers as sellers_mod
from analytics.base import (
    Filters,
    flag_sparse_months,
    item_scope,
    order_scope,
    read_sql,
    safe_div,
    scalar,
)
from config import settings

_VALID = "o.has_valid_delivery_dates"


def _one(engine: Engine, f: Filters | None, select: str, extra: str = _VALID) -> float | int | None:
    s = order_scope(f)
    return scalar(engine, f"SELECT {select} FROM {s.from_sql}\n{s.where(extra)}", s.params)


# ----------------------------------------------------------------------- KPIs
def calculate_delivered_orders(engine: Engine, f: Filters | None = None) -> int:
    """Orders with status ``delivered`` (whether or not their dates are valid)."""
    return int(_one(engine, f, "COUNT(*)", "o.order_status = 'delivered'") or 0)


def calculate_valid_delivery_orders(engine: Engine, f: Filters | None = None) -> int:
    """Delivered orders with consistent dates: the denominator of all delivery rates."""
    return int(_one(engine, f, "COUNT(*)") or 0)


def calculate_on_time_delivery_rate(engine: Engine, f: Filters | None = None) -> float | None:
    """Delivered on/before the estimated date / delivered orders with valid dates."""
    return safe_div(_one(engine, f, "COUNT(*) FILTER (WHERE NOT o.is_late)"), calculate_valid_delivery_orders(engine, f))


def calculate_late_delivery_rate(engine: Engine, f: Filters | None = None) -> float | None:
    """Delivered after the estimated date / delivered orders with valid dates."""
    return safe_div(_one(engine, f, "COUNT(*) FILTER (WHERE o.is_late)"), calculate_valid_delivery_orders(engine, f))


def calculate_average_delivery_time(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean days from purchase to delivery."""
    return _one(engine, f, "AVG(o.delivery_days)")


def calculate_average_delivery_delay(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean (delivered date - estimated date) in days; negative = early on average."""
    return _one(engine, f, "AVG(o.delivery_delay_days)")


def calculate_average_delay_of_late_orders(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean days late among late orders only."""
    return _one(engine, f, "AVG(o.delivery_delay_days)", f"{_VALID} AND o.is_late")


def calculate_average_freight_cost(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean order-level freight on validly delivered orders."""
    return _one(engine, f, "AVG(o.freight_value)")


def calculate_logistics_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """All KPI-card values for the Logistics page."""
    valid = calculate_valid_delivery_orders(engine, f)
    late_rate = calculate_late_delivery_rate(engine, f)
    return {
        "delivered_orders": calculate_delivered_orders(engine, f),
        "orders_with_valid_dates": valid,
        "on_time_deliveries": int(_one(engine, f, "COUNT(*) FILTER (WHERE NOT o.is_late)") or 0),
        "late_deliveries": int(_one(engine, f, "COUNT(*) FILTER (WHERE o.is_late)") or 0),
        "late_delivery_rate": late_rate,
        "on_time_delivery_rate": None if late_rate is None else 1 - late_rate,
        "avg_delivery_days": calculate_average_delivery_time(engine, f),
        "avg_delay_days": calculate_average_delivery_delay(engine, f),
        "avg_delay_of_late_orders": calculate_average_delay_of_late_orders(engine, f),
        "avg_freight_cost": calculate_average_freight_cost(engine, f),
    }


# ------------------------------------------------------------ order-level lists
def calculate_delivery_time(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """order_id, delivery_days, estimated_delivery_days (valid deliveries)."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT o.order_id, o.delivery_days, o.estimated_delivery_days\n"
        f"FROM {s.from_sql}\n{s.where(_VALID)}\nORDER BY o.order_id", s.params)


def calculate_delivery_delay(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """order_id, delivery_delay_days (>0 late), is_late (valid deliveries)."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT o.order_id, o.delivery_delay_days, o.is_late\n"
        f"FROM {s.from_sql}\n{s.where(_VALID)}\nORDER BY o.order_id", s.params)


def identify_late_orders(engine: Engine, f: Filters | None = None, limit: int | None = None) -> pd.DataFrame:
    """Late orders, most delayed first, with state, freight and review score."""
    s = order_scope(f)
    sql = (
        "SELECT o.order_id, o.customer_state AS state, d.year_month AS purchase_month, "
        "o.delivery_days, o.estimated_delivery_days, o.delivery_delay_days, o.freight_value, r.review_score\n"
        f"FROM {s.from_sql}\nLEFT JOIN vw_order_review r ON r.order_id = o.order_id\n"
        f"{s.where(_VALID, 'o.is_late')}\nORDER BY o.delivery_delay_days DESC, o.order_id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return read_sql(engine, sql, s.params)


def calculate_delay_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Orders per ``delivery_delay_days`` value (negative = early), for histograms."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT o.delivery_delay_days AS delay_days, COUNT(*) AS orders\n"
        f"FROM {s.from_sql}\n{s.where(_VALID)}\nGROUP BY 1 ORDER BY 1", s.params)


# ------------------------------------------------------------------ breakdowns
def get_delivery_trend(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per purchase month: orders, avg actual vs estimated delivery days, avg delay,
    late_rate and ``is_sparse`` (see ``flag_sparse_months``)."""
    s = order_scope(f)
    df = read_sql(
        engine,
        "SELECT d.year_month, COUNT(*) AS orders, AVG(o.delivery_days) AS avg_delivery_days, "
        "AVG(o.estimated_delivery_days) AS avg_estimated_days, AVG(o.delivery_delay_days) AS avg_delay_days, "
        "AVG(CASE WHEN o.is_late THEN 1.0 ELSE 0.0 END) AS late_rate\n"
        f"FROM {s.from_sql}\n{s.where(_VALID)}\nGROUP BY 1 ORDER BY 1", s.params)
    return flag_sparse_months(df)


def analyze_delivery_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per customer state: delivered orders, avg delivery/estimated days, avg delay,
    late_rate, avg freight and average review score."""
    s = order_scope(f)
    sql = (
        "SELECT o.customer_state AS state, COUNT(*) AS orders, AVG(o.delivery_days) AS avg_delivery_days, "
        "AVG(o.estimated_delivery_days) AS avg_estimated_days, AVG(o.delivery_delay_days) AS avg_delay_days, "
        "AVG(CASE WHEN o.is_late THEN 1.0 ELSE 0.0 END) AS late_rate, AVG(o.freight_value) AS avg_freight, "
        "AVG(r.review_score) AS avg_review_score\n"
        f"FROM {s.from_sql}\nLEFT JOIN vw_order_review r ON r.order_id = o.order_id\n"
        f"{s.where(_VALID)}\nGROUP BY 1 ORDER BY late_rate DESC, orders DESC, 1"
    )
    return read_sql(engine, sql, s.params)


def analyze_delivery_by_seller(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.SELLER_MIN_ORDERS,
) -> pd.DataFrame:
    """Per seller (>= ``min_orders`` validly delivered orders): late_rate, delays, delivery time."""
    t = sellers_mod.seller_table(engine, f)
    t = t[t["delivered_orders"] >= min_orders]
    cols = ["seller_id", "state", "delivered_orders", "late_orders", "late_rate", "avg_delivery_days", "avg_delay_days"]
    return t[cols].sort_values(["late_rate", "delivered_orders", "seller_id"],
                               ascending=[False, False, True]).reset_index(drop=True)


def calculate_freight_by_category(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Item-level freight per category on validly delivered orders: items, avg
    freight per item, avg item price and freight_to_price ratio (freight / price)."""
    s = item_scope(f)
    sql = (
        "SELECT p.category_en AS category, COUNT(*) AS items, AVG(i.freight_value) AS avg_freight_per_item, "
        "AVG(i.price) AS avg_price, SUM(i.freight_value) / NULLIF(SUM(i.price), 0) AS freight_to_price\n"
        f"FROM {s.from_sql}\n{s.where(_VALID)}\nGROUP BY 1 ORDER BY avg_freight_per_item DESC, 1"
    )
    return read_sql(engine, sql, s.params)


def calculate_freight_delivery_relationship(engine: Engine, f: Filters | None = None) -> dict:
    """Association between order freight and delivery days (valid deliveries).

    Returns Spearman (rank) and Pearson correlations and n. This is an
    association only; it does not show that freight causes slower delivery."""
    s = order_scope(f)
    df = read_sql(engine, "SELECT o.freight_value, o.delivery_days\n"
                          f"FROM {s.from_sql}\n{s.where(_VALID)}", s.params).dropna()
    result = {"n": int(len(df)), "spearman": None, "pearson": None}
    if len(df) >= 3 and df["freight_value"].nunique() > 1 and df["delivery_days"].nunique() > 1:
        result["spearman"] = float(df["freight_value"].corr(df["delivery_days"], method="spearman"))
        result["pearson"] = float(df["freight_value"].corr(df["delivery_days"], method="pearson"))
    return result


# ------------------------------------------------------- bottlenecks / ranking
def identify_logistics_bottlenecks(
    engine: Engine, f: Filters | None = None,
    factor: float = settings.LOGISTICS_BOTTLENECK_FACTOR,
    min_state_orders: int = settings.STATE_MIN_ORDERS,
    min_seller_orders: int = settings.SELLER_MIN_ORDERS,
) -> pd.DataFrame:
    """States and sellers whose late rate is >= ``factor`` x the overall late rate,
    each with at least the minimum number of validly delivered orders.

    Columns: level ("state"/"seller"), name, orders, late_rate, overall_late_rate,
    times_overall, avg_delay_days."""
    cols = ["level", "name", "orders", "late_rate", "overall_late_rate", "times_overall", "avg_delay_days"]
    overall = calculate_late_delivery_rate(engine, f)
    if not overall:
        return pd.DataFrame(columns=cols)
    frames = []
    st = analyze_delivery_by_state(engine, f)
    st = st[st["orders"] >= min_state_orders]
    frames.append(pd.DataFrame({"level": "state", "name": st["state"], "orders": st["orders"],
                                "late_rate": st["late_rate"], "avg_delay_days": st["avg_delay_days"]}))
    se = analyze_delivery_by_seller(engine, f, min_orders=min_seller_orders)
    frames.append(pd.DataFrame({"level": "seller", "name": se["seller_id"], "orders": se["delivered_orders"],
                                "late_rate": se["late_rate"], "avg_delay_days": se["avg_delay_days"]}))
    out = pd.concat(frames, ignore_index=True)
    out["overall_late_rate"] = overall
    out["times_overall"] = out["late_rate"] / overall
    out = out[out["late_rate"] >= factor * overall]
    return out[cols].sort_values(["times_overall", "orders"], ascending=[False, False]).reset_index(drop=True)


def rank_delivery_performance(
    engine: Engine, f: Filters | None = None, by: str = "state",
    min_orders: int | None = None,
) -> pd.DataFrame:
    """Rank states or sellers from best to worst: lowest late rate first, then
    lowest average delay. ``by`` is ``"state"`` or ``"seller"``."""
    if by == "state":
        t = analyze_delivery_by_state(engine, f)
        t = t[t["orders"] >= (min_orders if min_orders is not None else settings.STATE_MIN_ORDERS)]
        key = "state"
    elif by == "seller":
        t = analyze_delivery_by_seller(
            engine, f, min_orders=min_orders if min_orders is not None else settings.SELLER_MIN_ORDERS)
        key = "seller_id"
    else:
        raise ValueError("by must be 'state' or 'seller'")
    t = t.sort_values(["late_rate", "avg_delay_days", key], ascending=[True, True, True]).reset_index(drop=True)
    t.insert(0, "rank", range(1, len(t) + 1))
    return t
