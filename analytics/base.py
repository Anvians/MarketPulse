"""Shared plumbing for the analytics layer.

Conventions (apply to every analytics module)
---------------------------------------------
* Functions take ``(engine, filters=None, ...)`` and return plain Python
  numbers / dicts / pandas DataFrames. No Streamlit code lives here.
* **Rates and shares are fractions in [0, 1]**, never percentages. Columns named
  ``*_pct`` hold percentages (0-100). ``None`` / NaN means "not computable"
  (empty denominator), never zero.
* **Revenue = product revenue** = sum of item ``price`` on *revenue orders*
  (not canceled/unavailable, >= 1 item). Freight is separate. Not profit.
* **Item scope vs order scope.** Revenue, category and seller metrics read the
  *item scope* (one row per item) so that category/seller filters restrict the
  items counted. Delivery, customer-timing and review metrics read the *order
  scope* (one row per order); a category/seller filter then selects the orders
  that *contain* a matching item (their delivery/review belongs to the whole
  order). Neither scope ever multiplies an order, so nothing double counts.
* All SQL is parameterised; user filter values are never formatted into SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import settings


# --------------------------------------------------------------------- filters
@dataclass(frozen=True)
class Filters:
    """Global filters. Tuples (not lists) so instances are hashable for caching.

    * ``date_from`` / ``date_to``: inclusive range on the order *purchase date*.
    * ``states``: customer state (state of the order's customer).
    * ``categories``: English product category names.
    * ``sellers``: seller ids.
    * ``payment_types``: the order's primary payment type.
    * ``order_statuses``: order status. Note: revenue metrics only ever count
      revenue orders, so filtering to e.g. ``canceled`` yields zero revenue by
      definition rather than changing what "revenue" means.
    """

    date_from: date | None = None
    date_to: date | None = None
    states: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    sellers: tuple[str, ...] = ()
    payment_types: tuple[str, ...] = ()
    order_statuses: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return self == Filters()

    def describe(self) -> str:
        """Human-readable summary of active filters (shown next to metrics)."""
        parts: list[str] = []
        if self.date_from or self.date_to:
            parts.append(f"purchase date {self.date_from or '…'} to {self.date_to or '…'}")
        for label, values in (
            ("state", self.states), ("category", self.categories), ("seller", self.sellers),
            ("payment", self.payment_types), ("status", self.order_statuses),
        ):
            if values:
                shown = ", ".join(values[:3]) + (f" +{len(values) - 3} more" if len(values) > 3 else "")
                parts.append(f"{label}: {shown}")
        return "; ".join(parts) if parts else "no filters"


def reset_filters() -> Filters:
    """The empty filter set."""
    return Filters()


@dataclass(frozen=True)
class Scope:
    """A FROM clause plus its WHERE conditions and bind parameters."""

    from_sql: str
    conditions: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)

    def where(self, *extra: str) -> str:
        conds = list(self.conditions) + [e for e in extra if e]
        return ("WHERE " + " AND ".join(conds)) if conds else ""


_ORDER_FROM = (
    "fact_orders o\n"
    "LEFT JOIN dim_date d ON d.date_key = o.purchase_date_key"
)
_ITEM_FROM = (
    "fact_order_items i\n"
    "JOIN fact_orders o ON o.order_id = i.order_id\n"
    "LEFT JOIN dim_products p ON p.product_id = i.product_id\n"
    "LEFT JOIN dim_sellers s ON s.seller_id = i.seller_id\n"
    "LEFT JOIN dim_date d ON d.date_key = o.purchase_date_key"
)


def _order_level_conditions(f: Filters) -> tuple[list[str], dict[str, Any]]:
    conds: list[str] = []
    params: dict[str, Any] = {}
    if f.date_from:
        conds.append("o.purchase_ts >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        conds.append("o.purchase_ts < :date_to_excl")
        params["date_to_excl"] = f.date_to + timedelta(days=1)
    if f.states:
        conds.append("o.customer_state = ANY(:states)")
        params["states"] = [s.upper() for s in f.states]
    if f.payment_types:
        conds.append("o.primary_payment_type = ANY(:payment_types)")
        params["payment_types"] = list(f.payment_types)
    if f.order_statuses:
        conds.append("o.order_status = ANY(:order_statuses)")
        params["order_statuses"] = [s.lower() for s in f.order_statuses]
    return conds, params


def _item_filter_params(f: Filters) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if f.categories:
        params["categories"] = list(f.categories)
    if f.sellers:
        params["sellers"] = list(f.sellers)
    return params


def item_scope(f: Filters | None = None) -> Scope:
    """One row per order item; category/seller filters restrict the items."""
    f = f or Filters()
    conds, params = _order_level_conditions(f)
    if f.categories:
        conds.append("p.category_en = ANY(:categories)")
    if f.sellers:
        conds.append("i.seller_id = ANY(:sellers)")
    params.update(_item_filter_params(f))
    return Scope(_ITEM_FROM, tuple(conds), params)


def order_scope(f: Filters | None = None) -> Scope:
    """One row per order; category/seller filters select orders containing a
    matching item (a single item must satisfy both when both are given)."""
    f = f or Filters()
    conds, params = _order_level_conditions(f)
    if f.categories or f.sellers:
        item_conds = []
        if f.categories:
            item_conds.append("fp.category_en = ANY(:categories)")
        if f.sellers:
            item_conds.append("fi.seller_id = ANY(:sellers)")
        conds.append(
            "EXISTS (SELECT 1 FROM fact_order_items fi "
            "JOIN dim_products fp ON fp.product_id = fi.product_id "
            "WHERE fi.order_id = o.order_id AND " + " AND ".join(item_conds) + ")"
        )
    params.update(_item_filter_params(f))
    return Scope(_ORDER_FROM, tuple(conds), params)


# ------------------------------------------------------------------ execution
def _decimals_to_float(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna()
            if len(sample) and isinstance(sample.iloc[0], Decimal):
                df[col] = df[col].map(lambda v: float(v) if v is not None else np.nan)
    return df


def read_sql(engine: Engine, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Run a parameterised query; NUMERIC columns come back as float."""
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params or {})
    return _decimals_to_float(df)


def scalar(engine: Engine, sql: str, params: dict[str, Any] | None = None) -> float | int | None:
    """First column of the first row (None if no rows / NULL)."""
    with engine.connect() as conn:
        value = conn.execute(text(sql), params or {}).scalar()
    if isinstance(value, Decimal):
        return float(value)
    return value


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """``numerator / denominator`` or None when not computable."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def summarize_numeric(values: pd.Series) -> dict[str, float | None]:
    """Count, mean, median, quartiles, p90 and range of a numeric series."""
    s = pd.to_numeric(values, errors="coerce").dropna()
    if s.empty:
        return {k: None for k in ("count", "mean", "median", "p25", "p75", "p90", "min", "max")} | {"count": 0}
    return {
        "count": int(len(s)), "mean": float(s.mean()), "median": float(s.median()),
        "p25": float(s.quantile(0.25)), "p75": float(s.quantile(0.75)),
        "p90": float(s.quantile(0.90)), "min": float(s.min()), "max": float(s.max()),
    }


# ----------------------------------------------------------- time-series rules
def flag_sparse_months(monthly: pd.DataFrame, orders_col: str = "orders") -> pd.DataFrame:
    """Add ``is_sparse``: months with fewer than ``SPARSE_MONTH_FRACTION`` x the
    median monthly order count. The Olist data has near-empty edge months, and
    growth between a sparse month and a full one is an artefact, not a trend.
    The rule is relative to the data in scope, so it adapts to filters."""
    out = monthly.copy()
    if out.empty:
        out["is_sparse"] = pd.Series(dtype=bool)
        return out
    threshold = settings.SPARSE_MONTH_FRACTION * float(out[orders_col].median())
    out["is_sparse"] = out[orders_col] < threshold
    return out


# --------------------------------------------------------------- revenue by dim
_DIMENSIONS: dict[str, tuple[list[str], bool]] = {
    # name: (select expressions, chronological?)
    "date": (["d.full_date AS full_date"], True),
    "month": (["d.year_month AS year_month"], True),
    "quarter": (["d.calendar_year AS calendar_year", "d.calendar_quarter AS calendar_quarter"], True),
    "year": (["d.calendar_year AS calendar_year"], True),
    "weekday": (["d.iso_weekday AS iso_weekday", "d.weekday_name AS weekday_name"], True),
    "category": (["p.category_en AS category"], False),
    "state": (["o.customer_state AS state"], False),
    "city": (["o.customer_state AS state", "o.customer_city AS city"], False),
    "seller": (["i.seller_id AS seller_id"], False),
    "seller_state": (["s.state AS seller_state"], False),
    "payment": (["o.primary_payment_type AS payment_type"], False),
}


def revenue_by(
    engine: Engine, f: Filters | None, dim: str, limit: int | None = None
) -> pd.DataFrame:
    """Product revenue, freight, distinct orders and items grouped by a dimension.

    Columns: dimension column(s), ``revenue``, ``freight``, ``orders`` (distinct
    revenue orders touching the group), ``items`` and ``revenue_share_pct``.
    ``orders`` can overlap across groups (an order spanning two categories
    counts once in each) but ``revenue`` always sums to total revenue.
    """
    if dim not in _DIMENSIONS:
        raise ValueError(f"Unknown dimension {dim!r}; choose from {sorted(_DIMENSIONS)}")
    cols, chronological = _DIMENSIONS[dim]
    group_positions = ", ".join(str(n + 1) for n in range(len(cols)))
    s = item_scope(f)
    order_by = group_positions if chronological else "revenue DESC, 1"
    sql = (
        f"SELECT {', '.join(cols)}, SUM(i.price) AS revenue, SUM(i.freight_value) AS freight, "
        f"COUNT(DISTINCT i.order_id) AS orders, COUNT(*) AS items, "
        # share of the TOTAL over all groups, computed before LIMIT so top-N shares stay correct
        f"100.0 * SUM(i.price) / NULLIF(SUM(SUM(i.price)) OVER (), 0) AS revenue_share_pct\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\n"
        f"GROUP BY {group_positions}\nORDER BY {order_by}"
    )
    if limit:
        sql += f"\nLIMIT {int(limit)}"
    return read_sql(engine, sql, s.params)


# ------------------------------------------------------------------- insights
@dataclass(frozen=True)
class Insight:
    """A rule-generated finding. ``rule`` states the transparent trigger."""

    title: str
    detail: str
    severity: str          # "info" | "positive" | "warning" | "critical"
    kpi: str
    rule: str
    evidence: dict[str, Any] = field(default_factory=dict)
