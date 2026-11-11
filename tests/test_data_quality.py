"""Data-quality and ingestion error-handling tests."""
from __future__ import annotations

import pandas as pd
import pytest

from config import settings
from ingestion import validate_data as v
from ingestion.exceptions import (
    EmptyDatasetError,
    MissingDataFilesError,
    SchemaMismatchError,
)
from ingestion.load_data import check_raw_files, read_raw_tables
from ingestion.transform_data import transform_all


# ------------------------------------------------------------ file handling
def test_missing_files_raise_with_every_missing_name(tmp_path):
    with pytest.raises(MissingDataFilesError) as exc:
        check_raw_files(tmp_path)
    msg = str(exc.value)
    assert all(name in msg for name in settings.RAW_FILES.values())
    assert "kaggle.com/datasets/olistbr" in msg


def test_single_missing_file_is_named(raw_dir):
    (raw_dir / settings.RAW_FILES["sellers"]).unlink()
    with pytest.raises(MissingDataFilesError) as exc:
        read_raw_tables(raw_dir)
    assert exc.value.missing == [settings.RAW_FILES["sellers"]]


def test_missing_column_raises_schema_error(raw_dir):
    path = raw_dir / settings.RAW_FILES["orders"]
    pd.read_csv(path).drop(columns=["order_status"]).to_csv(path, index=False)
    with pytest.raises(SchemaMismatchError, match="order_status"):
        read_raw_tables(raw_dir)


def test_empty_csv_raises(raw_dir):
    (raw_dir / settings.RAW_FILES["customers"]).write_text("")
    with pytest.raises(EmptyDatasetError):
        read_raw_tables(raw_dir)


def test_header_only_table_raises_empty_dataset(raw_tables):
    raw_tables["order_items"] = raw_tables["order_items"].iloc[0:0]
    with pytest.raises(EmptyDatasetError):
        transform_all(raw_tables)


def test_invalid_dates_become_null_and_are_logged(raw_tables):
    raw_tables["orders"].loc[raw_tables["orders"]["order_id"] == "o2", "order_delivered_customer_date"] = "not-a-date"
    result = transform_all(raw_tables)
    o2 = result.tables["fact_orders"].set_index("order_id").loc["o2"]
    assert pd.isna(o2["customer_delivery_ts"])
    assert not o2["has_valid_delivery_dates"]
    assert any("invalid order_delivered_customer_date" in s.step for s in result.log.steps)


def test_non_numeric_price_dropped_and_logged(raw_tables):
    raw_tables["order_items"].loc[0, "price"] = "abc"
    result = transform_all(raw_tables)
    assert any("non-numeric price" in s.step for s in result.log.steps)
    assert len(result.tables["fact_order_items"]) == 5


def test_missing_product_dimension_member_is_added_not_dropped(raw_tables):
    raw_tables["products"] = raw_tables["products"][raw_tables["products"]["product_id"] != "p3"]
    result = transform_all(raw_tables)
    p = result.tables["dim_products"].set_index("product_id")
    assert p.loc["p3", "category_en"] == "unknown"
    # revenue is preserved
    assert result.tables["fact_order_items"]["price"].sum() == pytest.approx(490.0)


# ------------------------------------------------------------ raw-layer checks
def test_dataset_metadata_counts_rows(raw_tables):
    meta = v.load_dataset_metadata(raw_tables).set_index("table")
    assert meta.loc["orders", "rows"] == 7          # includes the duplicate row
    assert meta.loc["orders", "duplicate_rows"] == 1
    assert set(meta.index) == set(settings.RAW_FILES)


def test_check_missing_values(raw_tables):
    mv = v.check_missing_values(raw_tables["orders"]).set_index("column")
    assert mv.loc["order_delivered_customer_date", "missing_count"] == 3
    assert mv.loc["order_id", "missing_count"] == 0
    assert mv.loc["order_delivered_customer_date", "missing_pct"] == pytest.approx(100 * 3 / 7, abs=0.01)


def test_check_duplicates_on_key(raw_tables):
    info = v.check_duplicates(raw_tables["orders"], ["order_id"])
    assert info["duplicate_rows"] == 1


def test_raw_duplicate_checks_warn_not_fail(raw_tables):
    res = {r.name: r for r in v.check_raw_duplicates(raw_tables)}
    assert res["raw_duplicates_orders"].status == v.WARN
    assert res["raw_duplicates_customers"].status == v.PASS


# ------------------------------------------------------- warehouse-layer checks
def test_primary_keys_pass_on_clean_tables(tables):
    assert all(r.status == v.PASS for r in v.validate_primary_keys(tables))


def test_primary_key_duplicate_is_detected(tables):
    bad = dict(tables)
    bad["fact_orders"] = pd.concat([tables["fact_orders"], tables["fact_orders"].iloc[[0]]])
    res = {r.name: r for r in v.validate_primary_keys(bad)}
    assert res["pk_fact_orders"].status == v.FAIL
    assert res["pk_fact_orders"].details["duplicate_keys"] == 1


def test_foreign_keys_pass_and_soft_keys_warn(tables):
    res = {r.name: r for r in v.validate_foreign_keys(tables)}
    assert all(r.status == v.PASS for n, r in res.items() if not n.startswith("soft_"))
    # seller zip 22000 and customer zips 40000/50000 are not in the geolocation fixture
    assert res["soft_fk_dim_customers.zip_prefix->dim_geolocation"].status == v.WARN


def test_foreign_key_orphan_is_detected(tables):
    bad = dict(tables)
    items = tables["fact_order_items"].copy()
    items.loc[0, "product_id"] = "ghost"
    bad["fact_order_items"] = items
    res = {r.name: r for r in v.validate_foreign_keys(bad)}
    assert res["fk_fact_order_items.product_id->dim_products"].status == v.FAIL


def test_date_validation_flags_delivery_before_purchase(tables):
    bad = dict(tables)
    fo = tables["fact_orders"].copy()
    fo.loc[fo["order_id"] == "o1", "customer_delivery_ts"] = pd.Timestamp("2016-12-01")
    bad["fact_orders"] = fo
    res = {r.name: r for r in v.validate_date_columns(bad)}
    assert res["dates_delivered_before_purchase"].status == v.WARN
    assert res["dates_delivered_before_purchase"].details["count"] == 1


def test_order_relationship_checks(tables):
    res = {r.name: r for r in v.validate_order_relationships(tables)}
    assert res["items_without_order"].status == v.PASS
    assert res["orders_without_items"].details["count"] == 1      # o6
    assert res["orders_without_payments"].details["count"] == 1   # o6
    assert res["orders_item_count_matches"].status == v.PASS


def test_revenue_reconciliation_passes(tables):
    res = {r.name: r for r in v.validate_revenue_calculations(tables)}
    for name in ("revenue_items_vs_orders", "freight_items_vs_orders", "payments_vs_orders",
                 "revenue_subset", "order_total_definition"):
        assert res[name].status == v.PASS, res[name].message


def test_revenue_reconciliation_detects_double_counting(tables):
    bad = dict(tables)
    fo = tables["fact_orders"].copy()
    fo.loc[fo["order_id"] == "o2", "items_value"] *= 2     # simulate a join fan-out
    bad["fact_orders"] = fo
    res = {r.name: r for r in v.validate_revenue_calculations(bad)}
    assert res["revenue_items_vs_orders"].status == v.FAIL


def test_check_data_types(tables):
    out = v.check_data_types(tables["fact_orders"], {"items_value": "float", "order_id": "string",
                                                     "purchase_ts": "datetime", "nope": "string"})
    ok = out.set_index("column")["ok"]
    assert ok["items_value"] and ok["order_id"] and ok["purchase_ts"]
    assert not ok["nope"]


def test_full_report_has_no_fail_on_fixture(raw_tables, tables):
    report = v.generate_data_quality_report(raw_tables, tables)
    fails = [c for c in report.checks if c.status == v.FAIL]
    assert not fails, [c.message for c in fails]
    d = report.to_dict()
    assert d["summary"]["WARN"] >= 1            # known fixture limitations are surfaced, not hidden
    assert "2016-2018" in d["notice"]
