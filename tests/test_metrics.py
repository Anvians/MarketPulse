"""Hand-checkable metric tests on the synthetic fixture (see conftest.py).

Covers: revenue, unique order counts, customer counts, repeat purchase,
delivery time / delay / late flags, review handling and geolocation collapse.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest


def _order(tables, order_id: str) -> pd.Series:
    return tables["fact_orders"].set_index("order_id").loc[order_id]


# ----------------------------------------------------------------- counts
def test_duplicate_order_rows_removed(tables):
    fo = tables["fact_orders"]
    assert len(fo) == 6
    assert fo["order_id"].is_unique


def test_orphan_items_payments_reviews_dropped(tables):
    assert "o_missing" not in set(tables["fact_order_items"]["order_id"])
    assert "o_missing" not in set(tables["fact_reviews"]["order_id"])


def test_unique_order_count_unaffected_by_multi_item_order(tables):
    items = tables["fact_order_items"]
    assert len(items) == 6                       # 6 item rows
    assert items["order_id"].nunique() == 5      # but only 5 orders have items
    assert _order(tables, "o2")["item_count"] == 2


# ---------------------------------------------------------------- revenue
def test_order_level_aggregates(tables):
    o2 = _order(tables, "o2")
    assert o2["items_value"] == pytest.approx(120.00)
    assert o2["freight_value"] == pytest.approx(13.00)
    assert o2["order_total_value"] == pytest.approx(133.00)
    assert o2["payment_value"] == pytest.approx(133.00)
    assert o2["payment_count"] == 2
    assert o2["seller_count"] == 2


def test_revenue_orders_exclude_canceled_and_itemless(tables):
    fo = tables["fact_orders"]
    rev = fo[fo["is_revenue_order"]]
    assert set(rev["order_id"]) == {"o1", "o2", "o3", "o4"}
    assert not _order(tables, "o5")["is_revenue_order"]   # canceled
    assert not _order(tables, "o6")["is_revenue_order"]   # no items


def test_total_product_revenue_and_aov(tables):
    fo = tables["fact_orders"]
    rev = fo[fo["is_revenue_order"]]
    assert rev["items_value"].sum() == pytest.approx(100 + 120 + 200 + 30)   # 450
    assert rev["items_value"].sum() / rev["order_id"].nunique() == pytest.approx(112.5)
    # freight stays separate from product revenue
    assert rev["freight_value"].sum() == pytest.approx(10 + 13 + 20 + 3)


def test_item_sum_equals_order_sum_no_double_count(tables):
    assert tables["fact_order_items"]["price"].sum() == pytest.approx(
        tables["fact_orders"]["items_value"].sum()
    )


def test_primary_payment_type_is_largest_payment(tables):
    assert _order(tables, "o2")["primary_payment_type"] == "credit_card"
    assert _order(tables, "o3")["primary_payment_type"] == "boleto"


def test_order_without_payments_has_null_payment(tables):
    assert pd.isna(_order(tables, "o6")["payment_value"])


# --------------------------------------------------------------- customers
def test_customer_counts(tables):
    assert tables["dim_customers"]["customer_unique_id"].is_unique
    assert len(tables["dim_customers"]) == 5          # u1..u5 (six customer_ids)
    fo = tables["fact_orders"]
    rev = fo[fo["is_revenue_order"]]
    assert rev["customer_unique_id"].nunique() == 3   # u1, u2, u3


def test_repeat_purchase_rate_uses_unique_person_and_qualifying_orders(tables):
    fo = tables["fact_orders"]
    per_person = fo[fo["is_revenue_order"]].groupby("customer_unique_id")["order_id"].nunique()
    assert (per_person > 1).sum() == 1        # only u1 (o1 + o2)
    assert (per_person > 1).sum() / len(per_person) == pytest.approx(1 / 3)


# ---------------------------------------------------------------- delivery
def test_delivery_time_days(tables):
    # 2017-01-10 10:00 -> 2017-01-20 15:00 = 10 days 5 hours
    assert _order(tables, "o1")["delivery_days"] == pytest.approx(10 + 5 / 24, abs=0.01)


def test_delay_and_late_flags_compare_dates(tables):
    assert _order(tables, "o1")["delivery_delay_days"] == -5
    assert not _order(tables, "o1")["is_late"]
    assert _order(tables, "o2")["delivery_delay_days"] == 5
    assert _order(tables, "o2")["is_late"]
    # delivered 18:00 on the estimated date -> on time (date comparison)
    assert _order(tables, "o3")["delivery_delay_days"] == 0
    assert not _order(tables, "o3")["is_late"]


def test_undelivered_orders_have_null_delivery_metrics(tables):
    for oid in ("o4", "o5", "o6"):
        row = _order(tables, oid)
        assert not row["has_valid_delivery_dates"]
        assert pd.isna(row["delivery_days"])
        assert pd.isna(row["delivery_delay_days"])
        assert pd.isna(row["is_late"])


def test_on_time_and_late_rates(tables):
    fo = tables["fact_orders"]
    valid = fo[fo["has_valid_delivery_dates"]]
    assert len(valid) == 3
    assert valid["is_late"].sum() == 1
    assert (~valid["is_late"].astype(bool)).sum() / len(valid) == pytest.approx(2 / 3)


# ----------------------------------------------------------------- reviews
def test_duplicate_review_key_collapsed(tables):
    fr = tables["fact_reviews"]
    assert len(fr[(fr["review_id"] == "r1") & (fr["order_id"] == "o1")]) == 1


def test_invalid_review_score_dropped(tables):
    fr = tables["fact_reviews"]
    assert "r_bad" not in set(fr["review_id"])
    assert fr["review_score"].between(1, 5).all()


def test_review_score_average_by_review_rows(tables):
    fr = tables["fact_reviews"]
    # rows: r1=5, r2=1, r2b=3, r3=4
    assert fr["review_score"].mean() == pytest.approx((5 + 1 + 3 + 4) / 4)


# ---------------------------------------------------------------- dimensions
def test_geolocation_one_row_per_prefix_and_outliers_dropped(tables):
    geo = tables["dim_geolocation"]
    assert geo["zip_prefix"].is_unique
    assert "99999" not in set(geo["zip_prefix"])           # outside Brazil
    sp = geo.set_index("zip_prefix").loc["01046"]
    assert sp["source_row_count"] == 3
    assert sp["latitude"] == pytest.approx(-23.56)


def test_zip_prefix_keeps_leading_zero(tables):
    assert "01046" in set(tables["dim_customers"]["zip_prefix"])


def test_category_translation_and_fallbacks(tables):
    p = tables["dim_products"].set_index("product_id")
    assert p.loc["p1", "category_en"] == "bed_bath_table"
    assert p.loc["p3", "category_en"] == "categoria_sem_traducao"   # kept Portuguese name
    assert p.loc["p4", "category_en"] == "unknown"
    assert p.loc["p1", "volume_cm3"] == pytest.approx(20 * 10 * 15)


def test_dim_date_is_contiguous_and_covers_orders(tables):
    dd = tables["dim_date"]
    assert dd["date_key"].is_unique
    full = pd.date_range(dd["full_date"].min(), dd["full_date"].max(), freq="D")
    assert len(dd) == len(full)
    fo = tables["fact_orders"]
    assert fo["purchase_date_key"].dropna().isin(dd["date_key"]).all()
    assert fo["delivered_date_key"].dropna().isin(dd["date_key"]).all()
    row = dd.set_index("date_key").loc[20170110]
    assert row["year_month"] == "2017-01" and row["weekday_name"] == "Tuesday"


def test_transformation_log_records_cleaning_steps(transformed):
    log = transformed.log.to_frame()
    steps = " | ".join(log["step"])
    assert "duplicate rows" in steps
    assert "orphan" in steps
    assert "outside Brazil" in steps
    assert not math.isnan(len(log))
