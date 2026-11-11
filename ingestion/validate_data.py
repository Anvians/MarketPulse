"""Data-quality validation for MarketPulse.

Two layers:
* raw layer      - metadata, missing values, duplicates in the source CSVs;
* warehouse layer - keys, relationships, dates, order consistency and revenue
  reconciliation on the transformed tables (and, via
  :func:`validate_database_reconciliation`, on the loaded database).

Checks return :class:`CheckResult` objects with status PASS / WARN / FAIL. FAIL
means the data would produce wrong KPIs; WARN means a known data limitation to
be communicated, not hidden.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import settings
from ingestion.schema_spec import (
    RAW_PRIMARY_KEYS,
    WAREHOUSE_COLUMN_KINDS,
    WAREHOUSE_FOREIGN_KEYS,
    WAREHOUSE_PRIMARY_KEYS,
    WAREHOUSE_SOFT_KEYS,
)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class CheckResult:
    name: str
    category: str
    status: str
    message: str
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DataQualityReport:
    generated_at: str
    overall_status: str
    checks: list[CheckResult]
    dataset_metadata: list[dict]
    notice: str = settings.DATA_PERIOD_NOTICE

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "notice": self.notice,
            "summary": {s: sum(c.status == s for c in self.checks) for s in (PASS, WARN, FAIL)},
            "dataset_metadata": self.dataset_metadata,
            "checks": [c.as_dict() for c in self.checks],
        }

    def checks_frame(self) -> pd.DataFrame:
        return pd.DataFrame([c.as_dict() for c in self.checks])


# ------------------------------------------------------------ raw-layer checks
def load_dataset_metadata(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-file record counts, column counts, missing-cell share and exact-duplicate rows."""
    rows = []
    for name, df in raw.items():
        cells = df.shape[0] * df.shape[1]
        rows.append({
            "table": name,
            "file": settings.RAW_FILES.get(name, name),
            "rows": len(df),
            "columns": df.shape[1],
            "missing_cells_pct": round(100 * float(df.isna().sum().sum()) / cells, 3) if cells else 0.0,
            "duplicate_rows": int(df.duplicated().sum()),
        })
    return pd.DataFrame(rows)


def check_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Missing count and percentage per column (sorted, highest first)."""
    n = len(df)
    out = pd.DataFrame({
        "column": df.columns,
        "dtype": [str(t) for t in df.dtypes],
        "missing_count": [int(df[c].isna().sum()) for c in df.columns],
    })
    out["missing_pct"] = (100 * out["missing_count"] / n).round(3) if n else 0.0
    return out.sort_values("missing_count", ascending=False).reset_index(drop=True)


def check_duplicates(df: pd.DataFrame, subset: list[str] | None = None) -> dict:
    """Duplicate rows (exact, or on ``subset`` key columns)."""
    n = len(df)
    dup = int(df.duplicated(subset=subset).sum()) if n else 0
    return {"rows": n, "duplicate_rows": dup,
            "duplicate_pct": round(100 * dup / n, 3) if n else 0.0,
            "key": subset or "all columns"}


def check_raw_duplicates(raw: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Duplicates on each raw table's natural key (informational: cleaning removes them)."""
    results = []
    for table, key in RAW_PRIMARY_KEYS.items():
        info = check_duplicates(raw[table], key)
        status = PASS if info["duplicate_rows"] == 0 else WARN
        results.append(CheckResult(
            f"raw_duplicates_{table}", "raw", status,
            f"{info['duplicate_rows']} duplicate rows on {key} out of {info['rows']}"
            + ("" if status == PASS else " (removed during transformation)"),
            info,
        ))
    geo = check_duplicates(raw["geolocation"])
    results.append(CheckResult(
        "raw_duplicates_geolocation", "raw", PASS if geo["duplicate_rows"] == 0 else WARN,
        f"{geo['duplicate_rows']} exact duplicate rows of {geo['rows']}; "
        "geolocation is aggregated to one row per zip prefix", geo,
    ))
    return results


def _kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        return "string"
    return str(series.dtype)


def check_data_types(df: pd.DataFrame, expected: dict[str, str]) -> pd.DataFrame:
    """Compare actual column kinds with expected kinds (integer is accepted where float is expected)."""
    rows = []
    for col, want in expected.items():
        if col not in df.columns:
            rows.append({"column": col, "expected": want, "actual": "MISSING", "ok": False})
            continue
        got = _kind(df[col])
        ok = got == want or (want == "float" and got == "integer")
        rows.append({"column": col, "expected": want, "actual": got, "ok": ok})
    return pd.DataFrame(rows)


# ----------------------------------------------------- warehouse-layer checks
def validate_primary_keys(tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    results = []
    for table, key in WAREHOUSE_PRIMARY_KEYS.items():
        if table not in tables:
            results.append(CheckResult(f"pk_{table}", "keys", FAIL, f"table {table} missing"))
            continue
        df = tables[table]
        nulls = int(df[key].isna().any(axis=1).sum())
        dups = int(df.duplicated(subset=key).sum())
        ok = nulls == 0 and dups == 0
        results.append(CheckResult(
            f"pk_{table}", "keys", PASS if ok else FAIL,
            f"{table}{key}: {nulls} NULL keys, {dups} duplicate keys",
            {"null_keys": nulls, "duplicate_keys": dups, "rows": len(df)},
        ))
    return results


def validate_foreign_keys(tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    results = []
    for child, ccol, parent, pcol in WAREHOUSE_FOREIGN_KEYS:
        vals = tables[child][ccol].dropna()
        orphans = int((~vals.isin(tables[parent][pcol])).sum())
        results.append(CheckResult(
            f"fk_{child}.{ccol}->{parent}", "relationships", PASS if orphans == 0 else FAIL,
            f"{orphans} orphan values in {child}.{ccol}", {"orphans": orphans, "checked": len(vals)},
        ))
    for child, ccol, parent, pcol in WAREHOUSE_SOFT_KEYS:
        vals = tables[child][ccol].dropna()
        missing = int((~vals.isin(tables[parent][pcol])).sum())
        pct = round(100 * missing / len(vals), 2) if len(vals) else 0.0
        results.append(CheckResult(
            f"soft_fk_{child}.{ccol}->{parent}", "relationships", PASS if missing == 0 else WARN,
            f"{missing} of {len(vals)} ({pct}%) {child}.{ccol} values have no geolocation record "
            "(soft relationship, not enforced)",
            {"missing": missing, "checked": len(vals), "missing_pct": pct},
        ))
    return results


def validate_date_columns(tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    o = tables["fact_orders"]
    results: list[CheckResult] = []

    def add(name: str, count: int, msg: str, fail: bool = False) -> None:
        status = PASS if count == 0 else (FAIL if fail else WARN)
        results.append(CheckResult(name, "dates", status, f"{count} {msg}", {"count": count}))

    add("dates_purchase_missing", int(o["purchase_ts"].isna().sum()),
        "orders have no purchase timestamp", fail=True)
    add("dates_delivered_before_purchase",
        int((o["customer_delivery_ts"] < o["purchase_ts"]).sum()),
        "orders delivered before purchase (excluded from delivery metrics)")
    add("dates_approved_before_purchase", int((o["approved_ts"] < o["purchase_ts"]).sum()),
        "orders approved before purchase")
    add("dates_delivered_without_date",
        int(((o["order_status"] == settings.DELIVERED_STATUS) & o["customer_delivery_ts"].isna()).sum()),
        "'delivered' orders without a delivery date (excluded from delivery metrics)")
    add("dates_delivery_date_on_undelivered",
        int(((o["order_status"] != settings.DELIVERED_STATUS) & o["customer_delivery_ts"].notna()).sum()),
        "non-delivered orders that carry a delivery date")
    add("dates_estimated_missing", int(o["estimated_delivery_date"].isna().sum()),
        "orders have no estimated delivery date")

    valid_dates = o["purchase_ts"].dropna()
    if valid_dates.empty:
        results.append(CheckResult("dates_range", "dates", FAIL, "no valid purchase dates"))
    else:
        results.append(CheckResult(
            "dates_range", "dates", PASS,
            f"purchases span {valid_dates.min().date()} to {valid_dates.max().date()}",
            {"min": str(valid_dates.min().date()), "max": str(valid_dates.max().date())},
        ))
    return results


def validate_order_relationships(tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    o, items = tables["fact_orders"], tables["fact_order_items"]
    results: list[CheckResult] = []

    delivered_no_items = int(((o["order_status"] == settings.DELIVERED_STATUS) & (o["item_count"] == 0)).sum())
    results.append(CheckResult(
        "orders_delivered_without_items", "orders", PASS if delivered_no_items == 0 else WARN,
        f"{delivered_no_items} delivered orders have no item rows (cannot contribute revenue)",
        {"count": delivered_no_items},
    ))
    no_items = int((o["item_count"] == 0).sum())
    results.append(CheckResult(
        "orders_without_items", "orders", PASS,
        f"{no_items} of {len(o)} orders have no items (typically canceled/unavailable/created)",
        {"count": no_items, "total": len(o)},
    ))
    no_pay = int(o["payment_count"].isna().sum())
    results.append(CheckResult(
        "orders_without_payments", "orders", PASS if no_pay == 0 else WARN,
        f"{no_pay} orders have no payment record", {"count": no_pay},
    ))
    stray = int((~items["order_id"].isin(o["order_id"])).sum())
    results.append(CheckResult(
        "items_without_order", "orders", PASS if stray == 0 else FAIL,
        f"{stray} item rows reference no order", {"count": stray},
    ))
    mismatch = int((o["item_count"] != o["order_id"].map(items.groupby("order_id").size()).fillna(0)).sum())
    results.append(CheckResult(
        "orders_item_count_matches", "orders", PASS if mismatch == 0 else FAIL,
        f"{mismatch} orders whose item_count differs from item rows", {"count": mismatch},
    ))
    return results


def validate_revenue_calculations(tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    o, items, pay = tables["fact_orders"], tables["fact_order_items"], tables["fact_payments"]
    tol = settings.MONEY_TOLERANCE
    results: list[CheckResult] = []

    def reconcile(name: str, a: float, b: float, label: str) -> None:
        diff = abs(a - b)
        results.append(CheckResult(
            name, "revenue", PASS if diff <= tol else FAIL,
            f"{label}: {a:,.2f} vs {b:,.2f} (diff {diff:,.2f})", {"a": a, "b": b, "diff": diff},
        ))

    reconcile("revenue_items_vs_orders", float(items["price"].sum()), float(o["items_value"].sum()),
              "item-level price vs order-level items_value")
    reconcile("freight_items_vs_orders", float(items["freight_value"].sum()), float(o["freight_value"].sum()),
              "item-level freight vs order-level freight_value")
    reconcile("payments_vs_orders", float(pay["payment_value"].sum()), float(o["payment_value"].sum()),
              "payment-level vs order-level payment_value")

    rev_ids = set(o.loc[o["is_revenue_order"], "order_id"])
    reconcile("revenue_subset", float(items.loc[items["order_id"].isin(rev_ids), "price"].sum()),
              float(o.loc[o["is_revenue_order"], "items_value"].sum()),
              "revenue-order item price vs order-level items_value")
    total_gap = float((o["order_total_value"] - (o["items_value"] + o["freight_value"])).abs().max() or 0)
    results.append(CheckResult(
        "order_total_definition", "revenue", PASS if total_gap <= tol else FAIL,
        f"max |order_total_value - (items_value + freight_value)| = {total_gap:.4f}", {"max_gap": total_gap},
    ))

    both = o[o["payment_value"].notna() & (o["item_count"] > 0)]
    if len(both):
        off = int(((both["payment_value"] - both["order_total_value"]).abs() > 1.0).sum())
        pct = round(100 * off / len(both), 2)
        results.append(CheckResult(
            "payment_vs_order_total", "revenue", PASS if pct < 1 else WARN,
            f"{off} of {len(both)} orders ({pct}%) have payment_value differing from items+freight by "
            "more than 1.00 (vouchers, instalment interest, rounding). Revenue uses item price, not payments.",
            {"orders": off, "checked": len(both), "pct": pct},
        ))
    return results


def generate_data_quality_report(
    raw: dict[str, pd.DataFrame], tables: dict[str, pd.DataFrame]
) -> DataQualityReport:
    """Run every check and assemble one report."""
    checks: list[CheckResult] = []
    checks += check_raw_duplicates(raw)
    checks += validate_primary_keys(tables)
    checks += validate_foreign_keys(tables)
    checks += validate_date_columns(tables)
    checks += validate_order_relationships(tables)
    checks += validate_revenue_calculations(tables)
    for table, expected in WAREHOUSE_COLUMN_KINDS.items():
        types = check_data_types(tables[table], expected)
        bad = types[~types["ok"]]
        checks.append(CheckResult(
            f"dtypes_{table}", "types", PASS if bad.empty else FAIL,
            "all columns have expected types" if bad.empty
            else f"unexpected types: {bad.to_dict('records')}",
        ))
    overall = FAIL if any(c.status == FAIL for c in checks) else (
        WARN if any(c.status == WARN for c in checks) else PASS)
    return DataQualityReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        overall_status=overall,
        checks=checks,
        dataset_metadata=load_dataset_metadata(raw).to_dict("records"),
    )


# ---------------------------------------------------------- database layer
def validate_database_reconciliation(engine: Engine) -> list[CheckResult]:
    """Run reconciliation checks against the LOADED database (views + facts)."""
    queries = {
        "db_items_vs_orders_revenue": (
            "SELECT (SELECT COALESCE(SUM(price),0) FROM fact_order_items) AS a, "
            "(SELECT COALESCE(SUM(items_value),0) FROM fact_orders) AS b", "reconcile"),
        "db_payments_vs_orders": (
            "SELECT (SELECT COALESCE(SUM(payment_value),0) FROM fact_payments) AS a, "
            "(SELECT COALESCE(SUM(payment_value),0) FROM fact_orders) AS b", "reconcile"),
        "db_revenue_orders_view_unique": (
            "SELECT COUNT(*) - COUNT(DISTINCT order_id) AS v FROM vw_revenue_orders", "zero"),
        "db_order_review_view_unique": (
            "SELECT COUNT(*) - COUNT(DISTINCT order_id) AS v FROM vw_order_review", "zero"),
        "db_monthly_kpis_orders_match": (
            "SELECT ABS((SELECT COALESCE(SUM(orders),0) FROM vw_monthly_kpis) - "
            "(SELECT COUNT(*) FROM fact_orders WHERE is_revenue_order AND purchase_date_key IS NOT NULL)) AS v",
            "zero"),
        "db_delivery_flag_consistency": (
            "SELECT COUNT(*) AS v FROM fact_orders WHERE (is_late IS NOT NULL AND NOT has_valid_delivery_dates) "
            "OR (has_valid_delivery_dates AND is_late IS NULL)", "zero"),
    }
    results = []
    with engine.connect() as conn:
        for name, (sql, mode) in queries.items():
            row = conn.execute(text(sql)).one()
            if mode == "reconcile":
                a, b = float(row.a), float(row.b)
                ok = abs(a - b) <= settings.MONEY_TOLERANCE
                results.append(CheckResult(name, "database", PASS if ok else FAIL,
                                           f"{a:,.2f} vs {b:,.2f}", {"a": a, "b": b}))
            else:
                v = int(row.v)
                results.append(CheckResult(name, "database", PASS if v == 0 else FAIL,
                                           f"{v} violations", {"violations": v}))
    return results
