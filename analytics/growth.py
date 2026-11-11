"""Growth opportunities: where observed demand is rising or supply looks thin.

Everything here is OBSERVED history (2016-2018) compared across periods, or a
transparent ratio rule. Nothing is forecast and no causal claim is made; each
finding is a place to investigate. Thresholds live in ``config/settings.py``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics import geography
from analytics.base import Filters, Insight, item_scope, read_sql, revenue_by
from analytics.revenue import _category_period_change
from config import settings


def identify_growth_categories(
    engine: Engine, f: Filters | None = None, periods: int = 3, min_orders: int = settings.CATEGORY_MIN_ORDERS,
) -> pd.DataFrame:
    """Categories whose revenue in the last ``periods`` non-sparse months exceeds the
    ``periods`` before (needs >= 2 x ``periods`` non-sparse months, else empty) and that
    have at least ``min_orders`` orders overall. Columns: category, recent_revenue,
    prior_revenue, change_pct, orders. Categories with no prior revenue are excluded
    (growth from zero is undefined)."""
    cols = ["category", "recent_revenue", "prior_revenue", "change_pct", "orders"]
    change = _category_period_change(engine, f, periods)
    if change.empty:
        return pd.DataFrame(columns=cols)
    orders = revenue_by(engine, f, "category")[["category", "orders"]]
    m = change.merge(orders, on="category", how="left")
    m = m[(m["prior_revenue"] > 0) & (m["change_pct"] > 0) & (m["orders"] >= min_orders)]
    return m[cols].sort_values("change_pct", ascending=False).reset_index(drop=True)


def identify_growth_states(
    engine: Engine, f: Filters | None = None, periods: int = 3, min_prior_revenue: float = 0.0,
) -> pd.DataFrame:
    """Customer states with positive recent revenue change (see geography.identify_growth_regions)."""
    g = geography.identify_growth_regions(engine, f, periods)
    if g.empty:
        return g
    return g[(g["change_pct"] > 0) & (g["prior_revenue"] > min_prior_revenue)].reset_index(drop=True)


def identify_underserved_states(
    engine: Engine, f: Filters | None = None, quantile: float = settings.SUPPLY_GAP_QUANTILE,
    min_customers: int = settings.SUPPLY_GAP_MIN_CUSTOMERS,
) -> pd.DataFrame:
    """States with at least ``min_customers`` customers that have NO seller, or whose
    customers-per-seller is at or above the ``quantile`` of states that have sellers.

    Sellers are counted in their own state, but they can ship anywhere, so this is a
    prompt to check local seller onboarding, not proof of unmet demand.
    Columns: state, customers, sellers, customers_per_seller, reason."""
    d = geography.calculate_customer_seller_distribution(engine, f)
    cols = ["state", "customers", "sellers", "customers_per_seller", "reason"]
    if d.empty:
        return pd.DataFrame(columns=cols)
    d = d[d["customers"] >= min_customers].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    ratios = d["customers_per_seller"].dropna()
    cutoff = float(ratios.quantile(quantile)) if len(ratios) else np.nan
    no_seller = d["sellers"] == 0
    thin = d["customers_per_seller"] >= cutoff if not np.isnan(cutoff) else pd.Series(False, index=d.index)
    d["reason"] = np.where(no_seller, "no seller located in the state",
                           f"customers per seller >= p{int(quantile * 100)} ({cutoff:.1f})" if not np.isnan(cutoff) else "")
    return d[no_seller | thin][cols].sort_values("customers", ascending=False).reset_index(drop=True)


def identify_cross_sell_pairs(
    engine: Engine, f: Filters | None = None, min_pair_orders: int = settings.CROSS_SELL_MIN_PAIR_ORDERS,
    min_lift: float = settings.CROSS_SELL_MIN_LIFT, top_n: int | None = 50,
) -> pd.DataFrame:
    """Category pairs bought together in the same order.

    ``lift`` = P(A and B) / (P(A) x P(B)) over revenue orders; > 1 means the pair occurs
    together more than independence would predict. Only pairs seen in at least
    ``min_pair_orders`` orders are kept. Association only; most orders hold one category,
    so counts are small. Columns: category_a, category_b, pair_orders, orders_a, orders_b, lift."""
    cols = ["category_a", "category_b", "pair_orders", "orders_a", "orders_b", "lift"]
    s = item_scope(f)
    oc = read_sql(
        engine,
        "SELECT DISTINCT i.order_id, p.category_en AS category\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order', 'p.category_en IS NOT NULL')}", s.params)
    if oc.empty:
        return pd.DataFrame(columns=cols)
    n_orders = oc["order_id"].nunique()
    per_cat = oc.groupby("category")["order_id"].nunique()
    pairs = oc.merge(oc, on="order_id", suffixes=("_a", "_b"))
    pairs = pairs[pairs["category_a"] < pairs["category_b"]]
    if pairs.empty:
        return pd.DataFrame(columns=cols)
    g = pairs.groupby(["category_a", "category_b"]).size().rename("pair_orders").reset_index()
    g = g[g["pair_orders"] >= min_pair_orders]
    if g.empty:
        return pd.DataFrame(columns=cols)
    g["orders_a"] = g["category_a"].map(per_cat)
    g["orders_b"] = g["category_b"].map(per_cat)
    g["lift"] = g["pair_orders"] * n_orders / (g["orders_a"] * g["orders_b"])
    g = g[g["lift"] > min_lift].sort_values(["pair_orders", "lift"], ascending=False)
    return g[cols].head(top_n).reset_index(drop=True) if top_n else g[cols].reset_index(drop=True)


def generate_growth_insights(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.CATEGORY_MIN_ORDERS,
    min_customers: int = settings.SUPPLY_GAP_MIN_CUSTOMERS, min_pair_orders: int = settings.CROSS_SELL_MIN_PAIR_ORDERS,
) -> list[Insight]:
    """Evidence-based growth findings built only from the functions above."""
    out: list[Insight] = []
    cats = identify_growth_categories(engine, f, min_orders=min_orders)
    if not cats.empty:
        top = cats.head(3)
        out.append(Insight(
            "Categories with rising revenue",
            "Revenue rose most in " + ", ".join(f"{r.category} (+{r.change_pct:.0f}%)" for r in top.itertuples())
            + ". Check whether the rise is broad (many sellers/customers) before adding focus; the data cannot show why.",
            "positive", "category_revenue_trend", "last 3 non-sparse months vs the 3 before, change > 0",
            {"categories": top["category"].tolist(), "min_orders": min_orders}))
    states = identify_growth_states(engine, f)
    if not states.empty:
        top = states.head(3)
        out.append(Insight(
            "States with rising revenue",
            "Revenue rose most in " + ", ".join(f"{r.state} (+{r.change_pct:.0f}%)" for r in top.itertuples()) + ".",
            "positive", "state_revenue_trend", "last 3 non-sparse months vs the 3 before, change > 0",
            {"states": top["state"].tolist()}))
    gap = identify_underserved_states(engine, f, min_customers=min_customers)
    if not gap.empty:
        out.append(Insight(
            f"{len(gap)} state(s) look thinly served by local sellers",
            "These states have many customers per seller (or no seller). Consider seller onboarding there; sellers can "
            "also ship across states, so confirm with delivery times and freight before acting.",
            "info", "customers_per_seller", f"customers >= {min_customers} and no seller, or customers per seller >= p{int(settings.SUPPLY_GAP_QUANTILE * 100)}",
            {"states": gap["state"].tolist()[:10]}))
    pairs = identify_cross_sell_pairs(engine, f, min_pair_orders=min_pair_orders, top_n=3)
    if not pairs.empty:
        p = pairs.iloc[0]
        out.append(Insight(
            f"{p['category_a']} and {p['category_b']} are often bought together",
            f"They share {int(p['pair_orders'])} orders (lift {p['lift']:.1f}). Bundles or recommendations are worth testing.",
            "info", "category_pair_lift", f"pair in >= {min_pair_orders} orders and lift > {settings.CROSS_SELL_MIN_LIFT}",
            {"category_a": p["category_a"], "category_b": p["category_b"], "pair_orders": int(p["pair_orders"]), "lift": float(p["lift"])}))
    return out
