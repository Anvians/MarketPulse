"""Milestone 4 analytics on the synthetic fixture (see conftest.py for the data).

Default thresholds are sized for the real data, so on this 4-order fixture they
correctly produce nothing; the hand-checked cases lower the thresholds explicitly.
"""
from __future__ import annotations

import pytest

from analytics import growth as gr
from analytics import opportunities as op
from analytics.base import Filters

LOW = dict(min_category_orders=1, min_seller_orders=1, min_state_orders=1)


def test_default_thresholds_ignore_tiny_samples(warehouse):
    o = op.find_business_opportunities(warehouse, None)
    assert list(o.columns) == op.COLUMNS
    # seller / state / review rules need >= 10 orders etc., so none fire on 4 orders;
    # only the relative "bottom quartile of category demand" rule can.
    assert set(o["area"]) <= {"Products"}
    assert op.find_business_opportunities(warehouse, Filters(order_statuses=("canceled",))).empty


def test_opportunities_are_ranked_by_observed_revenue_with_stated_rules(warehouse):
    o = op.find_business_opportunities(warehouse, None, **LOW)
    assert o["priority"].tolist() == list(range(1, len(o) + 1))
    rev = o["observed_revenue"].dropna().tolist()
    assert rev == sorted(rev, reverse=True)
    assert o["rule"].str.len().gt(10).all() and o["evidence"].str.len().gt(5).all()
    assert o.iloc[0]["observed_revenue"] == pytest.approx(270.0)       # seller s2: 70 + 200
    assert {"Logistics", "Sellers", "Products"} <= set(o["area"])


def test_seller_s2_is_flagged_for_its_late_order(warehouse):
    o = op.find_business_opportunities(warehouse, None, **LOW)
    s2 = o[(o["area"] == "Sellers") & (o["subject"] == "s2")]
    assert len(s2) == 1 and "late rate 50%" in s2.iloc[0]["finding"]


def test_opportunities_respect_global_filters(warehouse):
    o = op.find_business_opportunities(warehouse, Filters(states=("RJ",)), **LOW)
    assert not (o["subject"] == "state: SP").any()


def test_summarize_opportunities_counts_per_area(warehouse):
    o = op.find_business_opportunities(warehouse, None, **LOW)
    s = op.summarize_opportunities(o)
    assert s["findings"].sum() == len(o)
    assert op.summarize_opportunities(o.iloc[0:0]).empty


def test_underserved_states_flags_state_without_seller(warehouse):
    d = gr.identify_underserved_states(warehouse, None, min_customers=1)
    mg = d[d["state"] == "MG"].iloc[0]
    assert mg["sellers"] == 0 and mg["reason"] == "no seller located in the state"
    assert gr.identify_underserved_states(warehouse, None).empty       # min 100 customers


def test_cross_sell_pair_counts_and_lift(warehouse):
    p = gr.identify_cross_sell_pairs(warehouse, None, min_pair_orders=1, min_lift=0.0)
    assert len(p) == 1
    r = p.iloc[0]
    # only o2 holds two categories; 4 revenue orders; 2 orders per category -> lift = 1*4/(2*2) = 1
    assert (r["category_a"], r["category_b"], r["pair_orders"]) == ("bed_bath_table", "sports_leisure", 1)
    assert r["lift"] == pytest.approx(1.0)
    assert gr.identify_cross_sell_pairs(warehouse, None).empty         # default needs 10 pair orders


def test_growth_needs_six_full_months_and_returns_typed_empty_frames(warehouse):
    c = gr.identify_growth_categories(warehouse, None)
    assert c.empty and list(c.columns) == ["category", "recent_revenue", "prior_revenue", "change_pct", "orders"]
    assert gr.identify_growth_states(warehouse, None).empty


def test_growth_insights_are_evidence_backed(warehouse):
    ins = gr.generate_growth_insights(warehouse, None, min_orders=1, min_customers=1, min_pair_orders=1)
    assert ins and all(i.rule and i.evidence for i in ins)
    assert any(i.kpi == "customers_per_seller" for i in ins)
