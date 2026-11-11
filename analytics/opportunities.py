"""Business opportunity finder: one prioritised table of rule-based findings.

Each row is produced by a stated rule from an existing analytics function, carries
its evidence, and is ranked by ``observed_revenue`` (the revenue the finding
touches, from the data). That is a size of the thing to look at, NOT a forecast of
gain: the data has no costs, no experiments and no causal evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics import customers, logistics, products, satisfaction, sellers
from analytics.base import Filters, revenue_by
from config import settings

COLUMNS = ["priority", "area", "subject", "finding", "evidence", "rule", "investigate", "observed_revenue"]


def _row(area, subject, finding, evidence, rule, investigate, revenue):
    return {"area": area, "subject": subject, "finding": finding, "evidence": evidence, "rule": rule,
            "investigate": investigate, "observed_revenue": None if revenue is None or pd.isna(revenue) else float(revenue)}


def find_business_opportunities(engine: Engine, f: Filters | None = None, **thresholds) -> pd.DataFrame:
    """All opportunity rows, highest ``observed_revenue`` first (``priority`` 1 = largest).

    ``thresholds`` may override ``min_category_orders`` / ``min_seller_orders`` /
    ``min_state_orders`` (defaults from ``config.settings``)."""
    min_cat = thresholds.get("min_category_orders", settings.CATEGORY_MIN_ORDERS)
    min_sel = thresholds.get("min_seller_orders", settings.SELLER_MIN_ORDERS)
    min_state = thresholds.get("min_state_orders", settings.STATE_MIN_ORDERS)
    rows: list[dict] = []

    # 1. product: weak categories
    for r in products.identify_underperforming_categories(engine, f, min_orders=min_cat).itertuples():
        rows.append(_row("Products", r.category, f"Category underperforms: {r.reasons}",
                         f"revenue R$ {r.revenue:,.0f}; {int(r.orders)} orders; avg review "
                         + ("n/a" if pd.isna(r.avg_review_score) else f"{r.avg_review_score:.2f}"),
                         f"orders below the 25th percentile of categories, or avg review < {settings.LOW_REVIEW_THRESHOLD} with >= {min_cat} reviews",
                         "Range, pricing, listing quality and seller mix in this category", r.revenue))
    # 2. product: well-liked but small
    for r in products.get_products_worth_promoting(engine, f, min_orders=min_cat).itertuples():
        rows.append(_row("Products", r.category, "Well reviewed but below-median revenue",
                         f"revenue R$ {r.revenue:,.0f}; {int(r.orders)} orders; avg review {r.avg_review_score:.2f}",
                         f"quadrant 'Grow / promote': review above median and revenue below median, >= {min_cat} orders",
                         "Visibility, promotion and assortment; quality is not the constraint", r.revenue))
    # 3. logistics bottlenecks (revenue looked up from the same scope)
    bn = logistics.identify_logistics_bottlenecks(engine, f, min_state_orders=min_state, min_seller_orders=min_sel)
    if not bn.empty:
        rev_state = revenue_by(engine, f, "state").set_index("state")["revenue"]
        rev_seller = revenue_by(engine, f, "seller").set_index("seller_id")["revenue"]
        for r in bn.itertuples():
            rev = (rev_state if r.level == "state" else rev_seller).get(r.name, np.nan)
            rows.append(_row("Logistics", f"{r.level}: {r.name}", f"Late-delivery rate {r.times_overall:.1f}x the overall rate",
                             f"late rate {r.late_rate:.1%} vs overall {r.overall_late_rate:.1%}; {int(r.orders)} delivered orders",
                             f"late rate >= {settings.LOGISTICS_BOTTLENECK_FACTOR}x overall, with enough delivered orders",
                             "Carrier, handling time and the estimated-date promise for this " + r.level, rev))
    # 4. sellers
    for r in sellers.identify_underperforming_sellers(engine, f, min_orders=min_sel).itertuples():
        rows.append(_row("Sellers", r.seller_id, f"Seller breaches service rules: {r.reasons}",
                         f"revenue R$ {r.revenue:,.0f}; {int(r.orders)} orders",
                         f"late rate > {settings.SELLER_HIGH_LATE_RATE:.0%} or avg review < {settings.LOW_REVIEW_THRESHOLD}, >= {min_sel} orders",
                         "Seller coaching, fulfilment performance or removal from featured placement", r.revenue))
    # 5. freight
    fr = logistics.calculate_freight_by_category(engine, f)
    if not fr.empty:
        crev = revenue_by(engine, f, "category").set_index("category")["revenue"]
        for r in fr[fr["freight_to_price"] >= settings.HIGH_FREIGHT_RATIO].itertuples():
            rows.append(_row("Pricing & freight", r.category, "Freight is a large share of the item price",
                             f"freight/price {r.freight_to_price:.0%}; avg price R$ {r.avg_price:,.0f}; {int(r.items)} items",
                             f"freight / item price >= {settings.HIGH_FREIGHT_RATIO:.0%}",
                             "Freight subsidies, regional sellers or bundling to lift basket size", crev.get(r.category, np.nan)))
    # 6. retention
    rate = customers.calculate_repeat_purchase_rate(engine, f)
    if rate is not None and rate < settings.LOW_REPEAT_RATE:
        single = customers.identify_single_purchase_customers(engine, f)
        rows.append(_row("Customers", "all customers in scope", "Few customers buy again",
                         f"repeat-purchase rate {rate:.1%}; one-order customers are {single['customer_share']:.1%} of customers "
                         f"and {single['revenue_share']:.1%} of revenue",
                         f"repeat-purchase rate < {settings.LOW_REPEAT_RATE:.0%}",
                         "Post-purchase follow-up, loyalty offers, and whether the marketplace is mostly one-off purchases",
                         single["revenue"]))
    # 7. satisfaction
    for r in satisfaction.identify_low_satisfaction_categories(engine, f).itertuples():
        rows.append(_row("Satisfaction", r.category, "Low average review score",
                         f"avg review {r.avg_review_score:.2f}; negative-review rate {r.negative_rate:.1%}; {int(r.reviews)} reviews",
                         f"avg review < {settings.LOW_REVIEW_THRESHOLD} with enough reviews", "Read review comments, product quality and delivery for this category",
                         revenue_by(engine, f, "category").set_index("category")["revenue"].get(r.category, np.nan)))

    df = pd.DataFrame(rows, columns=[c for c in COLUMNS if c != "priority"])
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.sort_values(["observed_revenue", "area", "subject"], ascending=[False, True, True], na_position="last").reset_index(drop=True)
    df.insert(0, "priority", range(1, len(df) + 1))
    return df


def summarize_opportunities(opps: pd.DataFrame) -> pd.DataFrame:
    """Findings and revenue touched per area."""
    if opps.empty:
        return pd.DataFrame(columns=["area", "findings", "observed_revenue"])
    return (opps.groupby("area").agg(findings=("subject", "size"), observed_revenue=("observed_revenue", "sum"))
            .reset_index().sort_values("findings", ascending=False))
