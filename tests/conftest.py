"""Shared fixtures.

IMPORTANT: the CSV content below is a tiny SYNTHETIC fixture used only to test
code paths and hand-checkable arithmetic. It is not Olist data and no analytical
result in the application is ever derived from it.

Fixture design (expected values are asserted in the tests):

order  customer(person)  status     items (price/freight)               payments            delivered vs estimated
o1     c1 (u1)           delivered  p1/s1 100/10                        card 110            +10d5h, 5 days early  -> on time (-5)
o2     c2 (u1)           delivered  p1/s1 50/5 ; p2/s2 70/8             card 100, voucher 33 5 days late         -> late (+5)
o3     c3 (u2)           delivered  p2/s2 200/20                        boleto 220          delivered same DATE as estimate -> on time (0)
o4     c4 (u3)           shipped    p3/s1 30/3                          card 33             no delivery date
o5     c5 (u4)           canceled   p3/s1 40/4                          card 44             -
o6     c6 (u5)           created    (no items)                          (none)              -
plus: duplicate o1 row, an orphan item/review for 'o_missing', duplicate review row,
      a review with invalid score 7, an out-of-Brazil geolocation row.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from config import settings
from config.database import check_connection, ensure_database_exists, get_engine
from ingestion.load_data import read_raw_tables
from ingestion.transform_data import transform_all


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    pd.DataFrame(rows, columns=header).to_csv(path, index=False)


def write_fixture_csvs(d: Path) -> Path:
    """Write the nine synthetic fixture CSVs into ``d`` (must exist)."""
    f = settings.RAW_FILES

    _write(d / f["customers"],
           ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"],
           [["c1", "u1", "01046", "sao paulo", "SP"],
            ["c2", "u1", "01046", "sao paulo", "SP"],
            ["c3", "u2", "20000", "rio de janeiro", "RJ"],
            ["c4", "u3", "30000", "belo horizonte", "MG"],
            ["c5", "u4", "40000", "salvador", "BA"],
            ["c6", "u5", "50000", "recife", "PE"]])

    ohead = ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
             "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"]
    o1 = ["o1", "c1", "delivered", "2017-01-10 10:00:00", "2017-01-10 11:00:00", "2017-01-12 09:00:00",
          "2017-01-20 15:00:00", "2017-01-25 00:00:00"]
    _write(d / f["orders"], ohead, [
        o1,
        ["o2", "c2", "delivered", "2017-03-01 09:00:00", "2017-03-01 10:00:00", "2017-03-03 09:00:00",
         "2017-03-20 12:00:00", "2017-03-15 00:00:00"],
        ["o3", "c3", "delivered", "2017-02-05 08:00:00", "2017-02-05 09:00:00", "2017-02-07 09:00:00",
         "2017-02-15 18:00:00", "2017-02-15 00:00:00"],
        ["o4", "c4", "shipped", "2017-03-10 08:00:00", "2017-03-10 09:00:00", "2017-03-12 09:00:00",
         "", "2017-04-10 00:00:00"],
        ["o5", "c5", "canceled", "2017-03-11 08:00:00", "", "", "", "2017-04-11 00:00:00"],
        ["o6", "c6", "created", "2017-03-12 08:00:00", "", "", "", "2017-04-12 00:00:00"],
        o1,  # exact duplicate order row
    ])

    ihead = ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"]
    sl = "2017-01-15 00:00:00"
    _write(d / f["order_items"], ihead, [
        ["o1", "1", "p1", "s1", sl, "100.00", "10.00"],
        ["o2", "1", "p1", "s1", sl, "50.00", "5.00"],
        ["o2", "2", "p2", "s2", sl, "70.00", "8.00"],
        ["o3", "1", "p2", "s2", sl, "200.00", "20.00"],
        ["o4", "1", "p3", "s1", sl, "30.00", "3.00"],
        ["o5", "1", "p3", "s1", sl, "40.00", "4.00"],
        ["o_missing", "1", "p1", "s1", sl, "99.00", "9.00"],  # orphan
    ])

    _write(d / f["payments"],
           ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"],
           [["o1", "1", "credit_card", "1", "110.00"],
            ["o2", "1", "credit_card", "2", "100.00"],
            ["o2", "2", "voucher", "1", "33.00"],
            ["o3", "1", "boleto", "1", "220.00"],
            ["o4", "1", "credit_card", "1", "33.00"],
            ["o5", "1", "credit_card", "1", "44.00"]])

    rhead = ["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message",
             "review_creation_date", "review_answer_timestamp"]
    _write(d / f["reviews"], rhead, [
        ["r1", "o1", "5", "", "otimo", "2017-01-21 00:00:00", "2017-01-22 10:00:00"],
        ["r1", "o1", "5", "", "otimo", "2017-01-21 00:00:00", "2017-01-21 08:00:00"],  # duplicate key, earlier answer
        ["r2", "o2", "1", "", "atrasou", "2017-03-21 00:00:00", "2017-03-22 10:00:00"],
        ["r2b", "o2", "3", "", "", "2017-03-25 00:00:00", "2017-03-26 10:00:00"],  # later review for same order
        ["r3", "o3", "4", "", "", "2017-02-16 00:00:00", "2017-02-17 10:00:00"],
        ["r_bad", "o4", "7", "", "", "2017-03-30 00:00:00", "2017-03-31 10:00:00"],  # invalid score
        ["r6", "o_missing", "5", "", "", "2017-03-30 00:00:00", "2017-03-31 10:00:00"],  # orphan
    ])

    _write(d / f["products"],
           ["product_id", "product_category_name", "product_name_lenght", "product_description_lenght",
            "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"],
           [["p1", "cama_mesa_banho", "40", "300", "2", "500", "20", "10", "15"],
            ["p2", "esporte_lazer", "50", "400", "1", "1000", "30", "20", "10"],
            ["p3", "categoria_sem_traducao", "30", "200", "1", "250", "10", "10", "10"],
            ["p4", "", "", "", "", "", "", "", ""]])

    _write(d / f["sellers"], ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
           [["s1", "13023", "campinas", "SP"], ["s2", "22000", "rio de janeiro", "RJ"],
            ["s3", "99999", "nowhere", "ZZ"]])

    _write(d / f["geolocation"],
           ["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state"],
           [["01046", "-23.55", "-46.63", "sao paulo", "SP"],
            ["01046", "-23.56", "-46.64", "sao paulo", "SP"],
            ["01046", "-23.57", "-46.65", "sao paulo", "SP"],
            ["20000", "-22.90", "-43.20", "rio de janeiro", "RJ"],
            ["20000", "-22.92", "-43.22", "rio de janeiro", "RJ"],
            ["30000", "-19.92", "-43.94", "belo horizonte", "MG"],
            ["13023", "-22.90", "-47.06", "campinas", "SP"],
            ["99999", "45.0", "10.0", "outside", "XX"]])  # outside Brazil -> dropped

    _write(d / f["category_translation"], ["product_category_name", "product_category_name_english"],
           [["cama_mesa_banho", "bed_bath_table"], ["esporte_lazer", "sports_leisure"]])
    return d


@pytest.fixture()
def raw_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    return write_fixture_csvs(d)


@pytest.fixture()
def raw_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    return read_raw_tables(raw_dir)


@pytest.fixture()
def transformed(raw_tables):
    return transform_all(raw_tables)


@pytest.fixture()
def tables(transformed) -> dict[str, pd.DataFrame]:
    return transformed.tables


# ----------------------------------------------------------- database fixtures
TEST_DB_NAME = "marketpulse_test"


@pytest.fixture(scope="session")
def test_db_settings():
    """Connection settings for the integration-test database (never the real one)."""
    return settings.DatabaseSettings.from_env(name=os.getenv("TEST_DB_NAME", TEST_DB_NAME))


@pytest.fixture(scope="session")
def db_engine(test_db_settings):
    """Engine on a dedicated test database. Skips (with the reason) if PostgreSQL is unreachable."""
    try:
        ensure_database_exists(test_db_settings)
    except Exception as exc:  # noqa: BLE001 - surfaced as an explicit skip reason
        pytest.skip(f"PostgreSQL not reachable for integration tests: {exc}")
    engine = get_engine(test_db_settings)
    ok, msg = check_connection(engine)
    if not ok:
        pytest.skip(f"PostgreSQL not reachable for integration tests: {msg}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def warehouse(db_engine, tmp_path_factory):
    """Session-scoped engine on a test database loaded once with the synthetic
    fixture (analytics tests are read-only, so they can share it)."""
    from ingestion.load_data import load_warehouse

    from ingestion.validate_data import generate_data_quality_report

    d = tmp_path_factory.mktemp("analytics_raw")
    write_fixture_csvs(d)
    raw = read_raw_tables(d)
    result = transform_all(raw)
    report = generate_data_quality_report(raw, result.tables).to_dict()
    load_warehouse(db_engine, result, d, quality_report=report)
    return db_engine
