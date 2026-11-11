"""Page tests on a larger SYNTHETIC marketplace (tests/synthetic_large.py) so that the branches that
the 3-order fixture cannot reach (forecast, cohorts, clusters, delivery model, tests, text terms) run."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    import os

    from config import settings
    from config.database import check_connection, ensure_database_exists, get_engine
    from ingestion.load_data import load_warehouse, read_raw_tables
    from ingestion.transform_data import transform_all
    from ingestion.validate_data import generate_data_quality_report
    from synthetic_large import write_large_fixture

    s = settings.DatabaseSettings.from_env(name="marketpulse_test_large")
    try:
        ensure_database_exists(s)
        engine = get_engine(s)
        ok, msg = check_connection(engine)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    if not ok:
        pytest.skip(msg)
    d = tmp_path_factory.mktemp("large_raw")
    write_large_fixture(d, n_orders=5000)
    raw = read_raw_tables(d)
    res = transform_all(raw)
    load_warehouse(engine, res, d, quality_report=generate_data_quality_report(raw, res.tables).to_dict())
    old = {k: os.environ.get(k) for k in ("DB_NAME", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD")}
    os.environ.update(DB_NAME=s.name, DB_HOST=s.host, DB_PORT=str(s.port), DB_USER=s.user, DB_PASSWORD=s.password)
    from components import data
    data.refresh()
    data.engine.clear()
    yield engine
    for k, v in old.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    data.refresh()
    data.engine.clear()
    engine.dispose()


def _page(name):
    at = AppTest.from_file(APP, default_timeout=120).run()
    return at.switch_page(f"pages/{name}.py").run()


@pytest.mark.parametrize("page", ["executive", "revenue", "sales", "products", "customers", "satisfaction", "sellers", "logistics",
                                  "geography", "opportunities", "growth", "segmentation", "forecast", "stat_tests", "review_text", "data_quality"])
def test_pages_render_with_data(large_db, page):
    at = _page(page)
    assert not at.exception, [e.value for e in at.exception]
    if page != "forecast":      # the forecast page uses st.error as a verdict when the model fails its backtest
        assert not at.error


def test_segmentation_page_shows_segments_clusters_and_cohorts(large_db):
    at = _page("segmentation")
    text = " ".join(m.value for m in at.markdown)
    assert "Active repeat" in text and "clusters, silhouette" in text
    assert any(m.label == "Retention after 1 month" for m in at.metric)


def test_forecast_page_reports_whether_the_model_beat_the_naive_rule(large_db):
    at = _page("forecast")
    assert not at.exception
    assert [x.value for x in at.success] or [x.value for x in at.error]   # one verdict banner is always shown
    assert any("naive" in m.label.lower() for m in at.metric)


def test_delivery_risk_trains_on_button_press_and_gives_a_verdict(large_db):
    at = _page("delivery_risk")
    next(b for b in at.button if "Train" in b.label).click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert [x.value for x in at.success] or [x.value for x in at.error]
    assert any("Late rate in the test period" in m.value for m in at.markdown)


def test_stat_tests_page_shows_effect_sizes(large_db):
    at = _page("stat_tests")
    assert {m.label for m in at.metric} >= {"p-value", "Effect size", "Magnitude"}


def test_review_text_page_lists_terms(large_db):
    at = _page("review_text")
    assert any("not** a sentiment model" in i.value for i in at.info)
