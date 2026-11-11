"""System-level helpers: database / ETL status, data-quality access, search.

These back the Data Quality page and the global search functions. Table and
column identifiers used in dynamic SQL always come from ``information_schema``
or a fixed whitelist, never from user input; user text is only ever bound as a
parameter.
"""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from analytics.base import read_sql, scalar
from ingestion.schema_spec import WAREHOUSE_LOAD_ORDER


def get_database_status(engine: Engine) -> dict:
    """Connection check + row counts. Never raises for connection problems."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
            name = conn.execute(text("SELECT current_database()")).scalar_one()
    except SQLAlchemyError as exc:
        return {"connected": False, "error": str(exc.__cause__ or exc).splitlines()[0], "database": None,
                "version": None, "tables": pd.DataFrame(columns=["table", "rows"])}
    return {"connected": True, "error": None, "database": name, "version": str(version).split(",")[0],
            "tables": table_row_counts(engine)}


def table_row_counts(engine: Engine) -> pd.DataFrame:
    """Exact row count of every warehouse table (whitelisted names)."""
    rows = []
    with engine.connect() as conn:
        for t in WAREHOUSE_LOAD_ORDER:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
            except SQLAlchemyError:
                conn.rollback()
                n = None
            rows.append({"table": t, "rows": n})
    return pd.DataFrame(rows)


def warehouse_is_loaded(engine: Engine) -> bool:
    """True when fact_orders exists and has rows (used to show a helpful setup message otherwise)."""
    try:
        return bool(scalar(engine, "SELECT COUNT(*) FROM fact_orders"))
    except SQLAlchemyError:
        return False


def get_data_processing_status(engine: Engine) -> dict:
    """Latest ETL run (timestamp, status, source folder) with per-table load counts
    and the transformation log. ``None`` run when the pipeline never ran."""
    try:
        runs = read_sql(engine, "SELECT run_id, started_at, finished_at, status, raw_dir, notes "
                                "FROM etl_run_log ORDER BY run_id DESC LIMIT 1")
    except SQLAlchemyError:
        return {"run": None, "loads": pd.DataFrame(), "transformations": pd.DataFrame()}
    if runs.empty:
        return {"run": None, "loads": pd.DataFrame(), "transformations": pd.DataFrame()}
    run = runs.iloc[0].to_dict()
    rid = int(run["run_id"])
    loads = read_sql(engine, "SELECT table_name, rows_loaded FROM etl_table_load_log WHERE run_id = :r ORDER BY table_name", {"r": rid})
    trans = read_sql(engine, "SELECT table_name, step, rows_before, rows_after, detail FROM etl_transformation_log "
                             "WHERE run_id = :r ORDER BY log_id", {"r": rid})
    return {"run": run, "loads": loads, "transformations": trans}


def load_quality_report(engine: Engine) -> dict | None:
    """The data-quality report stored by the latest pipeline run (None if absent)."""
    try:
        raw = scalar(engine, "SELECT report::text FROM etl_quality_report ORDER BY run_id DESC LIMIT 1")
    except SQLAlchemyError:
        return None
    return json.loads(raw) if raw else None


def describe_columns(engine: Engine, table: str) -> pd.DataFrame:
    """Per column of a warehouse table: type, nullable, rows, missing count and missing %."""
    if table not in WAREHOUSE_LOAD_ORDER:
        raise ValueError(f"Unknown table {table!r}")
    cols = read_sql(
        engine,
        "SELECT column_name AS column, data_type AS data_type, is_nullable = 'YES' AS nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position",
        {"t": table})
    if cols.empty:
        return cols.assign(rows=pd.Series(dtype=int), missing=pd.Series(dtype=int), missing_pct=pd.Series(dtype=float))
    quote = engine.dialect.identifier_preparer.quote
    counts = ", ".join(f"COUNT({quote(c)}) AS c{i}" for i, c in enumerate(cols["column"]))
    row = read_sql(engine, f"SELECT COUNT(*) AS n, {counts} FROM {table}").iloc[0]
    n = int(row["n"])
    cols["rows"] = n
    cols["missing"] = [n - int(row[f"c{i}"]) for i in range(len(cols))]
    cols["missing_pct"] = 100 * cols["missing"] / n if n else 0.0
    return cols


def get_data_period(engine: Engine) -> dict:
    """First/last purchase date and order count (for the 'historical data' banner)."""
    row = read_sql(engine, "SELECT MIN(purchase_ts)::date AS first_day, MAX(purchase_ts)::date AS last_day, COUNT(*) AS orders FROM fact_orders").iloc[0]
    return {"first_day": None if pd.isna(row["first_day"]) else row["first_day"],
            "last_day": None if pd.isna(row["last_day"]) else row["last_day"], "orders": int(row["orders"])}


# ---------------------------------------------------------------------- search
def search_customer(engine: Engine, query: str, limit: int = 50) -> pd.DataFrame:
    """Find customers by (part of) their anonymised ``customer_unique_id``."""
    q = query.strip().lower()
    cols = ["customer_unique_id", "state", "city", "orders", "revenue", "first_purchase", "last_purchase"]
    if not q:
        return pd.DataFrame(columns=cols)
    return read_sql(
        engine,
        "SELECT c.customer_unique_id, c.state, c.city, "
        "COUNT(o.order_id) FILTER (WHERE o.is_revenue_order) AS orders, "
        "COALESCE(SUM(o.items_value) FILTER (WHERE o.is_revenue_order), 0) AS revenue, "
        "MIN(o.purchase_ts)::date AS first_purchase, MAX(o.purchase_ts)::date AS last_purchase\n"
        "FROM dim_customers c LEFT JOIN fact_orders o ON o.customer_unique_id = c.customer_unique_id\n"
        "WHERE lower(c.customer_unique_id) LIKE :q\n"
        "GROUP BY c.customer_unique_id, c.state, c.city ORDER BY revenue DESC, c.customer_unique_id LIMIT :n",
        {"q": f"%{q}%", "n": int(limit)})


def get_customer_orders(engine: Engine, customer_unique_id: str) -> pd.DataFrame:
    """All orders of one customer with value, delivery outcome and review."""
    return read_sql(
        engine,
        "SELECT o.order_id, o.purchase_ts, o.order_status, o.items_value, o.freight_value, o.primary_payment_type, "
        "o.delivery_delay_days, r.review_score\n"
        "FROM fact_orders o LEFT JOIN vw_order_review r ON r.order_id = o.order_id\n"
        "WHERE o.customer_unique_id = :c ORDER BY o.purchase_ts", {"c": customer_unique_id})


def search_product_category(engine: Engine, query: str, limit: int = 50) -> pd.DataFrame:
    """Categories whose English or Portuguese name contains ``query``: category, products."""
    q = f"%{query.strip().lower()}%"
    return read_sql(
        engine,
        "SELECT category_en AS category, COUNT(*) AS products FROM dim_products "
        "WHERE lower(category_en) LIKE :q OR lower(COALESCE(category_pt, '')) LIKE :q "
        "GROUP BY category_en ORDER BY products DESC, category_en LIMIT :n", {"q": q, "n": int(limit)})


def get_filter_options(engine: Engine) -> dict:
    """Values for the global filter widgets (read from the loaded data)."""
    def col(sql: str) -> list[str]:
        return [str(v) for v in read_sql(engine, sql).iloc[:, 0].dropna().tolist()]

    period = get_data_period(engine)
    return {
        "states": col("SELECT DISTINCT customer_state FROM fact_orders WHERE customer_state IS NOT NULL ORDER BY 1"),
        "categories": col("SELECT DISTINCT category_en FROM dim_products WHERE category_en IS NOT NULL ORDER BY 1"),
        "sellers": col("SELECT seller_id FROM dim_sellers ORDER BY 1"),
        "payment_types": col("SELECT DISTINCT primary_payment_type FROM fact_orders WHERE primary_payment_type IS NOT NULL ORDER BY 1"),
        "order_statuses": col("SELECT DISTINCT order_status FROM fact_orders ORDER BY 1"),
        "min_date": period["first_day"], "max_date": period["last_day"],
    }
