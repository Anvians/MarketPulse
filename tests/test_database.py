"""Database integration tests (require a reachable PostgreSQL; skipped with a
reason otherwise). They load the synthetic fixture into a dedicated test
database and verify constraints, views and SQL joins against hand-computed values."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from config.database import check_connection, ensure_database_exists, get_engine
from config.settings import DatabaseSettings
from ingestion.exceptions import DatabaseConnectionError
from ingestion.load_data import load_warehouse
from ingestion.validate_data import FAIL, validate_database_reconciliation


@pytest.fixture(scope="module")
def loaded_db(db_engine, tmp_path_factory):
    """Load the fixture once per module (these tests only read, or roll back what they change);
    reloading for every test was what made the suite slow."""
    from ingestion.load_data import read_raw_tables
    from ingestion.transform_data import transform_all
    from conftest import write_fixture_csvs

    d = tmp_path_factory.mktemp("db_raw")
    write_fixture_csvs(d)
    result = transform_all(read_raw_tables(d))
    run_id = load_warehouse(db_engine, result, d, quality_report={"overall_status": "PASS"})
    return db_engine, run_id


def q(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def test_row_counts_match_transformed_tables(loaded_db, transformed):
    engine, _ = loaded_db
    for name, df in transformed.tables.items():
        n = q(engine, f"SELECT COUNT(*) FROM {name}")[0][0]
        assert n == len(df), name


def test_foreign_keys_exist_and_are_enforced(loaded_db):
    engine, _ = loaded_db
    fks = q(engine, "SELECT COUNT(*) FROM information_schema.table_constraints "
                    "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public' "
                    "AND table_name LIKE 'fact_%'")[0][0]
    assert fks >= 8
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO fact_order_items (order_id, order_item_id, product_id, seller_id, price, freight_value) "
                "VALUES ('nope', 1, 'p1', 's1', 1, 1)"))


def test_check_constraints_reject_bad_review_score(loaded_db):
    engine, _ = loaded_db
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO fact_reviews (review_id, order_id, review_score) VALUES ('x', 'o1', 9)"))


def test_indexes_created(loaded_db):
    engine, _ = loaded_db
    names = {r[0] for r in q(engine, "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
    for expected in ("idx_orders_purchase_ts", "idx_items_seller", "idx_reviews_order", "idx_products_category"):
        assert expected in names


def test_revenue_orders_view_has_one_row_per_order(loaded_db):
    engine, _ = loaded_db
    rows = q(engine, "SELECT order_id FROM vw_revenue_orders ORDER BY order_id")
    assert [r[0] for r in rows] == ["o1", "o2", "o3", "o4"]


def test_order_review_view_one_review_per_order_latest_wins(loaded_db):
    engine, _ = loaded_db
    rows = dict(q(engine, "SELECT order_id, review_score FROM vw_order_review"))
    assert rows == {"o1": 5, "o2": 3, "o3": 4}      # o2: later review (3) beats earlier (1)


def test_monthly_kpis_view(loaded_db):
    engine, _ = loaded_db
    rows = {r[0]: r for r in q(engine, "SELECT year_month, orders, product_revenue, avg_order_value, "
                                       "freight_charges FROM vw_monthly_kpis")}
    assert set(rows) == {"2017-01", "2017-02", "2017-03"}
    assert float(rows["2017-01"][2]) == 100.0
    # March has o2 (120) and o4 (30) -> 150 revenue, 2 orders, AOV 75; canceled o5 excluded
    assert rows["2017-03"][1] == 2
    assert float(rows["2017-03"][2]) == 150.0
    assert float(rows["2017-03"][3]) == 75.0
    assert float(rows["2017-03"][4]) == 16.0


def test_item_join_does_not_inflate_revenue(loaded_db):
    """Joining items to products/sellers/orders must keep the same revenue as the order grain."""
    engine, _ = loaded_db
    item_rev = q(engine, "SELECT SUM(price) FROM vw_item_details WHERE is_revenue_order")[0][0]
    order_rev = q(engine, "SELECT SUM(items_value) FROM vw_revenue_orders")[0][0]
    assert float(item_rev) == float(order_rev) == 450.0


def test_customer_summary_repeat_flag(loaded_db):
    engine, _ = loaded_db
    rows = {r[0]: (r[1], bool(r[2])) for r in q(
        engine, "SELECT customer_unique_id, orders, is_repeat_customer FROM vw_customer_summary")}
    assert rows == {"u1": (2, True), "u2": (1, False), "u3": (1, False)}
    n_repeat = sum(1 for _, rep in rows.values() if rep)
    assert n_repeat / len(rows) == pytest.approx(1 / 3)


def test_delivery_performance_view(loaded_db):
    engine, _ = loaded_db
    rows = {r[0]: (r[1], r[2]) for r in q(
        engine, "SELECT order_id, delivery_delay_days, is_late FROM vw_delivery_performance")}
    assert rows == {"o1": (-5, False), "o2": (5, True), "o3": (0, False)}


def test_seller_summary_view(loaded_db):
    engine, _ = loaded_db
    rows = {r[0]: r for r in q(engine, "SELECT seller_id, orders, items_sold, product_revenue, delivered_orders, "
                                       "late_orders FROM vw_seller_summary")}
    # s1: o1(100), o2(50), o4(30) -> 3 orders, 180 revenue; o5 canceled excluded
    assert rows["s1"][1] == 3 and float(rows["s1"][3]) == 180.0
    assert rows["s1"][4] == 2 and rows["s1"][5] == 1     # o1 on time, o2 late (o4 undelivered)
    # s2: o2(70), o3(200)
    assert rows["s2"][1] == 2 and float(rows["s2"][3]) == 270.0
    assert "s3" not in rows                               # seller without orders


def test_category_summary_view_revenue_sums_to_total(loaded_db):
    engine, _ = loaded_db
    rows = q(engine, "SELECT category_en, product_revenue FROM vw_category_summary")
    assert sum(float(r[1]) for r in rows) == 450.0
    by_cat = {r[0]: float(r[1]) for r in rows}
    assert by_cat["bed_bath_table"] == 150.0            # p1: o1 100 + o2 50


def test_database_reconciliation_checks_pass(loaded_db):
    engine, _ = loaded_db
    results = validate_database_reconciliation(engine)
    assert not [r for r in results if r.status == FAIL], [r.message for r in results]


def test_etl_logs_written(loaded_db):
    engine, run_id = loaded_db
    status = q(engine, "SELECT status FROM etl_run_log WHERE run_id = :r", r=run_id)[0][0]
    assert status == "success"
    loaded = dict(q(engine, "SELECT table_name, rows_loaded FROM etl_table_load_log WHERE run_id = :r", r=run_id))
    assert loaded["fact_orders"] == 6
    assert q(engine, "SELECT COUNT(*) FROM etl_transformation_log WHERE run_id = :r", r=run_id)[0][0] > 0
    assert q(engine, "SELECT report->>'overall_status' FROM etl_quality_report WHERE run_id = :r", r=run_id)[0][0] == "PASS"


def test_sql_validation_script_runs(loaded_db):
    """database/validation_queries.sql executes and reports zero violations."""
    from config import settings
    engine, _ = loaded_db
    script = (settings.DATABASE_SQL_DIR / "validation_queries.sql").read_text()
    code = "\n".join(line for line in script.splitlines() if not line.strip().startswith("--"))
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert len(statements) >= 9
    with engine.connect() as conn:
        for stmt in statements:
            row = conn.execute(text(stmt)).mappings().one()
            if "violations" in row:
                assert row["violations"] == 0, row
            else:
                values = [v for k, v in row.items() if k != "check_name"]
                assert float(values[0]) == pytest.approx(float(values[1])), row


def test_reload_is_idempotent(db_engine, transformed, raw_dir):
    load_warehouse(db_engine, transformed, raw_dir)
    load_warehouse(db_engine, transformed, raw_dir)
    assert q(db_engine, "SELECT COUNT(*) FROM fact_orders")[0][0] == 6


# ------------------------------------------------------------ connection errors
def test_invalid_connection_is_reported_not_raised():
    engine = get_engine(DatabaseSettings(host="localhost", port=1, name="x", user="x", password="x"))
    ok, msg = check_connection(engine)
    assert ok is False and msg


def test_ensure_database_raises_clear_error_on_bad_server():
    with pytest.raises(DatabaseConnectionError):
        ensure_database_exists(DatabaseSettings(host="localhost", port=1, name="x", user="x", password="x"))
