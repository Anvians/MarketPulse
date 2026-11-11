"""Seller performance analytics and the transparent seller scorecard.

Attribution rules (documented because multi-seller orders exist)
----------------------------------------------------------------
* Seller revenue/freight/items come from that seller's own item rows.
* A seller's *orders* = distinct revenue orders containing one of its items.
* Delivery and review are properties of the **whole order**, so for an order
  with two sellers the same delivery outcome and the same review are attributed
  to both. Late rate = late orders / orders with valid delivery dates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import Filters, item_scope, read_sql, safe_div, scalar
from config import settings

_SELLER_COLS = [
    "seller_id", "state", "city", "orders", "items_sold", "revenue", "freight",
    "avg_review_score", "reviews", "delivered_orders", "late_orders", "late_rate",
    "on_time_rate", "avg_delivery_days", "avg_delay_days",
]


def seller_table(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """One row per seller with >= 1 revenue order in scope (all seller metrics)."""
    s = item_scope(f)
    sql = (
        "WITH so AS (\n"
        "  SELECT i.seller_id, i.order_id, SUM(i.price) AS revenue, "
        "SUM(i.freight_value) AS freight, COUNT(*) AS items\n"
        f"  FROM {s.from_sql}\n  {s.where('o.is_revenue_order')}\n  GROUP BY i.seller_id, i.order_id)\n"
        "SELECT so.seller_id, sl.state, sl.city, COUNT(*) AS orders, SUM(so.items) AS items_sold, "
        "SUM(so.revenue) AS revenue, SUM(so.freight) AS freight, "
        "AVG(r.review_score) AS avg_review_score, COUNT(r.review_score) AS reviews, "
        "COUNT(*) FILTER (WHERE o.has_valid_delivery_dates) AS delivered_orders, "
        "COUNT(*) FILTER (WHERE o.is_late) AS late_orders, "
        "AVG(o.delivery_days) AS avg_delivery_days, AVG(o.delivery_delay_days) AS avg_delay_days\n"
        "FROM so\n"
        "JOIN fact_orders o ON o.order_id = so.order_id\n"
        "LEFT JOIN dim_sellers sl ON sl.seller_id = so.seller_id\n"
        "LEFT JOIN vw_order_review r ON r.order_id = so.order_id\n"
        "GROUP BY so.seller_id, sl.state, sl.city\nORDER BY revenue DESC, so.seller_id"
    )
    df = read_sql(engine, sql, s.params)
    if df.empty:
        return pd.DataFrame(columns=_SELLER_COLS)
    delivered = df["delivered_orders"].replace(0, np.nan)
    df["late_rate"] = df["late_orders"] / delivered
    df["on_time_rate"] = 1 - df["late_rate"]
    return df[_SELLER_COLS]


# ---------------------------------------------------------------------- KPIs
def calculate_total_sellers(engine: Engine) -> int:
    """All registered sellers (``dim_sellers``), including those with no orders."""
    return int(scalar(engine, "SELECT COUNT(*) FROM dim_sellers") or 0)


def calculate_seller_revenue(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """seller_id, revenue, freight, items_sold, revenue_share_pct."""
    t = seller_table(engine, f)
    out = t[["seller_id", "revenue", "freight", "items_sold"]].copy()
    total = out["revenue"].sum()
    out["revenue_share_pct"] = 100 * out["revenue"] / total if total else np.nan
    return out


def calculate_seller_order_volume(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """seller_id, orders, items_sold."""
    return seller_table(engine, f)[["seller_id", "orders", "items_sold"]]


def calculate_seller_average_rating(engine: Engine, f: Filters | None = None, min_reviews: int = 1) -> pd.DataFrame:
    """seller_id, avg_review_score, reviews for sellers with >= ``min_reviews`` reviews."""
    t = seller_table(engine, f)
    return t[t["reviews"] >= min_reviews][["seller_id", "avg_review_score", "reviews"]].reset_index(drop=True)


def calculate_seller_delivery_rate(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """seller_id, delivered_orders, on_time_rate (orders with valid delivery dates only)."""
    t = seller_table(engine, f)
    return t[t["delivered_orders"] > 0][["seller_id", "delivered_orders", "on_time_rate"]].reset_index(drop=True)


def calculate_seller_late_delivery_rate(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """seller_id, delivered_orders, late_orders, late_rate."""
    t = seller_table(engine, f)
    return t[t["delivered_orders"] > 0][["seller_id", "delivered_orders", "late_orders", "late_rate"]].reset_index(drop=True)


def calculate_seller_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """KPI-card values for the Seller Performance page.

    ``avg_seller_review_score`` is the mean of seller averages (each seller counts
    once). ``seller_late_delivery_rate`` is pooled: late seller-orders / seller-orders
    with valid delivery dates."""
    t = seller_table(engine, f)
    delivered = t["delivered_orders"].sum()
    return {
        "total_sellers": calculate_total_sellers(engine),
        "sellers_with_orders": int(len(t)),
        "avg_orders_per_seller": float(t["orders"].mean()) if len(t) else None,
        "avg_seller_revenue": float(t["revenue"].mean()) if len(t) else None,
        "avg_seller_review_score": float(t["avg_review_score"].mean()) if len(t) else None,
        "seller_late_delivery_rate": safe_div(t["late_orders"].sum(), delivered) if len(t) else None,
    }


# -------------------------------------------------------------------- rankings
def rank_sellers_by_revenue(engine: Engine, f: Filters | None = None, top_n: int | None = 10) -> pd.DataFrame:
    t = seller_table(engine, f).sort_values(["revenue", "seller_id"], ascending=[False, True])
    t.insert(0, "rank", range(1, len(t) + 1))
    return t.head(top_n) if top_n else t


def rank_sellers_by_orders(engine: Engine, f: Filters | None = None, top_n: int | None = 10) -> pd.DataFrame:
    t = seller_table(engine, f).sort_values(["orders", "revenue", "seller_id"], ascending=[False, False, True])
    t.insert(0, "rank", range(1, len(t) + 1))
    return t.head(top_n) if top_n else t


def rank_sellers_by_satisfaction(
    engine: Engine, f: Filters | None = None, top_n: int | None = 10, min_reviews: int = 10,
) -> pd.DataFrame:
    """Highest average review score among sellers with >= ``min_reviews`` reviews
    (small review counts are noise)."""
    t = seller_table(engine, f)
    t = t[t["reviews"] >= min_reviews].sort_values(
        ["avg_review_score", "reviews", "seller_id"], ascending=[False, False, True])
    t.insert(0, "rank", range(1, len(t) + 1))
    return t.head(top_n) if top_n else t


def calculate_seller_revenue_by_state(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per seller state: sellers, orders, revenue, average review, late rate (pooled)."""
    t = seller_table(engine, f)
    if t.empty:
        return pd.DataFrame(columns=["state", "sellers", "orders", "revenue", "avg_review_score", "late_rate"])
    g = t.groupby("state", dropna=False).apply(
        lambda x: pd.Series({
            "sellers": len(x), "orders": x["orders"].sum(), "revenue": x["revenue"].sum(),
            "avg_review_score": x["avg_review_score"].mean(),
            "late_rate": safe_div(x["late_orders"].sum(), x["delivered_orders"].sum()),
        }), include_groups=False).reset_index()
    return g.sort_values(["revenue", "state"], ascending=[False, True]).reset_index(drop=True)


# ------------------------------------------------------------------ scorecard
def _tier(score: float) -> str:
    for minimum, label in settings.SELLER_TIERS:
        if score >= minimum:
            return label
    return settings.SELLER_TIERS[-1][1]


def scorecard_methodology() -> dict:
    """The scoring rules, as data, for display next to the scorecard."""
    w = settings.SELLER_SCORE_WEIGHTS
    return {
        "weights": dict(w),
        "min_orders": settings.SELLER_MIN_ORDERS,
        "tiers": [{"min_score": m, "tier": t} for m, t in settings.SELLER_TIERS],
        "description": (
            "Score = 100 x weighted sum of percentile ranks (0-1) among scored sellers: "
            f"revenue ({w['revenue']:.0%}), order volume ({w['orders']:.0%}), on-time delivery "
            f"({w['on_time']:.0%}) and average review score ({w['satisfaction']:.0%}). A seller is "
            f"scored only with at least {settings.SELLER_MIN_ORDERS} orders and valid delivery and "
            "review data. Percentile ranks are relative to the other sellers in the current filter "
            "scope, so scores describe relative standing, not absolute quality."
        ),
    }


def generate_seller_scorecard(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.SELLER_MIN_ORDERS,
    seller_id: str | None = None,
) -> pd.DataFrame:
    """Scored sellers with component percentiles, ``score`` (0-100), ``tier`` and
    ``score_rank``. Pass ``seller_id`` to return just that seller (ranked against
    all scored sellers); an empty frame means the seller is not scorable."""
    t = seller_table(engine, f)
    t = t[(t["orders"] >= min_orders) & (t["delivered_orders"] > 0) & t["avg_review_score"].notna()].copy()
    cols = ["seller_id", "state", "orders", "revenue", "on_time_rate", "avg_review_score",
            "pct_revenue", "pct_orders", "pct_on_time", "pct_satisfaction", "score", "tier", "score_rank"]
    if t.empty:
        return pd.DataFrame(columns=cols)
    w = settings.SELLER_SCORE_WEIGHTS
    t["pct_revenue"] = t["revenue"].rank(pct=True)
    t["pct_orders"] = t["orders"].rank(pct=True)
    t["pct_on_time"] = t["on_time_rate"].rank(pct=True)
    t["pct_satisfaction"] = t["avg_review_score"].rank(pct=True)
    t["score"] = 100 * (
        w["revenue"] * t["pct_revenue"] + w["orders"] * t["pct_orders"]
        + w["on_time"] * t["pct_on_time"] + w["satisfaction"] * t["pct_satisfaction"]
    )
    t["tier"] = t["score"].map(_tier)
    t = t.sort_values(["score", "revenue", "seller_id"], ascending=[False, False, True]).reset_index(drop=True)
    t["score_rank"] = range(1, len(t) + 1)
    t = t[cols]
    if seller_id is not None:
        return t[t["seller_id"] == seller_id].reset_index(drop=True)
    return t


def identify_underperforming_sellers(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.SELLER_MIN_ORDERS,
) -> pd.DataFrame:
    """Sellers with >= ``min_orders`` orders that breach a transparent rule:
    late rate > ``SELLER_HIGH_LATE_RATE`` or average review < ``LOW_REVIEW_THRESHOLD``.
    Adds ``reasons`` (text) and ``revenue_at_stake`` (their revenue)."""
    t = seller_table(engine, f)
    t = t[t["orders"] >= min_orders].copy()
    cols = list(t.columns) + ["reasons"]
    if t.empty:
        return pd.DataFrame(columns=cols)
    late = t["late_rate"] > settings.SELLER_HIGH_LATE_RATE
    poor = t["avg_review_score"] < settings.LOW_REVIEW_THRESHOLD

    def reasons(i: int) -> str:
        r = []
        if late.iloc[i]:
            r.append(f"late rate {t['late_rate'].iloc[i]:.0%} > {settings.SELLER_HIGH_LATE_RATE:.0%}")
        if poor.iloc[i]:
            r.append(f"avg review {t['avg_review_score'].iloc[i]:.2f} < {settings.LOW_REVIEW_THRESHOLD}")
        return "; ".join(r)

    t["reasons"] = [reasons(i) for i in range(len(t))]
    return t[late | poor].sort_values(["revenue", "seller_id"], ascending=[False, True]).reset_index(drop=True)


def search_sellers(engine: Engine, query: str, limit: int = 50) -> pd.DataFrame:
    """Find sellers by id fragment, city or state (case-insensitive, parameterised)."""
    like = f"%{query.strip().lower()}%"
    return read_sql(
        engine,
        "SELECT seller_id, city, state FROM dim_sellers "
        "WHERE lower(seller_id) LIKE :q OR lower(COALESCE(city, '')) LIKE :q "
        "OR lower(COALESCE(state, '')) LIKE :q ORDER BY seller_id LIMIT :n",
        {"q": like, "n": int(limit)},
    )
