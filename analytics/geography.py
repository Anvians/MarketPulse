"""Geographic analytics.

State = the customer's state at the time of the order (``fact_orders.customer_state``)
unless a function says "seller". Zip-code coordinates are never joined here (the
raw geolocation file has many rows per prefix); maps use state-level aggregates
only, so no customer or seller is duplicated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics import customers as customers_mod
from analytics import logistics as logistics_mod
from analytics.base import (
    Filters,
    flag_sparse_months,
    item_scope,
    order_scope,
    read_sql,
    revenue_by,
    scalar,
)
from config import settings


def state_to_region(state: str | None) -> str:
    """IBGE macro-region of a state code ('Unknown' if not recognised)."""
    return settings.BRAZIL_REGIONS.get((state or "").upper(), "Unknown")


def calculate_revenue_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "state")


def calculate_orders_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """state, orders (revenue orders), order_share_pct."""
    s = order_scope(f)
    df = read_sql(engine, "SELECT o.customer_state AS state, COUNT(*) AS orders\n"
                          f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nGROUP BY 1 ORDER BY orders DESC, 1", s.params)
    df["order_share_pct"] = 100 * df["orders"] / df["orders"].sum() if not df.empty else pd.Series(dtype=float)
    return df


def calculate_customers_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return customers_mod.calculate_customers_by_state(engine, f)


def calculate_sellers_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Sellers (by the SELLER's state) with >= 1 revenue order in scope: state, sellers, revenue."""
    s = item_scope(f)
    df = read_sql(
        engine,
        "SELECT s.state AS state, COUNT(DISTINCT i.seller_id) AS sellers, SUM(i.price) AS revenue\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nGROUP BY 1 ORDER BY sellers DESC, 1", s.params)
    df["seller_share_pct"] = 100 * df["sellers"] / df["sellers"].sum() if not df.empty else pd.Series(dtype=float)
    return df


def calculate_delivery_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return logistics_mod.analyze_delivery_by_state(engine, f)


def calculate_freight_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per customer state on revenue orders: orders, avg freight per order, avg freight per
    item and freight_to_price (total freight / total product revenue)."""
    s = item_scope(f)
    return read_sql(
        engine,
        "SELECT o.customer_state AS state, COUNT(DISTINCT i.order_id) AS orders, "
        "SUM(i.freight_value) / NULLIF(COUNT(DISTINCT i.order_id), 0) AS avg_freight_per_order, "
        "AVG(i.freight_value) AS avg_freight_per_item, SUM(i.freight_value) / NULLIF(SUM(i.price), 0) AS freight_to_price\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nGROUP BY 1 ORDER BY avg_freight_per_order DESC, 1", s.params)


def calculate_state_summary(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """One row per customer state combining revenue, orders, customers, delivery,
    freight and satisfaction (+ region and revenue share). Sellers are not included
    because a seller's state differs from the customer's (see ``calculate_sellers_by_state``)."""
    rev = revenue_by(engine, f, "state").rename(columns={"freight": "freight_total"})
    if rev.empty:
        return pd.DataFrame(columns=["state", "region", "revenue", "orders", "customers"])
    cust = customers_mod.calculate_customers_by_state(engine, f)[["state", "customers"]]
    dlv = logistics_mod.analyze_delivery_by_state(engine, f)[
        ["state", "late_rate", "avg_delivery_days", "avg_review_score"]]
    fr = calculate_freight_by_state(engine, f)[["state", "avg_freight_per_order"]]
    out = rev.merge(cust, on="state", how="left").merge(dlv, on="state", how="left").merge(fr, on="state", how="left")
    out["avg_order_value"] = out["revenue"] / out["orders"].replace(0, np.nan)
    out["region"] = out["state"].map(state_to_region)
    return out


def calculate_revenue_by_region(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Revenue, orders (sum of state orders; an order has one customer state) and share by IBGE region."""
    st = revenue_by(engine, f, "state")
    cols = ["region", "revenue", "orders", "states", "revenue_share_pct"]
    if st.empty:
        return pd.DataFrame(columns=cols)
    st["region"] = st["state"].map(state_to_region)
    g = st.groupby("region").agg(revenue=("revenue", "sum"), orders=("orders", "sum"), states=("state", "nunique")).reset_index()
    g["revenue_share_pct"] = 100 * g["revenue"] / g["revenue"].sum()
    return g.sort_values("revenue", ascending=False).reset_index(drop=True)[cols]


def identify_top_revenue_regions(engine: Engine, f: Filters | None = None, cumulative_pct: float = 80.0) -> pd.DataFrame:
    """Smallest set of top states that together make up >= ``cumulative_pct`` of revenue."""
    st = revenue_by(engine, f, "state")
    if st.empty:
        return st
    st["cumulative_share_pct"] = st["revenue_share_pct"].cumsum()
    keep = (st["cumulative_share_pct"] - st["revenue_share_pct"]) < cumulative_pct
    return st[keep].reset_index(drop=True)


def identify_growth_regions(engine: Engine, f: Filters | None = None, periods: int = 3) -> pd.DataFrame:
    """States ranked by revenue change: last ``periods`` non-sparse months vs the
    ``periods`` months before. OBSERVED historical change, not a forecast; needs
    >= 2 x ``periods`` non-sparse months, otherwise an empty frame is returned.
    Columns: state, recent_revenue, prior_revenue, change_pct."""
    cols = ["state", "recent_revenue", "prior_revenue", "change_pct"]
    months = flag_sparse_months(revenue_by(engine, f, "month"))
    full = months[~months["is_sparse"]]["year_month"].tolist()
    if len(full) < 2 * periods:
        return pd.DataFrame(columns=cols)
    recent, prior = full[-periods:], full[-2 * periods:-periods]
    s = item_scope(f)
    df = read_sql(
        engine,
        "SELECT o.customer_state AS state, d.year_month, SUM(i.price) AS revenue\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order', 'd.year_month = ANY(:window)')}\nGROUP BY 1, 2",
        {**s.params, "window": recent + prior})
    df["is_recent"] = df["year_month"].isin(recent)
    g = df.pivot_table(index="state", columns="is_recent", values="revenue", aggfunc="sum", fill_value=0.0)
    out = pd.DataFrame({"recent_revenue": g.get(True, 0.0), "prior_revenue": g.get(False, 0.0)}).reset_index()
    out["change_pct"] = 100 * (out["recent_revenue"] / out["prior_revenue"].replace(0, np.nan) - 1)
    return out[cols].sort_values("change_pct", ascending=False, na_position="last").reset_index(drop=True)


def calculate_customer_seller_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Customers vs sellers per state (seller state for sellers): customers, sellers,
    customer_share_pct, seller_share_pct and customers_per_seller (NaN when a state has no sellers)."""
    c = customers_mod.calculate_customers_by_state(engine, f)[["state", "customers"]]
    sl = calculate_sellers_by_state(engine, f)[["state", "sellers"]]
    out = c.merge(sl, on="state", how="outer").fillna({"customers": 0, "sellers": 0})
    out["customer_share_pct"] = 100 * out["customers"] / out["customers"].sum() if out["customers"].sum() else np.nan
    out["seller_share_pct"] = 100 * out["sellers"] / out["sellers"].sum() if out["sellers"].sum() else np.nan
    out["customers_per_seller"] = out["customers"] / out["sellers"].replace(0, np.nan)
    return out.sort_values(["customers", "state"], ascending=[False, True]).reset_index(drop=True)


def calculate_geography_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """KPI-card values for the Geographic page."""
    o = order_scope(f)
    row = read_sql(
        engine,
        "SELECT COUNT(DISTINCT o.customer_state) AS states, "
        "COUNT(DISTINCT (o.customer_city, o.customer_state)) AS customer_cities\n"
        f"FROM {o.from_sql}\n{o.where('o.is_revenue_order')}", o.params).iloc[0]
    i = item_scope(f)
    seller_cities = scalar(
        engine,
        f"SELECT COUNT(DISTINCT (s.city, s.state)) FROM {i.from_sql}\n{i.where('o.is_revenue_order')}", i.params)
    rev = revenue_by(engine, f, "state", limit=1)
    cust = customers_mod.calculate_customers_by_state(engine, f)
    return {
        "total_states": int(row["states"]),
        "customer_cities": int(row["customer_cities"]),
        "seller_cities": int(seller_cities or 0),
        "top_revenue_state": None if rev.empty else rev.iloc[0]["state"],
        "top_revenue_state_share_pct": None if rev.empty else float(rev.iloc[0]["revenue_share_pct"]),
        "top_customer_state": None if cust.empty else cust.iloc[0]["state"],
        "top_customer_state_share_pct": None if cust.empty else float(cust.iloc[0]["customer_share_pct"]),
    }
