"""Milestone 5 analytics.

The data frames built in this file are SYNTHETIC (seeded generators) and exist only to test
that the methods behave correctly where the right answer is known: a planted signal must be
found, and pure noise must NOT be reported as useful. Nothing here is Olist data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics import cohorts as co
from analytics import delivery_model as dm
from analytics import forecasting as fc
from analytics import segmentation as sg
from analytics import stats_tests as stt
from analytics import text_analysis as ta
from analytics.base import Filters


# ------------------------------------------------------------------ segmentation
def _purchases():
    # 10 one-time customers (A..J: revenue 10..100, purchased Jan 1.. Jan 10) + repeat R1 (3 orders, last Jan 10) and R2 (2 orders, old)
    rows = [(f"c{i}", pd.Timestamp("2017-01-01") + pd.Timedelta(days=i), 10.0 * (i + 1)) for i in range(10)]
    rows += [("R1", pd.Timestamp("2017-01-03"), 50.0), ("R1", pd.Timestamp("2017-01-06"), 50.0), ("R1", pd.Timestamp("2017-01-10"), 50.0)]
    rows += [("R2", pd.Timestamp("2017-01-01"), 20.0), ("R2", pd.Timestamp("2017-01-02"), 20.0)]
    return pd.DataFrame(rows, columns=["customer_unique_id", "purchase_ts", "revenue"])


def test_rfm_reference_date_is_the_day_after_the_last_purchase_not_today():
    r = sg.build_rfm_table(_purchases()).set_index("customer_unique_id")
    assert r.loc["c9", "recency_days"] == 1 and r.loc["c9", "recency_days"] < r.loc["c0", "recency_days"]
    assert r.loc["c0", "recency_days"] == 10


def test_rfm_values_and_segments_follow_the_published_rules():
    r = sg.build_rfm_table(_purchases()).set_index("customer_unique_id")
    assert (r.loc["R1", "frequency"], r.loc["R1", "monetary"]) == (3, 150.0) and r.loc["R1", "f_score"] == 3
    assert r.loc["R1", "segment"] == "Active repeat"                    # 2+ orders and bought on the last day
    assert r.loc["R2", "segment"] == "Lapsed repeat"                    # 2+ orders, old
    assert r.loc["c9", "segment"] == "High-value recent"                # 1 order, newest, top spender
    assert r.loc["c0", "segment"] == "Inactive one-time"                # oldest, smallest
    one = r[r["frequency"] == 1]
    assert not one["segment"].isin(["Active repeat", "Lapsed repeat"]).any()
    assert set(r["segment"]) <= set(sg.SEGMENT_ORDER)


def test_segment_summary_partitions_customers_and_revenue():
    rfm = sg.build_rfm_table(_purchases())
    s = sg.summarize_segments(rfm)
    assert s["customers"].sum() == len(rfm) and s["revenue"].sum() == pytest.approx(rfm["monetary"].sum())
    assert s["customer_share_pct"].sum() == pytest.approx(100) and list(s["segment"]) == sg.SEGMENT_ORDER


def test_rfm_empty_input_is_handled():
    assert sg.build_rfm_table(pd.DataFrame(columns=["customer_unique_id", "purchase_ts", "revenue"])).empty
    assert sg.summarize_segments(sg.build_rfm_table(pd.DataFrame(columns=["customer_unique_id", "purchase_ts", "revenue"]))).empty


def test_kmeans_is_deterministic_and_finds_planted_groups():
    rng = np.random.default_rng(1)
    a = pd.DataFrame({"recency_days": rng.integers(1, 30, 150), "frequency": 1, "monetary": rng.normal(40, 5, 150).clip(5)})
    b = pd.DataFrame({"recency_days": rng.integers(300, 400, 150), "frequency": 3, "monetary": rng.normal(400, 30, 150).clip(5)})
    rfm = pd.concat([a, b], ignore_index=True).assign(customer_unique_id=lambda d: [f"u{i}" for i in range(len(d))])
    r1, r2 = sg.cluster_customers(rfm), sg.cluster_customers(rfm)
    assert r1["available"] and r1["k"] == 2 and r1["silhouette"] > 0.5
    assert (r1["table"]["cluster"].to_numpy() == r2["table"]["cluster"].to_numpy()).all()
    assert r1["profile"]["customers"].sum() == 300
    assert sorted(r1["profile"]["customers"]) == [150, 150]


def test_kmeans_declines_when_there_is_too_little_data():
    rfm = sg.build_rfm_table(_purchases())
    assert sg.cluster_customers(rfm)["available"] is False


# ------------------------------------------------------------------------ cohorts
def _cohort_purchases():
    d = lambda s: pd.Timestamp(s)
    rows = [("c1", d("2017-01-05")), ("c2", d("2017-01-06")), ("c3", d("2017-01-07")), ("c4", d("2017-01-08")),
            ("c1", d("2017-02-10")), ("c2", d("2017-02-11")), ("c1", d("2017-03-01")),
            ("c5", d("2017-02-02")), ("c6", d("2017-02-03")), ("c5", d("2017-03-04"))]
    return pd.DataFrame(rows, columns=["customer_unique_id", "purchase_ts"]).assign(revenue=1.0)


def test_cohort_retention_matches_hand_count():
    t = co.build_cohort_table(_cohort_purchases(), min_size=2)
    jan = t[t["cohort"] == "2017-01"].set_index("months_since")
    assert jan.loc[0, "retention"] == 1.0 and jan.loc[1, "retention"] == 0.5 and jan.loc[2, "retention"] == 0.25
    assert t[(t["cohort"] == "2017-02") & (t["months_since"] == 1)]["retention"].iloc[0] == 0.5
    # month 1 pooled over cohorts that can reach it: (2 + 1) kept / (4 + 2) = 50%
    s = co.summarize_retention(t, 1)
    assert s["retention"] == pytest.approx(0.5) and s["cohorts_used"] == 2


def test_small_cohorts_are_not_reported_as_percentages():
    t = co.build_cohort_table(_cohort_purchases(), min_size=5)
    assert t["retention"].isna().all() and t["is_small"].all()
    assert co.summarize_retention(t, 1)["retention"] is None


def test_second_order_in_the_same_month_is_not_retention():
    p = pd.DataFrame({"customer_unique_id": ["a", "a"], "purchase_ts": pd.to_datetime(["2017-01-02", "2017-01-20"]), "revenue": 1.0})
    t = co.build_cohort_table(p, min_size=1)
    assert t["months_since"].tolist() == [0] and t["retention"].tolist() == [1.0]


def test_cohort_matrix_shape():
    m = co.cohort_matrix(co.build_cohort_table(_cohort_purchases(), min_size=2))
    assert m.loc["2017-01", 1] == 50.0 and list(m.index) == ["2017-01", "2017-02"]


# ---------------------------------------------------------------------- forecasting
def _months(n):
    return [str(p) for p in pd.period_range("2017-01", periods=n, freq="M")]


def test_forecast_needs_enough_months():
    r = fc.forecast_series(pd.Series(np.arange(5.0), index=_months(5)))
    assert not r["available"] and "12" in r["reason"]


def test_forecast_beats_naive_on_a_trend_and_reports_it():
    rng = np.random.default_rng(0)
    y = pd.Series(1000 + 80 * np.arange(20) + rng.normal(0, 30, 20), index=_months(20))
    r = fc.forecast_series(y)
    assert r["available"] and r["metrics"]["beats_naive"] and r["metrics"]["mae_model"] < r["metrics"]["mae_naive"]
    f = r["forecast"]
    assert f["month"].tolist() == ["2018-09", "2018-10", "2018-11"]
    assert (f["lower"] <= f["forecast"]).all() and (f["forecast"] <= f["upper"]).all() and (f["lower"] >= 0).all()
    assert f["forecast"].iloc[0] > y.iloc[-5]                               # follows the upward trend
    assert (f["upper"] - f["lower"]).is_monotonic_increasing                # uncertainty widens with the horizon


def test_beats_naive_flag_is_consistent_with_the_backtest_errors():
    rng = np.random.default_rng(5)
    y = pd.Series(1000 + rng.normal(0, 200, 18), index=_months(18))
    m = fc.forecast_series(y)["metrics"]
    assert m["beats_naive"] == (m["mae_model"] < m["mae_naive"]) and m["backtest_months"] == 6


def test_backtest_never_uses_the_month_it_predicts():
    y = pd.Series(np.linspace(100, 300, 16), index=_months(16))
    bt = fc.forecast_series(y)["backtest"]
    assert bt["month"].tolist() == _months(16)[-6:] and bt["actual"].tolist() == pytest.approx(y.iloc[-6:].tolist())


# ------------------------------------------------------------------ delivery model
def _orders(n=3000, signal=True, seed=0):
    rng = np.random.default_rng(seed)
    dist = rng.uniform(5, 2500, n)
    est = rng.integers(8, 40, n).astype(float)
    logit = -3.2 + 0.0012 * dist - 0.05 * (est - 20) if signal else np.full(n, -2.5)
    late = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return dm.prepare_features(pd.DataFrame({
        "order_id": [f"o{i}" for i in range(n)], "purchase_ts": pd.date_range("2017-01-01", periods=n, freq="h"),
        "customer_state": rng.choice(["SP", "RJ", "BA"], n), "seller_state": rng.choice(["SP", "MG"], n), "category": rng.choice(["a", "b", "c"], n),
        "item_count": 1, "seller_count": 1, "items_value": rng.uniform(20, 300, n), "freight_value": rng.uniform(5, 40, n),
        "estimated_delivery_days": est, "total_weight_g": rng.uniform(100, 5000, n), "max_volume_cm3": rng.uniform(100, 9000, n),
        "purchase_month": rng.integers(1, 13, n), "purchase_weekday": rng.integers(1, 8, n),
        "c_lat": -23.5, "c_lng": -46.6, "s_lat": -23.5 + dist / 111.0, "s_lng": -46.6, "is_late": late}))


def test_delivery_model_finds_a_planted_signal_with_a_time_split():
    r = dm.train_delivery_risk_model(_orders(), min_orders=500, min_late=30)
    assert r["available"] and r["usable"]
    assert r["metrics"]["Gradient boosting"]["roc_auc"] > 0.65
    assert r["metrics"]["Baseline (overall late rate)"]["roc_auc"] == 0.5
    assert r["period"]["train_to"] <= r["period"]["test_from"]             # test set is strictly later
    assert r["n_train"] + r["n_test"] == 3000 and r["n_test"] == 750
    assert r["importance"].iloc[0]["feature"] in ("distance_km", "estimated_delivery_days")
    d = r["deciles"]
    assert d["actual_late_rate"].iloc[-1] > d["actual_late_rate"].iloc[0]  # riskiest decile really is later


def test_delivery_model_does_not_claim_skill_on_pure_noise():
    r = dm.train_delivery_risk_model(_orders(signal=False, seed=3), min_orders=500, min_late=30)
    assert r["available"] and not r["usable"]
    assert r["metrics"]["Gradient boosting"]["roc_auc"] < 0.6


def test_predicted_risk_rises_with_distance_when_distance_matters():
    r = dm.train_delivery_risk_model(_orders(), min_orders=500, min_late=30)
    base = dict(customer_state="SP", seller_state="SP", category="a", item_count=1, seller_count=1, items_value=100, freight_value=20,
                estimated_delivery_days=20, total_weight_g=1000, max_volume_cm3=2000, purchase_month=6, purchase_weekday=3, same_state=1.0, freight_ratio=0.2)
    near, far = dm.predict_risk(r["model"], {**base, "distance_km": 20}), dm.predict_risk(r["model"], {**base, "distance_km": 2400})
    assert 0 <= near <= 1 and 0 <= far <= 1 and far > near


def test_delivery_model_declines_small_samples():
    r = dm.train_delivery_risk_model(_orders(100), min_orders=500, min_late=30)
    assert not r["available"] and "500" in r["reason"]


def test_no_outcome_leaking_features():
    banned = {"delivery_days", "delivery_delay_days", "customer_delivery_ts", "carrier_delivery_ts", "approved_ts", "is_late", "review_score"}
    assert not banned & set(dm.FEATURES)


# ------------------------------------------------------------------ statistical tests
def _facts(n=2000, effect=True, seed=0):
    rng = np.random.default_rng(seed)
    late = (rng.random(n) < 0.2).astype(int)
    score = np.where(late == 1, rng.choice([1, 2, 3, 4, 5], n, p=[.35, .25, .2, .12, .08]), rng.choice([1, 2, 3, 4, 5], n, p=[.05, .05, .1, .3, .5])) \
        if effect else rng.choice([1, 2, 3, 4, 5], n, p=[.1, .1, .2, .3, .3])
    freight = rng.uniform(5, 60, n)
    return pd.DataFrame({"review_score": score, "is_late": late, "freight_value": freight,
                         "delivery_days": 5 + 0.3 * freight + rng.normal(0, 2, n) if effect else rng.normal(12, 4, n),
                         "primary_payment_type": rng.choice(["credit_card", "boleto", "voucher"], n),
                         "customer_state": rng.choice(["SP", "RJ", "BA"], n)})


def test_review_effect_is_detected_and_large():
    r = stt.late_vs_review_score(_facts())
    assert r["available"] and r["p_value"] < 1e-6 and r["effect_size"] > 0.3 and r["magnitude"] in ("medium", "large")
    assert r["late_mean"] < r["on_time_mean"]


def test_no_effect_is_reported_as_negligible_even_with_many_orders():
    d = _facts(effect=False, seed=2)
    assert stt.late_vs_review_score(d)["magnitude"] == "negligible"
    assert stt.payment_vs_late(d)["magnitude"] == "negligible"
    assert stt.state_vs_review_score(d)["magnitude"] == "negligible"
    assert stt.freight_vs_delivery_time(d)["magnitude"] == "negligible"


def test_payment_vs_late_detects_a_planted_association():
    rng = np.random.default_rng(4)
    pay = rng.choice(["credit_card", "boleto"], 4000)
    late = np.where(pay == "boleto", rng.random(4000) < 0.25, rng.random(4000) < 0.05).astype(int)
    r = stt.payment_vs_late(pd.DataFrame({"primary_payment_type": pay, "is_late": late}))
    assert r["p_value"] < 1e-6 and r["effect_size"] > 0.1
    rates = r["late_rate_by_payment"].set_index("primary_payment_type")["late_rate"]
    assert rates["boleto"] > rates["credit_card"]


def test_freight_vs_delivery_time_positive_association():
    assert stt.freight_vs_delivery_time(_facts())["effect_size"] > 0.3


def test_confidence_intervals_are_valid():
    ci = stt.confidence_intervals(_facts()).set_index("metric")
    r = ci.loc["Late-delivery rate"]
    assert 0 <= r["lower"] <= r["estimate"] <= r["upper"] <= 1
    s = ci.loc["Average review score"]
    assert 1 <= s["lower"] <= s["estimate"] <= s["upper"] <= 5


def test_tests_decline_tiny_samples_instead_of_guessing():
    tiny = _facts(3)
    assert all(not r["available"] and r["reason"] for r in stt.run_all_tests(tiny))


# ---------------------------------------------------------------------- text terms
def _comments():
    neg = ["Não chegou, atrasou muito", "produto atrasou e não entregaram", "demorou demais, péssimo atendimento"] * 12
    pos = ["Ótimo produto, chegou rápido", "Recomendo, ótima qualidade", "Chegou antes do prazo, ótimo"] * 12
    return pd.DataFrame({"review_score": [1] * len(neg) + [5] * len(pos), "comment": neg + pos})


def test_terms_follow_the_review_score_and_ignore_accents_and_stopwords():
    r = ta.term_association(_comments(), min_count=5)
    assert r["available"] and r["n_negative"] == 36 and r["n_positive"] == 36
    neg, pos = set(r["negative_terms"]["term"].head(5)), set(r["positive_terms"]["term"].head(5))
    assert {"atrasou", "demorou"} & neg and {"otimo", "otima"} & pos
    assert not {"nao", "muito", "para"} & (neg | pos)                       # stopwords removed
    assert ta.normalize("Não") == "nao"


def test_term_analysis_declines_without_enough_comments():
    r = ta.term_association(_comments().head(10), min_count=1)
    assert not r["available"] and "20" in r["reason"]


# ------------------------------------------------------------ against the database
def test_rfm_from_database_matches_fixture(warehouse):
    r = sg.calculate_rfm(warehouse, None).set_index("monetary")
    assert r.loc[220.0, "frequency"] == 2 and r.loc[220.0, "segment"] == "Active repeat"   # u1: o1 + o2 (100 + 120)
    assert len(r) == 3
    assert sg.calculate_rfm(warehouse, Filters(states=("RJ",))).shape[0] == 1


def test_database_functions_decline_gracefully_on_tiny_data(warehouse):
    assert not fc.forecast_revenue(warehouse, None)["available"]
    assert not dm.train_delivery_risk_model(dm.load_delivery_dataset(warehouse, None))["available"]
    assert all(not t["available"] for t in stt.run_all_tests(stt.load_order_facts(warehouse, None)))
    assert not ta.term_association(ta.load_comments(warehouse, None))["available"]
    cov = ta.comment_coverage(warehouse, None)
    assert cov["reviews"] == 3 and cov["with_comment_share"] == pytest.approx(1 / 3)
    assert co.calculate_cohort_retention(warehouse, None)["is_small"].all()


def test_delivery_dataset_uses_purchase_time_columns_only(warehouse):
    d = dm.load_delivery_dataset(warehouse, None)
    assert len(d) == 3 and set(dm.FEATURES) <= set(d.columns)
    assert d["same_state"].isin([0.0, 1.0]).all() and d["distance_km"].notna().any()
