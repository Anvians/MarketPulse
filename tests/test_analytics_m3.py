"""Tests for the Milestone 3 analytics additions (satisfaction, geography, system, exports,
revenue recommendations). Same hand-computed synthetic fixture as test_analytics.py:

reviews (one per order, latest): o1=5 (Jan, SP, credit, s1, bed)  o2=3 (Mar, SP, credit, s1+s2, bed+sports)
                                 o3=4 (Feb, RJ, boleto, s2, sports)  o4 unreviewed (Mar, MG)
delay: o1 -5d, o2 +5d, o3 0d.   freight: o1 10, o2 13 (5+8), o3 20, o4 3.
sellers: s1 SP (campinas), s2 RJ (rio de janeiro).  customers: u1 SP (o1,o2), u2 RJ, u3 MG.
"""
from __future__ import annotations

from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from analytics import geography, revenue, satisfaction, system
from analytics.base import Filters
from reports import csv_exporter, excel_generator

pytestmark = pytest.mark.usefixtures("warehouse")


@pytest.fixture()
def eng(warehouse):
    return warehouse


def by(df: pd.DataFrame, key: str, col: str) -> dict:
    return dict(zip(df[key], df[col]))


# ============================================================== satisfaction
def test_review_distribution_always_has_five_scores(eng):
    d = satisfaction.calculate_review_distribution(eng)
    assert list(d["score"]) == [1, 2, 3, 4, 5]
    assert list(d["reviews"]) == [0, 0, 1, 1, 1]
    assert d["share"].sum() == pytest.approx(1.0)


def test_distribution_for_empty_scope_has_zero_reviews_and_nan_share(eng):
    d = satisfaction.calculate_review_distribution(eng, Filters(states=("AC",)))
    assert d["reviews"].sum() == 0 and d["share"].isna().all()
    assert satisfaction.calculate_negative_review_percentage(eng, Filters(states=("AC",))) is None


def test_satisfaction_kpis(eng):
    k = satisfaction.calculate_satisfaction_kpis(eng)
    assert k["avg_review_score"] == pytest.approx(4.0) and k["total_reviews"] == 3
    assert (k["one_star"], k["two_star"], k["five_star"]) == (0, 0, 1)
    assert k["negative_review_rate"] == 0.0


def test_negative_rate_counts_scores_one_and_two(eng):
    """Temporarily give o3 a later 1-star review (the latest review per order wins), then remove it."""
    from sqlalchemy import text
    with eng.begin() as c:
        c.execute(text("INSERT INTO fact_reviews (review_id, order_id, review_score, review_creation_ts) "
                       "VALUES ('r_tmp', 'o3', 1, '2017-03-01')"))
    try:
        d = satisfaction.calculate_review_distribution(eng).set_index("score")["reviews"]
        assert d[1] == 1 and d[4] == 0                                    # o3 now counts as 1 star, not 4
        assert satisfaction.calculate_negative_review_percentage(eng) == pytest.approx(1 / 3)
        k = satisfaction.calculate_satisfaction_kpis(eng)
        assert k["one_star"] == 1 and k["avg_review_score"] == pytest.approx(3.0)      # (5 + 3 + 1) / 3
        t = satisfaction.analyze_review_trends(eng).set_index("year_month")
        assert t.loc["2017-02", "negative_rate"] == 1.0 and t.loc["2017-01", "negative_rate"] == 0.0
    finally:
        with eng.begin() as c:
            c.execute(text("DELETE FROM fact_reviews WHERE review_id = 'r_tmp'"))
    assert satisfaction.calculate_negative_review_percentage(eng) == 0.0   # fixture restored


def test_review_trends(eng):
    t = satisfaction.analyze_review_trends(eng)
    assert by(t, "year_month", "avg_review_score") == {"2017-01": 5.0, "2017-02": 4.0, "2017-03": 3.0}
    assert by(t, "year_month", "reviews") == {"2017-01": 1, "2017-02": 1, "2017-03": 1}
    assert not t["is_sparse"].any()


def test_reviews_by_category_excludes_unreviewed(eng):
    c = satisfaction.analyze_reviews_by_category(eng)
    assert by(c, "category", "avg_review_score") == {"bed_bath_table": 4.0, "sports_leisure": 3.5}
    assert by(c, "category", "reviews") == {"bed_bath_table": 2, "sports_leisure": 2}
    assert "categoria_sem_traducao" not in set(c["category"])          # o4 has no review
    assert satisfaction.analyze_reviews_by_category(eng, min_reviews=3).empty


def test_reviews_by_seller_state_payment(eng):
    assert by(satisfaction.analyze_reviews_by_seller(eng), "seller_id", "avg_review_score") == {"s1": 4.0, "s2": 3.5}
    st = satisfaction.analyze_reviews_by_state(eng)
    assert by(st, "state", "reviews") == {"SP": 2, "RJ": 1}
    assert by(satisfaction.analyze_reviews_by_payment(eng), "payment_type", "avg_review_score") == {"credit_card": 4.0, "boleto": 4.0}


def test_delivery_review_buckets(eng):
    d = satisfaction.analyze_delivery_review_relationship(eng).set_index("bucket")
    assert d.loc["On time or early", "orders"] == 2 and d.loc["On time or early", "avg_review_score"] == pytest.approx(4.5)
    assert d.loc["4-7 days late", "orders"] == 1 and d.loc["4-7 days late", "avg_review_score"] == pytest.approx(3.0)
    assert list(d["sort_key"]) == sorted(d["sort_key"])               # ordered from best to worst


def test_late_vs_on_time_comparison(eng):
    c = satisfaction.compare_late_vs_on_time_reviews(eng)
    assert c["late_avg"] == pytest.approx(3.0) and c["late_orders"] == 1
    assert c["on_time_avg"] == pytest.approx(4.5) and c["on_time_orders"] == 2
    assert c["difference"] == pytest.approx(-1.5)
    empty = satisfaction.compare_late_vs_on_time_reviews(eng, Filters(states=("AC",)))
    assert empty["difference"] is None and empty["late_orders"] == 0


def test_low_satisfaction_rules(eng):
    assert satisfaction.identify_low_satisfaction_categories(eng, min_reviews=1).empty              # 3.5 is not < 3.5
    low = satisfaction.identify_low_satisfaction_categories(eng, min_reviews=1, threshold=3.6)
    assert list(low["category"]) == ["sports_leisure"]
    assert list(satisfaction.identify_low_satisfaction_sellers(eng, min_reviews=1, threshold=3.6)["seller_id"]) == ["s2"]
    assert satisfaction.identify_low_satisfaction_sellers(eng).empty                               # default min reviews = 10


def test_satisfaction_filters_apply(eng):
    k = satisfaction.calculate_satisfaction_kpis(eng, Filters(states=("RJ",)))
    assert k["total_reviews"] == 1 and k["avg_review_score"] == pytest.approx(4.0)


# ================================================================= geography
def test_state_to_region():
    assert geography.state_to_region("SP") == "Southeast" and geography.state_to_region("ba") == "Northeast"
    assert geography.state_to_region("RS") == "South" and geography.state_to_region("DF") == "Central-West"
    assert geography.state_to_region("AM") == "North" and geography.state_to_region("XX") == "Unknown"
    assert geography.state_to_region(None) == "Unknown"


def test_every_state_is_assigned_to_exactly_one_region():
    from config import settings
    assert len(settings.BRAZIL_REGIONS) == 27


def test_orders_sellers_freight_by_state(eng):
    assert by(geography.calculate_orders_by_state(eng), "state", "orders") == {"SP": 2, "RJ": 1, "MG": 1}
    sl = geography.calculate_sellers_by_state(eng)
    assert by(sl, "state", "sellers") == {"SP": 1, "RJ": 1}                 # seller location, not customer
    fr = geography.calculate_freight_by_state(eng).set_index("state")
    assert fr.loc["SP", "avg_freight_per_order"] == pytest.approx(11.5)      # (10 + 13) / 2
    assert fr.loc["SP", "avg_freight_per_item"] == pytest.approx(23 / 3)
    assert fr.loc["RJ", "freight_to_price"] == pytest.approx(0.1)
    assert fr.loc["MG", "avg_freight_per_order"] == pytest.approx(3.0)


def test_state_summary(eng):
    s = geography.calculate_state_summary(eng).set_index("state")
    assert s.loc["SP", "revenue"] == pytest.approx(220.0) and s.loc["SP", "orders"] == 2
    assert s.loc["SP", "customers"] == 1 and s.loc["SP", "region"] == "Southeast"
    assert s.loc["SP", "late_rate"] == pytest.approx(0.5) and s.loc["SP", "avg_review_score"] == pytest.approx(4.0)
    assert np.isnan(s.loc["MG", "late_rate"])                               # MG order was not delivered
    assert s["revenue"].sum() == pytest.approx(450.0)
    assert geography.calculate_state_summary(eng, Filters(states=("AC",))).empty


def test_region_revenue_and_top_regions(eng):
    r = geography.calculate_revenue_by_region(eng)
    assert list(r["region"]) == ["Southeast"] and r["revenue_share_pct"].iloc[0] == pytest.approx(100.0)
    assert r["states"].iloc[0] == 3
    top = geography.identify_top_revenue_regions(eng)
    assert list(top["state"]) == ["SP", "RJ"]                               # 48.9% + 44.4%, MG not needed for 80%


def test_growth_regions_need_enough_history(eng):
    assert geography.identify_growth_regions(eng).empty                    # fixture has 3 months, needs 6


def test_customer_seller_distribution(eng):
    d = geography.calculate_customer_seller_distribution(eng).set_index("state")
    assert d.loc["SP", "customers"] == 1 and d.loc["SP", "sellers"] == 1 and d.loc["SP", "customers_per_seller"] == 1
    assert d.loc["MG", "sellers"] == 0 and np.isnan(d.loc["MG", "customers_per_seller"])
    assert d["customer_share_pct"].sum() == pytest.approx(100.0)


def test_geography_kpis(eng):
    k = geography.calculate_geography_kpis(eng)
    assert k["total_states"] == 3 and k["customer_cities"] == 3 and k["seller_cities"] == 2
    assert k["top_revenue_state"] == "SP" and k["top_revenue_state_share_pct"] == pytest.approx(100 * 220 / 450)
    assert k["top_customer_state"] == "MG" and k["top_customer_state_share_pct"] == pytest.approx(100 / 3)   # 3-way tie -> alphabetical
    empty = geography.calculate_geography_kpis(eng, Filters(states=("AC",)))
    assert empty["top_revenue_state"] is None and empty["total_states"] == 0


# =================================================================== system
def test_database_status(eng):
    s = system.get_database_status(eng)
    assert s["connected"] and s["database"] == "marketpulse_test" and "PostgreSQL" in s["version"]
    assert len(s["tables"]) == 9 and by(s["tables"], "table", "rows")["fact_orders"] == 6


def test_database_status_when_unreachable():
    from config.database import get_engine
    from config.settings import DatabaseSettings
    s = system.get_database_status(get_engine(DatabaseSettings(host="localhost", port=1, name="x", user="x", password="x")))
    assert s["connected"] is False and s["error"] and s["tables"].empty


def test_warehouse_is_loaded(eng):
    assert system.warehouse_is_loaded(eng)


def test_processing_status_and_quality_report(eng):
    p = system.get_data_processing_status(eng)
    assert p["run"]["status"] == "success" and p["run"]["finished_at"] is not None
    assert by(p["loads"], "table_name", "rows_loaded")["fact_orders"] == 6
    assert not p["transformations"].empty
    q = system.load_quality_report(eng)
    assert q["overall_status"] in {"PASS", "WARN"} and q["summary"]["FAIL"] == 0 and q["checks"]
    assert "2016-2018" in q["notice"]


def test_describe_columns_counts_missing(eng):
    c = system.describe_columns(eng, "fact_orders").set_index("column")
    assert c.loc["order_id", "missing"] == 0 and c.loc["order_id", "rows"] == 6
    assert c.loc["payment_value", "missing"] == 1 and c.loc["payment_value", "missing_pct"] == pytest.approx(100 / 6)
    assert bool(c.loc["payment_value", "nullable"]) is True
    with pytest.raises(ValueError):
        system.describe_columns(eng, "fact_orders; DROP TABLE fact_orders")


def test_data_period(eng):
    p = system.get_data_period(eng)
    assert str(p["first_day"]) == "2017-01-10" and str(p["last_day"]) == "2017-03-12" and p["orders"] == 6


def test_customer_search_and_orders(eng):
    r = system.search_customer(eng, "U1")
    assert list(r["customer_unique_id"]) == ["u1"] and r["orders"].iloc[0] == 2 and r["revenue"].iloc[0] == pytest.approx(220.0)
    never = system.search_customer(eng, "u4").iloc[0]                       # only a canceled order
    assert never["orders"] == 0 and never["revenue"] == 0
    assert system.search_customer(eng, "   ").empty
    assert system.search_customer(eng, "'; DROP TABLE dim_customers; --").empty
    o = system.get_customer_orders(eng, "u1")
    assert list(o["order_id"]) == ["o1", "o2"] and list(o["review_score"]) == [5, 3]
    assert system.get_customer_orders(eng, "nobody").empty


def test_category_search_matches_english_and_portuguese(eng):
    assert list(system.search_product_category(eng, "bed")["category"]) == ["bed_bath_table"]
    assert list(system.search_product_category(eng, "cama")["category"]) == ["bed_bath_table"]    # Portuguese name
    assert system.search_product_category(eng, "zzz").empty


# ================================================= revenue recommendations
def test_revenue_recommendations_are_derived_from_findings(eng):
    recs = revenue.generate_revenue_recommendations(revenue.identify_revenue_opportunities(eng))
    titles = " | ".join(r.title for r in recs)
    assert "concentrated in sports_leisure (60.0%)" in titles
    assert "2 categories generate 80%" in titles and "2 states generate 80%" in titles
    assert "Top 2 sellers hold 100.0%" in titles
    assert not any("falling revenue" in r.title for r in recs)                 # no declining categories in fixture
    assert all(r.rule and r.evidence for r in recs)


def test_revenue_recommendations_empty_input():
    assert revenue.generate_revenue_recommendations({}) == []


# ================================================================== exports
def test_csv_export_roundtrip_with_accents():
    df = pd.DataFrame({"city": ["são paulo", "brasília"], "revenue": [1.5, 2.0]})
    raw = csv_exporter.dataframe_to_csv_bytes(df)
    assert raw.startswith(b"\xef\xbb\xbf")                                    # BOM so Excel reads UTF-8
    back = pd.read_csv(BytesIO(raw), encoding="utf-8-sig")
    pd.testing.assert_frame_equal(back, df)


def test_csv_export_of_empty_frame_keeps_header():
    raw = csv_exporter.dataframe_to_csv_bytes(pd.DataFrame(columns=["a", "b"]))
    assert raw.decode("utf-8-sig").strip() == "a,b"


def test_export_filtered_results_sanitises_name():
    name, data, mime = csv_exporter.export_filtered_results(pd.DataFrame({"a": [1]}), "Revenue by state / 2017!")
    assert name == "Revenue_by_state___2017.csv" and mime == "text/csv" and data


def test_excel_export_roundtrip_and_sheet_names():
    sheets = {"Revenue": pd.DataFrame({"x": [1, 2]}), "a/b:c" * 10: pd.DataFrame({"y": [3]}),
              "Revenue ": pd.DataFrame({"z": [4]})}
    book = pd.read_excel(BytesIO(excel_generator.dataframes_to_excel_bytes(sheets)), sheet_name=None)
    assert len(book) == 3 and all(len(n) <= 31 for n in book) and "Revenue" in book
    assert list(book["Revenue"]["x"]) == [1, 2]


def test_excel_export_requires_data_and_handles_timezones():
    with pytest.raises(ValueError):
        excel_generator.dataframes_to_excel_bytes({})
    tz = pd.DataFrame({"t": pd.to_datetime(["2017-01-01 10:00"]).tz_localize("UTC")})
    assert excel_generator.dataframes_to_excel_bytes({"tz": tz})
