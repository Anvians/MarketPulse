"""Customer satisfaction analytics (review scores).

Uses ONE review per order (``vw_order_review``: the latest) on revenue orders, so
an order with several reviews is not over-weighted. Rates are fractions.
"Negative" = score 1 or 2. Review *text* sentiment is a separate Milestone 5
feature: a score and the comment written with it do not always agree.
Associations shown here (e.g. delay vs score) are not proof of causation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import Filters, flag_sparse_months, item_scope, order_scope, read_sql, safe_div
from config import settings

_NEG = "CASE WHEN r.review_score <= 2 THEN 1.0 ELSE 0.0 END"


def _reviewed_orders(f: Filters | None):
    s = order_scope(f)
    return f"{s.from_sql}\nJOIN vw_order_review r ON r.order_id = o.order_id", s.where("o.is_revenue_order"), s.params


def calculate_review_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Reviews per score 1-5 (all five scores always present): score, reviews, share."""
    from_sql, where, params = _reviewed_orders(f)
    df = read_sql(engine, f"SELECT r.review_score AS score, COUNT(*) AS reviews\nFROM {from_sql}\n{where}\nGROUP BY 1", params)
    out = pd.DataFrame({"score": range(1, 6)}).merge(df, on="score", how="left").fillna({"reviews": 0})
    out["reviews"] = out["reviews"].astype(int)
    total = out["reviews"].sum()
    out["share"] = out["reviews"] / total if total else np.nan
    return out


def calculate_negative_review_percentage(engine: Engine, f: Filters | None = None) -> float | None:
    """Reviews scored 1-2 / scored reviews (a fraction in [0, 1])."""
    d = calculate_review_distribution(engine, f)
    return safe_div(d.loc[d["score"] <= 2, "reviews"].sum(), d["reviews"].sum())


def calculate_satisfaction_kpis(engine: Engine, f: Filters | None = None) -> dict:
    d = calculate_review_distribution(engine, f).set_index("score")["reviews"]
    total = int(d.sum())
    return {
        "avg_review_score": safe_div((d.index.to_series() * d).sum(), total),
        "total_reviews": total,
        "one_star": int(d[1]), "two_star": int(d[2]), "five_star": int(d[5]),
        "negative_review_rate": safe_div(d[1] + d[2], total),
    }


def analyze_review_trends(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per purchase month: reviews, avg_review_score, negative_rate, is_sparse."""
    from_sql, where, params = _reviewed_orders(f)
    df = read_sql(
        engine,
        f"SELECT d.year_month, COUNT(*) AS reviews, AVG(r.review_score) AS avg_review_score, AVG({_NEG}) AS negative_rate\n"
        f"FROM {from_sql}\n{where}\nGROUP BY 1 ORDER BY 1", params)
    return flag_sparse_months(df, orders_col="reviews")


def _by_item_dimension(engine: Engine, f: Filters | None, expr: str, name: str, min_reviews: int) -> pd.DataFrame:
    s = item_scope(f)
    sql = (
        f"WITH g AS (SELECT {expr} AS {name}, i.order_id\n  FROM {s.from_sql}\n  {s.where('o.is_revenue_order')}\n  GROUP BY 1, 2)\n"
        f"SELECT g.{name}, COUNT(*) AS orders, COUNT(r.review_score) AS reviews, AVG(r.review_score) AS avg_review_score, "
        f"AVG(CASE WHEN r.review_score IS NULL THEN NULL ELSE {_NEG} END) AS negative_rate\n"
        "FROM g LEFT JOIN vw_order_review r ON r.order_id = g.order_id\n"
        f"GROUP BY g.{name} HAVING COUNT(r.review_score) >= :min_reviews\n"
        f"ORDER BY avg_review_score DESC NULLS LAST, reviews DESC, g.{name}"
    )
    return read_sql(engine, sql, {**s.params, "min_reviews": int(min_reviews)})


def analyze_reviews_by_category(engine: Engine, f: Filters | None = None, min_reviews: int = 1) -> pd.DataFrame:
    """category, orders, reviews, avg_review_score, negative_rate (orders containing the category)."""
    return _by_item_dimension(engine, f, "p.category_en", "category", min_reviews)


def analyze_reviews_by_seller(engine: Engine, f: Filters | None = None, min_reviews: int = 1) -> pd.DataFrame:
    """seller_id, orders, reviews, avg_review_score, negative_rate (the order's review is shared by all its sellers)."""
    return _by_item_dimension(engine, f, "i.seller_id", "seller_id", min_reviews)


def analyze_reviews_by_state(engine: Engine, f: Filters | None = None, min_reviews: int = 1) -> pd.DataFrame:
    """Per customer state: reviews, avg_review_score, negative_rate."""
    from_sql, where, params = _reviewed_orders(f)
    return read_sql(
        engine,
        f"SELECT o.customer_state AS state, COUNT(*) AS reviews, AVG(r.review_score) AS avg_review_score, AVG({_NEG}) AS negative_rate\n"
        f"FROM {from_sql}\n{where}\nGROUP BY 1 HAVING COUNT(*) >= :m ORDER BY avg_review_score DESC, reviews DESC, 1",
        {**params, "m": int(min_reviews)})


def analyze_reviews_by_payment(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per primary payment type: reviews, avg_review_score, negative_rate."""
    from_sql, where, params = _reviewed_orders(f)
    return read_sql(
        engine,
        f"SELECT o.primary_payment_type AS payment_type, COUNT(*) AS reviews, AVG(r.review_score) AS avg_review_score, AVG({_NEG}) AS negative_rate\n"
        f"FROM {from_sql}\n{where}\nGROUP BY 1 ORDER BY reviews DESC, 1", params)


_DELAY_BUCKETS = (
    ("On time or early", 1, "o.delivery_delay_days <= 0"),
    ("1-3 days late", 2, "o.delivery_delay_days BETWEEN 1 AND 3"),
    ("4-7 days late", 3, "o.delivery_delay_days BETWEEN 4 AND 7"),
    ("8+ days late", 4, "o.delivery_delay_days >= 8"),
)


def analyze_delivery_review_relationship(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Review score by delivery-delay bucket (validly delivered orders only):
    bucket, sort_key, orders, avg_review_score, negative_rate. An association,
    not proof that lateness causes lower scores."""
    from_sql, where, params = _reviewed_orders(f)
    case = " ".join(f"WHEN {cond} THEN '{label}'" for label, _, cond in _DELAY_BUCKETS)
    key = " ".join(f"WHEN {cond} THEN {k}" for _, k, cond in _DELAY_BUCKETS)
    df = read_sql(
        engine,
        f"SELECT CASE {case} END AS bucket, CASE {key} END AS sort_key, COUNT(*) AS orders, "
        f"AVG(r.review_score) AS avg_review_score, AVG({_NEG}) AS negative_rate\n"
        f"FROM {from_sql}\n{where.replace('WHERE', 'WHERE o.has_valid_delivery_dates AND', 1)}\n"
        "GROUP BY 1, 2 ORDER BY 2", params)
    return df


def compare_late_vs_on_time_reviews(engine: Engine, f: Filters | None = None) -> dict:
    """Mean review score of late vs on-time delivered orders and the difference."""
    from_sql, where, params = _reviewed_orders(f)
    row = read_sql(
        engine,
        "SELECT AVG(r.review_score) FILTER (WHERE o.is_late) AS late_avg, COUNT(*) FILTER (WHERE o.is_late) AS late_n, "
        "AVG(r.review_score) FILTER (WHERE NOT o.is_late) AS on_time_avg, COUNT(*) FILTER (WHERE NOT o.is_late) AS on_time_n\n"
        f"FROM {from_sql}\n{where.replace('WHERE', 'WHERE o.has_valid_delivery_dates AND', 1)}", params).iloc[0]
    late, ontime = row["late_avg"], row["on_time_avg"]
    return {"late_avg": None if pd.isna(late) else float(late), "late_orders": int(row["late_n"]),
            "on_time_avg": None if pd.isna(ontime) else float(ontime), "on_time_orders": int(row["on_time_n"]),
            "difference": None if pd.isna(late) or pd.isna(ontime) else float(late - ontime)}


def identify_low_satisfaction_categories(
    engine: Engine, f: Filters | None = None, min_reviews: int = settings.CATEGORY_MIN_ORDERS,
    threshold: float = settings.LOW_REVIEW_THRESHOLD,
) -> pd.DataFrame:
    """Categories with >= ``min_reviews`` reviews and average score below ``threshold``, worst first."""
    c = analyze_reviews_by_category(engine, f, min_reviews)
    return c[c["avg_review_score"] < threshold].sort_values("avg_review_score").reset_index(drop=True)


def identify_low_satisfaction_sellers(
    engine: Engine, f: Filters | None = None, min_reviews: int = settings.SELLER_MIN_ORDERS,
    threshold: float = settings.LOW_REVIEW_THRESHOLD,
) -> pd.DataFrame:
    """Sellers with >= ``min_reviews`` reviews and average score below ``threshold``, worst first."""
    s = analyze_reviews_by_seller(engine, f, min_reviews)
    return s[s["avg_review_score"] < threshold].sort_values("avg_review_score").reset_index(drop=True)
