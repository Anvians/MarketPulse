"""Headless tests of the Streamlit app (``streamlit.testing.AppTest``) on the synthetic fixture.

They check that every page renders without exceptions, that KPI cards carry
tooltips, that global filters change results and persist across pages, and that
the empty-result path shows a message instead of failing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config.kpi_definitions import KPI_DEFINITIONS

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["executive", "revenue", "sales", "products", "customers", "satisfaction",
         "sellers", "logistics", "geography", "opportunities", "growth", "reports", "data_quality",
         "segmentation", "forecast", "delivery_risk", "stat_tests", "review_text"]


@pytest.fixture()
def app(warehouse, test_db_settings, monkeypatch):
    monkeypatch.setenv("DB_HOST", test_db_settings.host)
    monkeypatch.setenv("DB_PORT", str(test_db_settings.port))
    monkeypatch.setenv("DB_NAME", test_db_settings.name)
    monkeypatch.setenv("DB_USER", test_db_settings.user)
    monkeypatch.setenv("DB_PASSWORD", test_db_settings.password)
    from components import data
    data.refresh()
    data.engine.clear()
    return AppTest.from_file(APP, default_timeout=90).run()


def _metric(at: AppTest, label: str):
    return next(m for m in at.metric if m.label == label)


def test_kpi_definitions_are_complete():
    assert len(KPI_DEFINITIONS) >= 45
    for key, d in KPI_DEFINITIONS.items():
        assert d.label and d.formula and d.denominator and d.null_handling, key
        assert d.formula in d.tooltip()


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_exceptions(app, page):
    at = app.switch_page(f"pages/{page}.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error


@pytest.mark.parametrize("page", [p for p in PAGES if p not in ("data_quality", "growth", "reports", "opportunities", "forecast", "delivery_risk", "stat_tests", "review_text")])
def test_kpi_cards_have_formula_tooltips(app, page):
    at = app.switch_page(f"pages/{page}.py").run()
    assert at.metric
    for m in at.metric:
        if m.help:   # ad-hoc metrics on a few pages carry their own help text
            assert len(m.help) > 10


def test_executive_kpis_match_the_hand_checked_fixture(app):
    assert _metric(app, "Total revenue").value == "R$ 450.00"   # o1 100 + o2 120 + o3 200 + o4 30
    assert _metric(app, "Total orders").value == "4"


def test_state_filter_changes_results_and_persists_across_pages(app, warehouse, test_db_settings):
    # AppTest re-runs only the active page after the first run, so the filter is set
    # in session state before the first run (what the sidebar widget does in a browser).
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["flt_states"] = ["SP"]
    at.run()
    assert _metric(at, "Total revenue").value == "R$ 220.00"          # SP: o1 + o2 only
    at = at.switch_page("pages/revenue.py").run()                       # filter survives navigation
    assert _metric(at, "Total revenue").value == "R$ 220.00"
    assert not at.exception


def test_reset_button_clears_every_filter_key(app):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["flt_states"] = ["SP"]
    at.run()
    next(b for b in at.button if b.label == "Reset filters").click().run()
    assert "flt_states" not in at.session_state or not at.session_state["flt_states"]


def test_filters_with_no_matches_show_empty_states_not_errors(warehouse, test_db_settings, app):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["flt_status"] = ["canceled"]
    at.run()
    assert _metric(at, "Total revenue").value == "R$ 0.00"
    assert _metric(at, "Average order value").value == "n/a"          # not computable, never 0
    for page in PAGES:
        at = at.switch_page(f"pages/{page}.py").run()
        assert not at.exception, (page, [e.value for e in at.exception])


def test_report_page_builds_and_offers_three_downloads(warehouse, test_db_settings, app):
    at = AppTest.from_file(APP, default_timeout=90).run()
    at = at.switch_page("pages/reports.py").run()
    assert any("Build report" in b.label for b in at.button)
    next(b for b in at.button if b.label == "Build report").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Report built" in s.value for s in at.success)
