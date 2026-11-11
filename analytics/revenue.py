"""Revenue intelligence.

Revenue = product revenue (sum of item price on revenue orders). It is **not
profit**: the dataset has no product costs or operating expenses. Freight is
reported separately and never added to revenue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import (
    Filters,
    flag_sparse_months,
    item_scope,
    read_sql,
    revenue_by,
    safe_div,
    summarize_numeric,
)
from config import settings


def calculate_monthly_revenue(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per month: revenue, freight, orders, items, ``mom_growth_pct`` (change vs the
    previous row; NaN after/before a sparse month) and ``is_sparse``."""
    m = flag_sparse_months(revenue_by(engine, f, "month"))
    if m.empty:
        m["mom_growth_pct"] = pd.Series(dtype=float)
        return m
    growth = 100 * m["revenue"].pct_change()
    unreliable = m["is_sparse"] | m["is_sparse"].shift(1, fill_value=False)
    m["mom_growth_pct"] = growth.where(~unreliable)
    return m


def calculate_revenue_growth(engine: Engine, f: Filters | None = None) -> dict:
    """Growth of the latest non-sparse month vs the previous non-sparse month.

    Sparse edge months (see ``flag_sparse_months``) are excluded and listed, so
    growth is never an artefact of comparing a near-empty month with a full one.
    This is **observed historical** growth, not a forecast."""
    m = flag_sparse_months(revenue_by(engine, f, "month"))
    excluded = m.loc[m["is_sparse"], "year_month"].tolist() if not m.empty else []
    full = m[~m["is_sparse"]].reset_index(drop=True) if not m.empty else m
    if len(full) < 2:
        return {"available": False, "excluded_sparse_months": excluded, "growth_pct": None}
    last, prev = full.iloc[-1], full.iloc[-2]
    return {
        "available": True,
        "latest_month": last["year_month"], "previous_month": prev["year_month"],
        "latest_revenue": float(last["revenue"]), "previous_revenue": float(prev["revenue"]),
        "growth_pct": None if prev["revenue"] == 0 else float(100 * (last["revenue"] / prev["revenue"] - 1)),
        "excluded_sparse_months": excluded,
    }


def calculate_revenue_by_category(engine: Engine, f: Filters | None = None, limit: int | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "category", limit)


def calculate_revenue_by_seller(engine: Engine, f: Filters | None = None, limit: int | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "seller", limit)


def calculate_revenue_by_state(engine: Engine, f: Filters | None = None, limit: int | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "state", limit)


def calculate_revenue_by_payment(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Revenue of orders grouped by the order's *primary* payment type (the type
    with the largest payment value; orders can mix types, e.g. card + voucher)."""
    return revenue_by(engine, f, "payment")


def calculate_category_revenue_contribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Categories with ``revenue_share_pct`` and ``cumulative_share_pct`` (Pareto)."""
    c = revenue_by(engine, f, "category")
    c["cumulative_share_pct"] = c["revenue_share_pct"].cumsum()
    return c


def calculate_average_order_value_trend(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per month: revenue / distinct revenue orders (product revenue, excl. freight)."""
    m = flag_sparse_months(revenue_by(engine, f, "month"))
    m["avg_order_value"] = m["revenue"] / m["orders"].replace(0, np.nan)
    return m[["year_month", "orders", "revenue", "avg_order_value", "is_sparse"]]


def calculate_revenue_distribution(engine: Engine, f: Filters | None = None) -> dict:
    """Distribution of per-order product revenue: ``orders`` (DataFrame order_id,
    order_value) and ``summary`` (count, mean, median, quartiles, p90, min, max)."""
    s = item_scope(f)
    orders = read_sql(
        engine,
        "SELECT i.order_id, SUM(i.price) AS order_value\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nGROUP BY i.order_id ORDER BY i.order_id",
        s.params)
    return {"orders": orders, "summary": summarize_numeric(orders["order_value"])}


def calculate_revenue_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """KPI-card values for the Revenue Intelligence page; freight shown separately."""
    s = item_scope(f)
    row = read_sql(
        engine,
        "SELECT COALESCE(SUM(i.price), 0) AS revenue, COALESCE(SUM(i.freight_value), 0) AS freight, "
        "COUNT(DISTINCT i.order_id) AS orders, COUNT(DISTINCT o.customer_unique_id) AS customers\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params).iloc[0]
    growth = calculate_revenue_growth(engine, f)
    top_cat = revenue_by(engine, f, "category", limit=1)
    return {
        "total_revenue": float(row["revenue"]),
        "freight_charges": float(row["freight"]),
        "avg_order_value": safe_div(row["revenue"], row["orders"]),
        "revenue_per_customer": safe_div(row["revenue"], row["customers"]),
        "revenue_growth_pct": growth["growth_pct"],
        "revenue_growth_basis": (f"{growth['previous_month']} -> {growth['latest_month']}" if growth["available"] else None),
        "top_category": None if top_cat.empty else top_cat.iloc[0]["category"],
        "top_category_share_pct": None if top_cat.empty else float(top_cat.iloc[0]["revenue_share_pct"]),
    }


def _category_period_change(engine: Engine, f: Filters | None, periods: int = 3) -> pd.DataFrame:
    """Revenue of the last ``periods`` non-sparse months vs the ``periods`` before them, by category."""
    months = flag_sparse_months(revenue_by(engine, f, "month"))
    full = months[~months["is_sparse"]]["year_month"].tolist()
    cols = ["category", "recent_revenue", "prior_revenue", "change_pct", "recent_months", "prior_months"]
    if len(full) < 2 * periods:
        return pd.DataFrame(columns=cols)
    recent, prior = full[-periods:], full[-2 * periods:-periods]
    s = item_scope(f)
    df = read_sql(
        engine,
        "SELECT p.category_en AS category, d.year_month, SUM(i.price) AS revenue\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order', 'd.year_month = ANY(:window)')}\nGROUP BY 1, 2",
        {**s.params, "window": recent + prior})
    df["is_recent"] = df["year_month"].isin(recent)
    g = df.pivot_table(index="category", columns="is_recent", values="revenue", aggfunc="sum", fill_value=0.0)
    out = pd.DataFrame({"recent_revenue": g.get(True, 0.0), "prior_revenue": g.get(False, 0.0)}).reset_index()
    out["change_pct"] = 100 * (out["recent_revenue"] / out["prior_revenue"].replace(0, np.nan) - 1)
    out["recent_months"] = ", ".join(recent)
    out["prior_months"] = ", ".join(prior)
    return out[cols]


def identify_revenue_opportunities(engine: Engine, f: Filters | None = None) -> dict[str, pd.DataFrame]:
    """Rule-based revenue findings, each a DataFrame (rule documented per key).

    * ``high_revenue_categories``: smallest set of top categories making up 80% of revenue.
    * ``low_performing_categories``: categories with < 1% revenue share and < ``CATEGORY_MIN_ORDERS`` orders.
    * ``declining_categories``: categories whose revenue in the last 3 non-sparse months is
      lower than in the 3 months before (needs >= 6 non-sparse months), worst first.
    * ``top_states``: states making up 80% of revenue.
    * ``seller_concentration``: top 10 sellers with their cumulative revenue share.
    """
    cat = calculate_category_revenue_contribution(engine, f)
    high = cat[(cat["cumulative_share_pct"] - cat["revenue_share_pct"]) < 80.0] if not cat.empty else cat
    low = cat[(cat["revenue_share_pct"] < 1.0) & (cat["orders"] < settings.CATEGORY_MIN_ORDERS)] if not cat.empty else cat
    change = _category_period_change(engine, f)
    declining = change[(change["change_pct"] < 0) & (change["prior_revenue"] > 0)].sort_values(
        "change_pct").reset_index(drop=True) if not change.empty else change
    st = revenue_by(engine, f, "state")
    st["cumulative_share_pct"] = st["revenue_share_pct"].cumsum()
    top_states = st[(st["cumulative_share_pct"] - st["revenue_share_pct"]) < 80.0] if not st.empty else st
    sel = revenue_by(engine, f, "seller", limit=10)
    sel["cumulative_share_pct"] = sel["revenue_share_pct"].cumsum()
    return {
        "high_revenue_categories": high.reset_index(drop=True),
        "low_performing_categories": low.reset_index(drop=True),
        "declining_categories": declining,
        "top_states": top_states.reset_index(drop=True),
        "seller_concentration": sel,
    }


def generate_revenue_recommendations(opportunities: dict[str, pd.DataFrame]) -> list:
    """Evidence-based recommendations built ONLY from the findings in
    :func:`identify_revenue_opportunities` (each carries the numbers and the rule that
    produced it). They are prompts for investigation, not forecasts or causal claims."""
    from analytics.base import Insight

    out: list[Insight] = []
    high = opportunities.get("high_revenue_categories")
    if high is not None and not high.empty:
        top = high.iloc[0]
        if top["revenue_share_pct"] >= settings.CONCENTRATION_ALERT_PCT:
            out.append(Insight(
                f"Revenue is concentrated in {top['category']} ({top['revenue_share_pct']:.1f}%)",
                "One category carries a large part of product revenue. Review dependence on it and "
                "test growth in the next-largest categories.",
                "warning", "category_revenue_share",
                f"single category share >= {settings.CONCENTRATION_ALERT_PCT:.0f}%",
                {"category": top["category"], "share_pct": float(top["revenue_share_pct"])}))
        out.append(Insight(
            f"{len(high)} categories generate 80% of product revenue",
            "Prioritise merchandising, promotions and stock-quality checks on these categories first.",
            "info", "category_revenue_pareto", "smallest set of categories reaching 80% cumulative share",
            {"categories": high["category"].tolist()[:10], "count": int(len(high))}))
    declining = opportunities.get("declining_categories")
    if declining is not None and not declining.empty:
        worst = declining.head(3)
        names = ", ".join(f"{r.category} ({r.change_pct:.0f}%)" for r in worst.itertuples())
        out.append(Insight(
            "Categories with falling revenue", f"Revenue fell most in: {names}. Investigate pricing, availability "
            "and seller changes (the data cannot say which caused the drop).",
            "warning", "category_revenue_trend", "last 3 non-sparse months vs the 3 before, change < 0",
            {"categories": worst["category"].tolist()}))
    states = opportunities.get("top_states")
    if states is not None and not states.empty:
        out.append(Insight(
            f"{len(states)} states generate 80% of product revenue",
            "Revenue is geographically concentrated; compare marketing and delivery reach in the remaining states "
            "before investing in expansion.",
            "info", "state_revenue_pareto", "smallest set of states reaching 80% cumulative share",
            {"states": states["state"].tolist()}))
    sel = opportunities.get("seller_concentration")
    if sel is not None and not sel.empty:
        top10 = float(sel["cumulative_share_pct"].iloc[-1])
        if top10 >= settings.CONCENTRATION_ALERT_PCT:
            out.append(Insight(
                f"Top {len(sel)} sellers hold {top10:.1f}% of revenue",
                "Marketplace revenue depends on a few sellers; explore partnership terms and onboarding of "
                "similar sellers to reduce dependency.",
                "warning", "seller_revenue_concentration",
                f"top-10 seller share >= {settings.CONCENTRATION_ALERT_PCT:.0f}%", {"top10_share_pct": top10}))
    return out
