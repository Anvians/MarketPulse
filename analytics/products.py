"""Product and category performance.

Category review score = mean of the order-level review of orders that contain
the category (an order spanning two categories contributes its review to both).
There is **no inventory data**, so nothing here speaks to stock levels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import Filters, item_scope, read_sql, revenue_by, scalar, summarize_numeric
from config import settings


def get_top_selling_products(engine: Engine, f: Filters | None = None, top_n: int = 10) -> pd.DataFrame:
    """Products by units sold (ties: higher revenue first). Includes freight_ratio
    (freight / price)."""
    return _product_table(engine, f, "units DESC, revenue DESC, i.product_id", top_n)


def get_bottom_selling_products(engine: Engine, f: Filters | None = None, top_n: int = 10) -> pd.DataFrame:
    """Products that sold, fewest units first. Many products sold exactly once;
    ties are broken by lower revenue."""
    return _product_table(engine, f, "units ASC, revenue ASC, i.product_id", top_n)


def _product_table(engine: Engine, f: Filters | None, order_by: str, top_n: int | None) -> pd.DataFrame:
    s = item_scope(f)
    sql = (
        "SELECT i.product_id, p.category_en AS category, COUNT(*) AS units, SUM(i.price) AS revenue, "
        "AVG(i.price) AS avg_price, SUM(i.freight_value) AS freight, "
        "SUM(i.freight_value) / NULLIF(SUM(i.price), 0) AS freight_ratio\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nGROUP BY i.product_id, p.category_en\n"
        f"ORDER BY {order_by}"
    )
    if top_n:
        sql += f" LIMIT {int(top_n)}"
    return read_sql(engine, sql, s.params)


def get_top_categories_by_revenue(engine: Engine, f: Filters | None = None, top_n: int = 10) -> pd.DataFrame:
    return revenue_by(engine, f, "category", top_n)


def get_bottom_categories_by_revenue(engine: Engine, f: Filters | None = None, top_n: int = 10) -> pd.DataFrame:
    c = revenue_by(engine, f, "category")
    return c.sort_values(["revenue", "category"]).head(top_n).reset_index(drop=True)


def get_categories_by_quantity(engine: Engine, f: Filters | None = None, top_n: int | None = 10) -> pd.DataFrame:
    """Categories by units sold: category, items (units), revenue."""
    c = revenue_by(engine, f, "category").sort_values(["items", "revenue", "category"], ascending=[False, False, True])
    out = c[["category", "items", "orders", "revenue"]].reset_index(drop=True)
    return out.head(top_n) if top_n else out


def calculate_average_product_price(engine: Engine, f: Filters | None = None) -> float | None:
    """Mean item price over items sold (item-weighted, so popular products weigh more)."""
    s = item_scope(f)
    return scalar(engine, f"SELECT AVG(i.price) FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params)


def calculate_category_revenue(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    return revenue_by(engine, f, "category")


def calculate_category_review_score(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Per category: avg_review_score, reviews (order-level reviews of orders containing it)."""
    s = item_scope(f)
    sql = (
        "WITH co AS (SELECT p.category_en AS category, i.order_id\n"
        f"  FROM {s.from_sql}\n  {s.where('o.is_revenue_order')}\n  GROUP BY 1, 2)\n"
        "SELECT co.category, AVG(r.review_score) AS avg_review_score, COUNT(r.review_score) AS reviews\n"
        "FROM co LEFT JOIN vw_order_review r ON r.order_id = co.order_id\n"
        "GROUP BY co.category ORDER BY avg_review_score DESC NULLS LAST, co.category"
    )
    return read_sql(engine, sql, s.params)


def calculate_category_summary(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """One table per category: revenue, share, orders, units, avg_price, freight,
    freight_ratio, avg_review_score, reviews."""
    rev = revenue_by(engine, f, "category")
    if rev.empty:
        return rev
    rev["avg_price"] = rev["revenue"] / rev["items"]
    rev["freight_ratio"] = rev["freight"] / rev["revenue"].replace(0, np.nan)
    out = rev.merge(calculate_category_review_score(engine, f), on="category", how="left")
    return out.rename(columns={"items": "units"})


def _product_attributes(engine: Engine, f: Filters | None) -> pd.DataFrame:
    s = item_scope(f)
    return read_sql(
        engine,
        "SELECT DISTINCT i.product_id, p.category_en AS category, p.weight_g, p.length_cm, p.height_cm, "
        "p.width_cm, p.volume_cm3\n"
        f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}\nORDER BY i.product_id", s.params)


def calculate_product_weight_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Sold products with weight_g (NaN when the source has none)."""
    return _product_attributes(engine, f)[["product_id", "category", "weight_g"]]


def calculate_product_dimension_analysis(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Sold products with length/height/width (cm) and volume_cm3."""
    return _product_attributes(engine, f)[["product_id", "category", "length_cm", "height_cm", "width_cm", "volume_cm3"]]


def calculate_product_attribute_summary(engine: Engine, f: Filters | None = None) -> dict:
    """Summary statistics of weight and volume over sold products, plus how many lack values."""
    a = _product_attributes(engine, f)
    return {
        "products": int(len(a)),
        "weight_g": summarize_numeric(a["weight_g"]),
        "volume_cm3": summarize_numeric(a["volume_cm3"]),
        "missing_weight": int(a["weight_g"].isna().sum()),
        "missing_dimensions": int(a["volume_cm3"].isna().sum()),
    }


def calculate_product_price_distribution(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Item prices (for histograms): product_id, category, price."""
    s = item_scope(f)
    return read_sql(engine, "SELECT i.product_id, p.category_en AS category, i.price\n"
                            f"FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params)


def calculate_product_kpis(engine: Engine, f: Filters | None = None) -> dict:
    """KPI-card values for the Product Performance page."""
    cat = calculate_category_summary(engine, f)
    s = item_scope(f)
    products = scalar(engine, f"SELECT COUNT(DISTINCT i.product_id) FROM {s.from_sql}\n{s.where('o.is_revenue_order')}", s.params)
    avg_review = scalar(
        engine,
        "SELECT AVG(r.review_score) FROM vw_order_review r WHERE r.order_id IN "
        f"(SELECT DISTINCT i.order_id FROM {s.from_sql}\n{s.where('o.is_revenue_order')})", s.params)
    return {
        "products_sold": int(products or 0),
        "total_units": int(cat["units"].sum()) if not cat.empty else 0,
        "categories": int(len(cat)),
        "avg_product_price": calculate_average_product_price(engine, f),
        "top_revenue_category": None if cat.empty else cat.sort_values("revenue", ascending=False).iloc[0]["category"],
        "best_selling_category": None if cat.empty else cat.sort_values("units", ascending=False).iloc[0]["category"],
        "avg_product_review_score": avg_review,
    }


def build_product_performance_matrix(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.CATEGORY_MIN_ORDERS,
) -> pd.DataFrame:
    """Category matrix on revenue, volume, review score and average price.

    Quadrants use two transparent cut-offs: revenue vs the median revenue of the
    *judgeable* categories (those with >= ``min_orders`` orders and at least one
    review, so tiny or unreviewed categories do not drag the median down), and
    review score vs the overall average order review in the current scope.
    * Star: revenue >= median and review >= average
    * Fix quality: revenue >= median and review < average
    * Grow / promote: revenue < median and review >= average
    * Rethink: revenue < median and review < average
    * Insufficient data: fewer than ``min_orders`` orders or no reviews
    """
    c = calculate_category_summary(engine, f)
    cols = ["category", "revenue", "units", "orders", "avg_price", "avg_review_score", "quadrant"]
    if c.empty:
        return pd.DataFrame(columns=cols)
    ok = (c["orders"] >= min_orders) & c["avg_review_score"].notna()
    scored = c[ok]
    median_rev = scored["revenue"].median() if len(scored) else np.nan
    from analytics.executive import calculate_average_review_score
    overall = calculate_average_review_score(engine, f)   # one review per order, current scope

    def quadrant(row: pd.Series) -> str:
        if not ok.loc[row.name]:
            return "Insufficient data"
        high_rev = row["revenue"] >= median_rev
        good = row["avg_review_score"] >= overall
        return ("Star" if good else "Fix quality") if high_rev else ("Grow / promote" if good else "Rethink")

    c["quadrant"] = c.apply(quadrant, axis=1)
    return c[cols].sort_values("revenue", ascending=False).reset_index(drop=True)


def identify_underperforming_categories(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.CATEGORY_MIN_ORDERS,
) -> pd.DataFrame:
    """Categories flagged by transparent rules (``reasons`` lists the triggers):
    * low demand: orders below the 25th percentile of category orders;
    * poor reviews: average review < ``LOW_REVIEW_THRESHOLD`` (needs >= ``min_orders`` reviews).
    """
    c = calculate_category_summary(engine, f)
    cols = ["category", "revenue", "orders", "avg_review_score", "reviews", "reasons"]
    if c.empty:
        return pd.DataFrame(columns=cols)
    p25 = c["orders"].quantile(0.25)
    low_demand = c["orders"] < p25
    poor = (c["avg_review_score"] < settings.LOW_REVIEW_THRESHOLD) & (c["reviews"] >= min_orders)
    # min_orders for reviews is capped so tiny test/filtered datasets can still be assessed
    c["reasons"] = [
        "; ".join(filter(None, [
            f"low demand ({int(o)} orders < p25 {p25:.1f})" if ld else "",
            f"poor reviews ({r:.2f} < {settings.LOW_REVIEW_THRESHOLD})" if pr else "",
        ]))
        for o, r, ld, pr in zip(c["orders"], c["avg_review_score"], low_demand, poor)
    ]
    return c[low_demand | poor][cols].sort_values("revenue").reset_index(drop=True)


def get_products_with_high_freight(
    engine: Engine, f: Filters | None = None, ratio: float = settings.HIGH_FREIGHT_RATIO,
    min_units: int = 5, top_n: int | None = 20,
) -> pd.DataFrame:
    """Products whose total freight is >= ``ratio`` x their total price (and sold
    >= ``min_units`` units): candidates for shipping-cost review."""
    t = _product_table(engine, f, "freight_ratio DESC NULLS LAST, i.product_id", None)
    t = t[(t["freight_ratio"] >= ratio) & (t["units"] >= min_units)].reset_index(drop=True)
    return t.head(top_n) if top_n else t


def get_products_worth_promoting(
    engine: Engine, f: Filters | None = None, min_orders: int = settings.CATEGORY_MIN_ORDERS,
) -> pd.DataFrame:
    """Categories in the 'Grow / promote' quadrant: well reviewed but below-median revenue."""
    m = build_product_performance_matrix(engine, f, min_orders)
    return m[m["quadrant"] == "Grow / promote"].reset_index(drop=True)
