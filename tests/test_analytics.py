"""Analytics-layer tests on the synthetic fixture loaded into PostgreSQL.

Hand-computed fixture truth (see conftest.py):

revenue orders (4): o1 Jan-10 u1 SP credit 100 (p1/s1) | o2 Mar-01 u1 SP credit 120 (p1/s1 50 + p2/s2 70)
                    o3 Feb-05 u2 RJ boleto 200 (p2/s2)  | o4 Mar-10 u3 MG credit 30 (p3/s1, shipped)
freight: 10 / 13 / 20 / 3  (= 46)       order reviews (latest per order): o1=5  o2=3  o3=4  (o4 none)
delivery (valid): o1 -5d early, o2 +5d late, o3 0d (on time)   non-revenue: o5 canceled, o6 created
categories: bed_bath_table (p1) 150 | sports_leisure (p2) 270 | categoria_sem_traducao (p3) 30
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from analytics import customers, executive, logistics, products, revenue, sales, sellers
from analytics.base import Filters, flag_sparse_months, item_scope, order_scope, revenue_by

pytestmark = pytest.mark.usefixtures("warehouse")


@pytest.fixture()
def eng(warehouse):
    return warehouse


def by(df: pd.DataFrame, key: str, col: str) -> dict:
    return dict(zip(df[key], df[col]))


# ================================================================ executive KPIs
def test_executive_kpis_match_hand_computation(eng):
    k = executive.calculate_executive_kpis(eng)
    assert k["total_revenue"] == pytest.approx(450.0)
    assert k["total_orders"] == 4
    assert k["total_customers"] == 3
    assert k["avg_order_value"] == pytest.approx(112.5)
    assert k["avg_customer_revenue"] == pytest.approx(150.0)
    assert k["avg_review_score"] == pytest.approx(4.0)          # (5 + 3 + 4) / 3, one review per order
    assert k["repeat_purchase_rate"] == pytest.approx(1 / 3)
    assert k["on_time_delivery_rate"] == pytest.approx(2 / 3)
    assert k["late_delivery_rate"] == pytest.approx(1 / 3)


def test_individual_executive_functions(eng):
    assert executive.calculate_total_revenue(eng) == pytest.approx(450.0)
    assert executive.calculate_total_orders(eng) == 4
    assert executive.calculate_total_customers(eng) == 3
    assert executive.calculate_average_order_value(eng) == pytest.approx(112.5)
    assert executive.calculate_average_customer_revenue(eng) == pytest.approx(150.0)
    assert executive.calculate_average_review_score(eng) == pytest.approx(4.0)


def test_monthly_series_and_sparse_flag(eng):
    m = executive.get_monthly_revenue(eng)
    assert by(m, "year_month", "revenue") == {"2017-01": 100.0, "2017-02": 200.0, "2017-03": 150.0}
    o = executive.get_monthly_orders(eng)
    assert by(o, "year_month", "orders") == {"2017-01": 1, "2017-02": 1, "2017-03": 2}
    assert not m["is_sparse"].any()


def test_top_categories_state_payment_status(eng):
    cats = executive.get_top_categories(eng)
    assert list(cats["category"]) == ["sports_leisure", "bed_bath_table", "categoria_sem_traducao"]
    assert list(cats["revenue"]) == pytest.approx([270.0, 150.0, 30.0])
    assert cats["revenue_share_pct"].sum() == pytest.approx(100.0)
    assert by(executive.get_revenue_by_state(eng), "state", "revenue") == {"SP": 220.0, "RJ": 200.0, "MG": 30.0}
    pay = executive.get_payment_distribution(eng)
    assert by(pay, "payment_type", "revenue") == {"boleto": 200.0, "credit_card": 250.0}
    assert by(pay, "payment_type", "orders") == {"boleto": 1, "credit_card": 3}
    status = executive.get_order_status_distribution(eng)       # ALL orders, any status
    assert by(status, "order_status", "orders") == {"delivered": 3, "shipped": 1, "canceled": 1, "created": 1}
    assert status["share_pct"].sum() == pytest.approx(100.0)


def test_review_trend(eng):
    t = by(executive.get_review_trend(eng), "year_month", "avg_review_score")
    assert t == {"2017-01": 5.0, "2017-02": 4.0, "2017-03": 3.0}   # o4 has no review


def test_executive_insights_are_rule_based_and_traceable(eng):
    ins = executive.generate_executive_insights(eng)
    titles = " | ".join(i.title for i in ins)
    assert "Highest revenue month: 2017-02" in titles
    assert "Best-performing category: sports_leisure" in titles
    assert "Highest revenue state: SP" in titles
    assert "declined 25.0%" in titles                              # Feb 200 -> Mar 150
    assert any(i.kpi == "late_delivery_rate" and i.severity == "warning" for i in ins)   # 33% > 8%
    assert all(i.rule for i in ins)                                # every insight states its rule


def test_insights_for_empty_scope(eng):
    ins = executive.generate_executive_insights(eng, Filters(states=("AC",)))
    assert len(ins) == 1 and "No sales" in ins[0].title


# ====================================================================== filters
def test_state_filter(eng):
    f = Filters(states=("SP",))
    assert executive.calculate_total_revenue(eng, f) == pytest.approx(220.0)
    assert executive.calculate_total_orders(eng, f) == 2
    assert executive.calculate_total_customers(eng, f) == 1


def test_state_filter_is_case_insensitive(eng):
    assert executive.calculate_total_revenue(eng, Filters(states=("sp",))) == pytest.approx(220.0)


def test_date_filter_is_inclusive_on_both_ends(eng):
    assert executive.calculate_total_revenue(eng, Filters(date_from=date(2017, 2, 1))) == pytest.approx(350.0)
    assert executive.calculate_total_revenue(eng, Filters(date_to=date(2017, 2, 28))) == pytest.approx(300.0)
    assert executive.calculate_total_revenue(eng, Filters(date_from=date(2017, 1, 10), date_to=date(2017, 1, 10))) == pytest.approx(100.0)


def test_category_filter_restricts_items_not_whole_orders(eng):
    f = Filters(categories=("bed_bath_table",))
    assert executive.calculate_total_revenue(eng, f) == pytest.approx(150.0)   # o2's p2 item excluded
    assert executive.calculate_total_orders(eng, f) == 2


def test_seller_filter(eng):
    f = Filters(sellers=("s2",))
    assert executive.calculate_total_revenue(eng, f) == pytest.approx(270.0)
    assert executive.calculate_total_orders(eng, f) == 2


def test_category_and_seller_filter_must_match_the_same_item(eng):
    assert executive.calculate_total_revenue(eng, Filters(categories=("bed_bath_table",), sellers=("s2",))) == 0
    assert executive.calculate_total_revenue(eng, Filters(categories=("sports_leisure",), sellers=("s2",))) == pytest.approx(270.0)


def test_payment_and_status_filters(eng):
    assert executive.calculate_total_revenue(eng, Filters(payment_types=("boleto",))) == pytest.approx(200.0)
    # canceled orders are never revenue: filtering on them yields 0 rather than redefining revenue
    assert executive.calculate_total_revenue(eng, Filters(order_statuses=("canceled",))) == 0
    assert executive.calculate_total_revenue(eng, Filters(order_statuses=("shipped",))) == pytest.approx(30.0)


def test_filters_combine_with_and(eng):
    f = Filters(states=("SP",), date_from=date(2017, 3, 1))
    assert executive.calculate_total_revenue(eng, f) == pytest.approx(120.0)


def test_filter_describe_and_reset():
    assert Filters().describe() == "no filters"
    d = Filters(states=("SP", "RJ"), date_from=date(2017, 1, 1)).describe()
    assert "SP, RJ" in d and "2017-01-01" in d
    from analytics.base import reset_filters
    assert reset_filters().is_empty()


def test_filter_values_are_bound_parameters_not_sql(eng):
    nasty = Filters(states=("SP'; DROP TABLE fact_orders; --",))
    assert executive.calculate_total_revenue(eng, nasty) == 0
    assert executive.calculate_total_orders(eng) == 4          # table still intact


def test_scopes_never_multiply_orders(eng):
    """Joining items/products/sellers/dates must not change the distinct order count."""
    s = order_scope()
    from analytics.base import scalar
    assert scalar(eng, f"SELECT COUNT(DISTINCT o.order_id) FROM {item_scope().from_sql} WHERE o.is_revenue_order") == 4
    assert scalar(eng, f"SELECT COUNT(*) FROM {s.from_sql}") == 6           # every order exactly once
    assert scalar(eng, f"SELECT COUNT(*) FROM {item_scope().from_sql}") == 6  # every item exactly once


def test_top_n_shares_are_relative_to_total_not_to_the_returned_rows(eng):
    """Regression: limit=1 must still report sports_leisure as 60% of ALL revenue, not 100%."""
    top = executive.get_top_categories(eng, top_n=1)
    assert len(top) == 1 and top["revenue_share_pct"].iloc[0] == pytest.approx(60.0)
    # SP revenue 220 = bed_bath_table 150 (o1 100 + o2 50) + sports_leisure 70 (o2)
    sp = revenue_by(eng, Filters(states=("SP",)), "category", limit=1)
    assert sp["category"].iloc[0] == "bed_bath_table"
    assert sp["revenue_share_pct"].iloc[0] == pytest.approx(100 * 150 / 220)


def test_revenue_by_unknown_dimension_raises(eng):
    with pytest.raises(ValueError, match="Unknown dimension"):
        revenue_by(eng, None, "colour")


# ================================================================== revenue page
def test_revenue_growth_uses_latest_two_non_sparse_months(eng):
    g = revenue.calculate_revenue_growth(eng)
    assert g["available"] and g["latest_month"] == "2017-03" and g["previous_month"] == "2017-02"
    assert g["growth_pct"] == pytest.approx(-25.0)
    assert g["excluded_sparse_months"] == []


def test_revenue_growth_unavailable_with_single_month(eng):
    g = revenue.calculate_revenue_growth(eng, Filters(date_from=date(2017, 1, 1), date_to=date(2017, 1, 31)))
    assert g["available"] is False and g["growth_pct"] is None


def test_monthly_revenue_has_mom_growth(eng):
    m = revenue.calculate_monthly_revenue(eng).set_index("year_month")
    assert pd.isna(m.loc["2017-01", "mom_growth_pct"])
    assert m.loc["2017-02", "mom_growth_pct"] == pytest.approx(100.0)
    assert m.loc["2017-03", "mom_growth_pct"] == pytest.approx(-25.0)


def test_sparse_month_rule_suppresses_artificial_growth():
    m = pd.DataFrame({"year_month": ["a", "b", "c", "d"], "orders": [2, 400, 420, 3], "revenue": [1, 2, 3, 4]})
    flagged = flag_sparse_months(m)
    assert flagged["is_sparse"].tolist() == [True, False, False, True]


def test_revenue_by_dimensions_reconcile_to_total(eng):
    total = executive.calculate_total_revenue(eng)
    for fn in (revenue.calculate_revenue_by_category, revenue.calculate_revenue_by_seller,
               revenue.calculate_revenue_by_state, revenue.calculate_revenue_by_payment):
        assert fn(eng)["revenue"].sum() == pytest.approx(total)
    assert by(revenue.calculate_revenue_by_seller(eng), "seller_id", "revenue") == {"s1": 180.0, "s2": 270.0}


def test_category_contribution_is_pareto(eng):
    c = revenue.calculate_category_revenue_contribution(eng)
    assert list(c["revenue_share_pct"].round(2)) == [60.0, 33.33, 6.67]
    assert c["cumulative_share_pct"].iloc[-1] == pytest.approx(100.0)


def test_aov_trend(eng):
    t = by(revenue.calculate_average_order_value_trend(eng), "year_month", "avg_order_value")
    assert t == {"2017-01": 100.0, "2017-02": 200.0, "2017-03": 75.0}


def test_revenue_distribution(eng):
    d = revenue.calculate_revenue_distribution(eng)
    assert sorted(d["orders"]["order_value"]) == [30.0, 100.0, 120.0, 200.0]
    assert d["summary"]["median"] == pytest.approx(110.0) and d["summary"]["count"] == 4


def test_revenue_kpis_separate_freight_from_revenue(eng):
    k = revenue.calculate_revenue_kpis(eng)
    assert k["total_revenue"] == pytest.approx(450.0) and k["freight_charges"] == pytest.approx(46.0)
    assert k["revenue_per_customer"] == pytest.approx(150.0)
    assert k["top_category"] == "sports_leisure" and k["top_category_share_pct"] == pytest.approx(60.0)
    assert k["revenue_growth_basis"] == "2017-02 -> 2017-03"


def test_revenue_opportunities_structure(eng):
    o = revenue.identify_revenue_opportunities(eng)
    assert set(o) == {"high_revenue_categories", "low_performing_categories", "declining_categories",
                      "top_states", "seller_concentration"}
    # 80% of revenue: sports (60) alone is not enough, sports+bed (93.3) is
    assert list(o["high_revenue_categories"]["category"]) == ["sports_leisure", "bed_bath_table"]
    assert list(o["top_states"]["state"]) == ["SP", "RJ"]        # 48.9% + 44.4% -> 93.3% (SP alone < 80)
    assert o["declining_categories"].empty                       # needs >= 6 non-sparse months; fixture has 3
    assert o["seller_concentration"]["cumulative_share_pct"].iloc[-1] == pytest.approx(100.0)


# =================================================================== sales page
def test_sales_kpis(eng):
    k = sales.calculate_sales_kpis(eng)
    assert k["total_sales"] == pytest.approx(450.0) and k["total_orders"] == 4
    assert k["avg_order_value"] == pytest.approx(112.5)
    assert k["avg_items_per_order"] == pytest.approx(1.25)       # 5 items / 4 orders
    assert k["avg_freight_value"] == pytest.approx(11.5)         # 46 / 4
    assert k["days_in_range"] == 60                              # 2017-01-10 .. 2017-03-10 inclusive
    assert k["daily_avg_orders"] == pytest.approx(4 / 60)
    assert k["latest_monthly_growth_pct"] == pytest.approx(-25.0)


def test_daily_yearly_weekday(eng):
    d = sales.calculate_daily_sales(eng)
    assert len(d) == 4 and d["revenue"].sum() == pytest.approx(450.0)
    y = sales.calculate_yearly_sales(eng)
    assert list(y["calendar_year"]) == [2017] and y["revenue"].iloc[0] == pytest.approx(450.0)
    assert y["months_with_sales"].iloc[0] == 3
    w = sales.calculate_sales_by_weekday(eng)
    assert len(w) == 7                                           # all weekdays present, zeros filled
    assert by(w, "weekday_name", "revenue") == {"Monday": 0, "Tuesday": 100.0, "Wednesday": 120.0,
                                                "Thursday": 0, "Friday": 30.0, "Saturday": 0, "Sunday": 200.0}


def test_growth_by_period(eng):
    m = sales.calculate_sales_growth(eng, period="month").set_index("period")
    assert m.loc["2017-02", "revenue_growth_pct"] == pytest.approx(100.0)
    assert m.loc["2017-03", "orders_growth_pct"] == pytest.approx(100.0)     # 1 -> 2 orders
    q = sales.calculate_sales_growth(eng, period="quarter")
    assert list(q["period"]) == ["2017-Q1"] and q["months_in_period"].iloc[0] == 3
    assert pd.isna(q["revenue_growth_pct"].iloc[0])
    y = sales.calculate_sales_growth(eng, period="year")
    assert list(y["period"]) == ["2017"]
    with pytest.raises(ValueError):
        sales.calculate_sales_growth(eng, period="week")


def test_yoy_requires_the_same_month_in_two_years(eng):
    assert sales.calculate_yoy_by_month(eng).empty              # only 2017 in the fixture


def test_compare_period_performance(eng):
    c = sales.compare_period_performance(
        eng, None, (date(2017, 3, 1), date(2017, 3, 31)), (date(2017, 1, 1), date(2017, 1, 31))).set_index("metric")
    assert c.loc["revenue", "period_a"] == pytest.approx(150.0) and c.loc["revenue", "period_b"] == pytest.approx(100.0)
    assert c.loc["revenue", "change_pct"] == pytest.approx(50.0)
    assert c.loc["orders", "change"] == 1
    assert c.loc["avg_order_value", "period_a"] == pytest.approx(75.0)


def test_compare_period_keeps_other_filters(eng):
    c = sales.compare_period_performance(
        eng, Filters(states=("SP",)), (date(2017, 3, 1), date(2017, 3, 31)), (date(2017, 1, 1), date(2017, 1, 31))
    ).set_index("metric")
    assert c.loc["revenue", "period_a"] == pytest.approx(120.0)  # o4 (MG) excluded


def test_peak_periods_and_declines(eng):
    p = sales.identify_peak_sales_periods(eng, top_n=2)
    assert list(p["peak"]["year_month"]) == ["2017-02", "2017-03"]
    assert list(p["declines"]["year_month"]) == ["2017-03"]
    d = sales.identify_peak_sales_periods(eng, top_n=1, freq="day")
    assert d["peak"]["revenue"].iloc[0] == pytest.approx(200.0) and d["declines"].empty
    with pytest.raises(ValueError):
        sales.identify_peak_sales_periods(eng, freq="hour")


def test_seasonality_and_value_distribution(eng):
    s = sales.calculate_sales_seasonality(eng)
    assert len(s) == 3 and s["years_observed"].eq(1).all()
    assert sorted(sales.calculate_order_value_distribution(eng)["order_value"]) == [30.0, 100.0, 120.0, 200.0]
    assert sales.calculate_average_items_per_order(eng) == pytest.approx(1.25)
    assert sales.calculate_average_freight_value(eng) == pytest.approx(11.5)


# ================================================================ products page
def test_top_and_bottom_products(eng):
    top = products.get_top_selling_products(eng, top_n=3)
    assert list(top["product_id"]) == ["p2", "p1", "p3"]          # p1/p2 tie on 2 units -> higher revenue first
    assert list(top["units"]) == [2, 2, 1]
    assert top.set_index("product_id").loc["p1", "revenue"] == pytest.approx(150.0)
    bottom = products.get_bottom_selling_products(eng, top_n=1)
    assert list(bottom["product_id"]) == ["p3"]


def test_category_functions(eng):
    assert list(products.get_top_categories_by_revenue(eng, top_n=1)["category"]) == ["sports_leisure"]
    assert list(products.get_bottom_categories_by_revenue(eng, top_n=1)["category"]) == ["categoria_sem_traducao"]
    q = products.get_categories_by_quantity(eng)
    assert by(q, "category", "items") == {"sports_leisure": 2, "bed_bath_table": 2, "categoria_sem_traducao": 1}
    assert products.calculate_average_product_price(eng) == pytest.approx(90.0)     # 450 / 5 items
    r = products.calculate_category_review_score(eng).set_index("category")
    assert r.loc["bed_bath_table", "avg_review_score"] == pytest.approx(4.0)         # o1=5, o2=3
    assert r.loc["sports_leisure", "avg_review_score"] == pytest.approx(3.5)         # o2=3, o3=4
    assert pd.isna(r.loc["categoria_sem_traducao", "avg_review_score"])               # o4 unreviewed


def test_product_kpis(eng):
    k = products.calculate_product_kpis(eng)
    assert k["products_sold"] == 3 and k["total_units"] == 5 and k["categories"] == 3
    assert k["top_revenue_category"] == "sports_leisure"
    assert k["avg_product_review_score"] == pytest.approx(4.0)


def test_weight_and_dimension_analysis(eng):
    w = products.calculate_product_weight_distribution(eng).set_index("product_id")
    assert w["weight_g"].to_dict() == {"p1": 500.0, "p2": 1000.0, "p3": 250.0}
    dims = products.calculate_product_dimension_analysis(eng).set_index("product_id")
    assert dims.loc["p1", "volume_cm3"] == pytest.approx(20 * 10 * 15)
    s = products.calculate_product_attribute_summary(eng)
    assert s["products"] == 3 and s["weight_g"]["mean"] == pytest.approx(1750 / 3) and s["missing_weight"] == 0
    assert sorted(products.calculate_product_price_distribution(eng)["price"]) == [30.0, 50.0, 70.0, 100.0, 200.0]


def test_performance_matrix_quadrants(eng):
    m = products.build_product_performance_matrix(eng, min_orders=1).set_index("category")
    # judgeable categories = bed (150) and sports (270) -> median revenue 210; overall average review = 4.0
    assert m.loc["bed_bath_table", "quadrant"] == "Grow / promote"       # 150 < 210 but review 4.0 >= 4.0
    assert m.loc["sports_leisure", "quadrant"] == "Fix quality"          # 270 >= 210 but review 3.5 < 4.0
    assert m.loc["categoria_sem_traducao", "quadrant"] == "Insufficient data"   # no reviews
    # default min_orders (30) leaves everything "Insufficient data": small samples are not judged
    assert (products.build_product_performance_matrix(eng)["quadrant"] == "Insufficient data").all()


def test_underperforming_categories(eng):
    u = products.identify_underperforming_categories(eng, min_orders=1)
    assert list(u["category"]) == ["categoria_sem_traducao"]            # orders 1 < p25 (1.5); sports 3.5 is not < 3.5
    assert "low demand" in u["reasons"].iloc[0]


def test_high_freight_products_and_promotion_candidates(eng):
    assert products.get_products_with_high_freight(eng, ratio=0.3, min_units=1).empty        # all ~10%
    hi = products.get_products_with_high_freight(eng, ratio=0.05, min_units=1)
    assert set(hi["product_id"]) == {"p1", "p2", "p3"}
    assert products.get_products_with_high_freight(eng, ratio=0.05, min_units=2)["product_id"].tolist() \
        == sorted(["p1", "p2"], key=lambda p: -hi.set_index("product_id").loc[p, "freight_ratio"])
    promo = products.get_products_worth_promoting(eng, min_orders=1)
    assert list(promo["category"]) == ["bed_bath_table"]                 # well reviewed, below-median revenue


# =============================================================== customers page
def test_customer_counts_and_rates(eng):
    assert customers.calculate_total_customers(eng) == 3
    assert customers.calculate_repeat_purchase_rate(eng) == pytest.approx(1 / 3)
    assert customers.calculate_average_orders_per_customer(eng) == pytest.approx(4 / 3)
    k = customers.calculate_customer_kpis(eng)
    assert k["total_customers"] == 3 and k["new_customers"] == 3 and k["repeat_customers"] == 1
    assert k["avg_customer_revenue"] == pytest.approx(150.0)
    assert k["observed_lifetime_revenue_median"] == pytest.approx(200.0)


def test_customer_revenue_table(eng):
    c = customers.calculate_customer_revenue(eng).set_index("customer_unique_id")
    assert c.loc["u1", "orders"] == 2 and c.loc["u1", "revenue"] == pytest.approx(220.0)
    assert c.loc["u1", "avg_order_value"] == pytest.approx(110.0)
    assert c.loc["u1", "frequency_segment"] == "repeat" and c.loc["u2", "frequency_segment"] == "one_time"
    assert list(customers.calculate_customer_revenue(eng, limit=1)["customer_unique_id"]) == ["u1"]


def test_new_vs_repeat_uses_first_ever_purchase_not_filtered_window(eng):
    window = Filters(date_from=date(2017, 3, 1))
    new = customers.identify_new_customers(eng, window)
    assert list(new["customer_unique_id"]) == ["u3"]             # u1 bought in Jan, so is not new in March
    # ...and within the window u1 has a single order, so is not a repeat customer *in scope*
    assert customers.identify_repeat_customers(eng, window).empty


def test_monthly_acquisition_and_new_vs_returning(eng):
    acq = by(customers.calculate_monthly_customer_acquisition(eng), "year_month", "new_customers")
    assert acq == {"2017-01": 1, "2017-02": 1, "2017-03": 1}
    nr = customers.calculate_new_vs_returning(eng).set_index("year_month")
    assert nr.loc["2017-03", "new_customers"] == 1 and nr.loc["2017-03", "returning_customers"] == 1   # u3 new, u1 back
    assert nr.loc["2017-01", "returning_customers"] == 0


def test_frequency_single_purchase_and_value_segments(eng):
    f = customers.calculate_customer_frequency(eng)
    assert by(f, "orders", "customers") == {1: 2, 2: 1}
    s = customers.identify_single_purchase_customers(eng)
    assert s["customers"] == 2 and s["customer_share"] == pytest.approx(2 / 3)
    assert s["revenue_share"] == pytest.approx(230 / 450)
    seg = customers.calculate_revenue_by_customer_type(eng).set_index("frequency_segment")
    assert seg.loc["one_time", "revenue"] == pytest.approx(230.0) and seg.loc["repeat", "customers"] == 1
    assert seg["revenue_share_pct"].sum() == pytest.approx(100.0)


def test_high_value_customers_and_lifetime_summary(eng):
    top = customers.identify_high_value_customers(eng)
    assert list(top["customer_unique_id"]) == ["u1"]
    assert top["revenue_share_pct"].iloc[0] == pytest.approx(100 * 220 / 450)
    life = customers.calculate_customer_lifetime_revenue(eng)
    assert life["mean"] == pytest.approx(150.0) and life["max"] == pytest.approx(220.0)


def test_customers_by_state(eng):
    s = customers.calculate_customers_by_state(eng)
    assert by(s, "state", "customers") == {"SP": 1, "RJ": 1, "MG": 1}
    assert s["customer_share_pct"].sum() == pytest.approx(100.0)


def test_purchase_patterns_for_repeat_customers(eng):
    p = customers.identify_customer_purchase_patterns(eng)
    assert p["repeat_customers"] == 1
    assert p["repeat_order_share"] == pytest.approx(2 / 4)
    # u1: 2017-01-10 10:00 -> 2017-03-01 09:00 = 49 days 23 h
    assert p["avg_days_between_orders"] == pytest.approx(49.958, abs=0.01)
    assert p["avg_days_to_second_order"] == pytest.approx(49.958, abs=0.01)
    assert p["avg_order_value_repeat_customers"] == pytest.approx(110.0)
    assert p["avg_order_value_single_customers"] == pytest.approx(115.0)    # (200 + 30) / 2


def test_customer_functions_on_empty_scope(eng):
    f = Filters(states=("AC",))
    assert customers.calculate_total_customers(eng, f) == 0
    assert customers.calculate_repeat_purchase_rate(eng, f) is None
    assert customers.calculate_customer_revenue(eng, f).empty
    assert customers.identify_single_purchase_customers(eng, f)["customer_share"] is None
    assert customers.identify_customer_purchase_patterns(eng, f)["repeat_customers"] == 0
    assert customers.calculate_customer_kpis(eng, f)["avg_customer_revenue"] is None


# ================================================================ sellers page
def test_seller_table_and_kpis(eng):
    t = sellers.seller_table(eng).set_index("seller_id")
    assert set(t.index) == {"s1", "s2"}                          # s3 has no orders
    assert t.loc["s1", "orders"] == 3 and t.loc["s1", "revenue"] == pytest.approx(180.0)
    assert t.loc["s1", "items_sold"] == 3
    assert t.loc["s2", "orders"] == 2 and t.loc["s2", "revenue"] == pytest.approx(270.0)
    assert t.loc["s1", "avg_review_score"] == pytest.approx(4.0)     # o1=5, o2=3 (o4 unreviewed)
    assert t.loc["s2", "avg_review_score"] == pytest.approx(3.5)     # o2=3, o3=4
    assert t.loc["s1", "late_rate"] == pytest.approx(0.5)            # o1 on time, o2 late (o4 undelivered)
    assert sellers.calculate_total_sellers(eng) == 3
    k = sellers.calculate_seller_kpis(eng)
    assert k["sellers_with_orders"] == 2 and k["avg_orders_per_seller"] == pytest.approx(2.5)
    assert k["avg_seller_revenue"] == pytest.approx(225.0) and k["avg_seller_review_score"] == pytest.approx(3.75)
    assert k["seller_late_delivery_rate"] == pytest.approx(0.5)       # 2 late / 4 delivered seller-orders


def test_seller_revenue_reconciles_to_total(eng):
    assert sellers.calculate_seller_revenue(eng)["revenue"].sum() == pytest.approx(450.0)
    assert sellers.calculate_seller_revenue(eng)["revenue_share_pct"].sum() == pytest.approx(100.0)


def test_seller_rankings(eng):
    assert list(sellers.rank_sellers_by_revenue(eng)["seller_id"]) == ["s2", "s1"]
    assert list(sellers.rank_sellers_by_orders(eng)["seller_id"]) == ["s1", "s2"]
    assert sellers.rank_sellers_by_satisfaction(eng, min_reviews=1)["seller_id"].tolist() == ["s1", "s2"]
    assert sellers.rank_sellers_by_satisfaction(eng).empty           # default needs >= 10 reviews
    assert list(sellers.rank_sellers_by_revenue(eng, top_n=1)["rank"]) == [1]


def test_seller_metric_helpers(eng):
    assert by(sellers.calculate_seller_order_volume(eng), "seller_id", "orders") == {"s1": 3, "s2": 2}
    assert by(sellers.calculate_seller_average_rating(eng), "seller_id", "avg_review_score") == {"s1": 4.0, "s2": 3.5}
    assert by(sellers.calculate_seller_delivery_rate(eng), "seller_id", "on_time_rate") == {"s1": 0.5, "s2": 0.5}
    assert by(sellers.calculate_seller_late_delivery_rate(eng), "seller_id", "late_orders") == {"s1": 1, "s2": 1}
    st = sellers.calculate_seller_revenue_by_state(eng).set_index("state")
    assert st.loc["SP", "revenue"] == pytest.approx(180.0) and st.loc["RJ", "revenue"] == pytest.approx(270.0)


def test_scorecard_matches_hand_computed_scores(eng):
    sc = sellers.generate_seller_scorecard(eng, min_orders=1).set_index("seller_id")
    # percentile ranks among 2 sellers: revenue s1=.5 s2=1 | orders s1=1 s2=.5 | on-time tie=.75 | review s1=1 s2=.5
    assert sc.loc["s1", "score"] == pytest.approx(78.75)     # 100 x (.3x.5 + .2x1 + .25x.75 + .25x1)
    assert sc.loc["s2", "score"] == pytest.approx(71.25)     # 100 x (.3x1 + .2x.5 + .25x.75 + .25x.5)
    assert sc.loc["s1", "tier"] == "Excellent" and sc.loc["s2", "tier"] == "Good"
    assert sc.loc["s1", "score_rank"] == 1
    one = sellers.generate_seller_scorecard(eng, min_orders=1, seller_id="s2")
    assert len(one) == 1 and one["score_rank"].iloc[0] == 2
    assert sellers.generate_seller_scorecard(eng).empty      # default min 10 orders: nobody qualifies


def test_scorecard_methodology_is_transparent():
    m = sellers.scorecard_methodology()
    assert sum(m["weights"].values()) == pytest.approx(1.0)
    assert "percentile" in m["description"] and str(m["min_orders"]) in m["description"]


def test_underperforming_sellers_state_their_reasons(eng):
    u = sellers.identify_underperforming_sellers(eng, min_orders=1)
    assert set(u["seller_id"]) == {"s1", "s2"}                # late rate 50% > 15%
    assert all("late rate" in r for r in u["reasons"])
    assert sellers.identify_underperforming_sellers(eng).empty


def test_seller_search_is_parameterised(eng):
    assert list(sellers.search_sellers(eng, "S1")["seller_id"]) == ["s1"]
    assert list(sellers.search_sellers(eng, "campinas")["seller_id"]) == ["s1"]
    assert sellers.search_sellers(eng, "x'; DROP TABLE dim_sellers; --").empty
    assert sellers.calculate_total_sellers(eng) == 3


# =============================================================== logistics page
def test_logistics_kpis(eng):
    k = logistics.calculate_logistics_kpis(eng)
    assert k["delivered_orders"] == 3 and k["orders_with_valid_dates"] == 3
    assert k["on_time_deliveries"] == 2 and k["late_deliveries"] == 1
    assert k["late_delivery_rate"] == pytest.approx(1 / 3) and k["on_time_delivery_rate"] == pytest.approx(2 / 3)
    assert k["avg_delivery_days"] == pytest.approx(13.25, abs=0.02)     # (10.21 + 19.13 + 10.42) / 3
    assert k["avg_delay_days"] == pytest.approx(0.0)                    # (-5 + 5 + 0) / 3
    assert k["avg_delay_of_late_orders"] == pytest.approx(5.0)
    assert k["avg_freight_cost"] == pytest.approx(43 / 3)               # (10 + 13 + 20) / 3


def test_order_level_delivery_lists(eng):
    t = logistics.calculate_delivery_time(eng).set_index("order_id")
    assert t.loc["o1", "delivery_days"] == pytest.approx(10.21, abs=0.01)
    assert t.loc["o1", "estimated_delivery_days"] == pytest.approx(15.0)    # Jan-10 -> Jan-25
    d = logistics.calculate_delivery_delay(eng).set_index("order_id")
    assert d["delivery_delay_days"].to_dict() == {"o1": -5, "o2": 5, "o3": 0}
    late = logistics.identify_late_orders(eng)
    assert list(late["order_id"]) == ["o2"] and late["delivery_delay_days"].iloc[0] == 5
    assert late["review_score"].iloc[0] == 3                                 # latest review for o2
    assert by(logistics.calculate_delay_distribution(eng), "delay_days", "orders") == {-5: 1, 0: 1, 5: 1}


def test_delivery_trend_and_by_state(eng):
    tr = logistics.get_delivery_trend(eng).set_index("year_month")
    assert tr.loc["2017-03", "late_rate"] == pytest.approx(1.0) and tr.loc["2017-01", "late_rate"] == 0
    st = logistics.analyze_delivery_by_state(eng).set_index("state")
    assert st.loc["SP", "orders"] == 2 and st.loc["SP", "late_rate"] == pytest.approx(0.5)
    assert st.loc["RJ", "late_rate"] == 0 and "MG" not in st.index     # o4 undelivered
    assert st.loc["SP", "avg_review_score"] == pytest.approx(4.0)       # o1=5, o2=3


def test_freight_by_category_and_relationship(eng):
    fc = logistics.calculate_freight_by_category(eng).set_index("category")
    assert fc.loc["bed_bath_table", "avg_freight_per_item"] == pytest.approx(7.5)     # items 10 and 5
    assert fc.loc["sports_leisure", "avg_freight_per_item"] == pytest.approx(14.0)    # items 8 and 20
    assert "categoria_sem_traducao" not in fc.index                                    # o4 not delivered
    rel = logistics.calculate_freight_delivery_relationship(eng)
    assert rel["n"] == 3 and -1 <= rel["spearman"] <= 1 and -1 <= rel["pearson"] <= 1
    tiny = logistics.calculate_freight_delivery_relationship(eng, Filters(states=("RJ",)))
    assert tiny["n"] == 1 and tiny["spearman"] is None                 # too few points: not computed


def test_bottlenecks_and_ranking(eng):
    b = logistics.identify_logistics_bottlenecks(eng, factor=1.4, min_state_orders=1, min_seller_orders=1)
    assert ("state", "SP") in set(zip(b["level"], b["name"]))          # 50% >= 1.4 x 33%
    assert ("state", "RJ") not in set(zip(b["level"], b["name"]))
    assert {"s1", "s2"} <= set(b.loc[b["level"] == "seller", "name"])
    assert logistics.identify_logistics_bottlenecks(eng).empty         # default minimum volumes not met
    r = logistics.rank_delivery_performance(eng, by="state", min_orders=1)
    assert list(r["state"]) == ["RJ", "SP"] and list(r["rank"]) == [1, 2]
    assert not logistics.rank_delivery_performance(eng, by="seller", min_orders=1).empty
    with pytest.raises(ValueError):
        logistics.rank_delivery_performance(eng, by="city")


def test_delivery_by_seller(eng):
    d = logistics.analyze_delivery_by_seller(eng, min_orders=1).set_index("seller_id")
    assert d.loc["s1", "delivered_orders"] == 2 and d.loc["s2", "late_orders"] == 1


def test_logistics_on_empty_scope(eng):
    f = Filters(states=("AC",))
    k = logistics.calculate_logistics_kpis(eng, f)
    assert k["late_delivery_rate"] is None and k["on_time_delivery_rate"] is None
    assert logistics.identify_logistics_bottlenecks(eng, f).empty


# ===================================================== reference SQL files run
@pytest.mark.parametrize("name", ["sales", "customer", "product", "seller", "logistics", "cohort"])
def test_reference_sql_files_execute(eng, name):
    from sqlalchemy import text
    from config import settings
    path = settings.PROJECT_ROOT / "sql" / f"{name}_analysis.sql"
    code = "\n".join(l for l in path.read_text().splitlines() if not l.strip().startswith("--"))
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert statements
    with eng.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt)).fetchall()


def test_reference_sql_matches_python_results(eng):
    from sqlalchemy import text
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT 1.0 * COUNT(*) FILTER (WHERE orders > 1) / COUNT(*) FROM ("
            "SELECT customer_unique_id, COUNT(*) AS orders FROM fact_orders WHERE is_revenue_order "
            "GROUP BY customer_unique_id) c")).scalar()
    assert float(rows) == pytest.approx(customers.calculate_repeat_purchase_rate(eng))
