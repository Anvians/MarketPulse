"""Read the raw Olist CSVs and load the transformed star schema into PostgreSQL."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import settings
from config.database import run_sql_file
from ingestion.exceptions import (
    EmptyDatasetError,
    MissingDataFilesError,
    SchemaMismatchError,
)
from ingestion.schema_spec import RAW_EXPECTED_COLUMNS, WAREHOUSE_LOAD_ORDER
from ingestion.transform_data import TransformResult

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ raw files
def check_raw_files(raw_dir: Path | None = None) -> dict[str, Path]:
    """Return ``{table: path}`` or raise MissingDataFilesError listing every missing file."""
    raw_dir = Path(raw_dir or settings.RAW_DATA_DIR)
    paths = {name: raw_dir / fname for name, fname in settings.RAW_FILES.items()}
    missing = [p.name for p in paths.values() if not p.is_file()]
    if missing:
        raise MissingDataFilesError(str(raw_dir), missing, settings.KAGGLE_DATASET_URL)
    return paths


def validate_expected_columns(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Fail if any required column is absent. Returns unexpected extra columns
    (tolerated, but reported) per table."""
    problems: list[str] = []
    extras: dict[str, list[str]] = {}
    for name, expected in RAW_EXPECTED_COLUMNS.items():
        actual = list(tables[name].columns)
        missing = [c for c in expected if c not in actual]
        if missing:
            problems.append(f"{name}: missing columns {missing}; found {actual}")
        extra = [c for c in actual if c not in expected]
        if extra:
            extras[name] = extra
    if problems:
        raise SchemaMismatchError("Raw files do not match the expected Olist layout:\n  " + "\n  ".join(problems))
    return extras


def read_raw_tables(raw_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    """Read all nine CSVs as text (so zip prefixes keep leading zeros), then verify
    columns. Typing is done explicitly in the transformation step."""
    paths = check_raw_files(raw_dir)
    tables: dict[str, pd.DataFrame] = {}
    for name, path in paths.items():
        try:
            # utf-8-sig strips a BOM if present (seen on the translation file).
            df = pd.read_csv(path, dtype="string", encoding="utf-8-sig", keep_default_na=True)
        except pd.errors.EmptyDataError as exc:
            raise EmptyDatasetError(f"{path.name} is empty") from exc
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype="string", encoding="latin-1", keep_default_na=True)
            logger.warning("%s is not UTF-8; read as latin-1", path.name)
        df.columns = [c.strip() for c in df.columns]
        logger.info("Read %s: %d rows, %d columns", path.name, len(df), df.shape[1])
        tables[name] = df
    validate_expected_columns(tables)
    return tables


# ------------------------------------------------------------------ database
def initialize_schema(engine: Engine) -> None:
    """(Re)create all warehouse tables. DESTRUCTIVE for warehouse tables."""
    run_sql_file(engine, settings.DATABASE_SQL_DIR / "create_tables.sql")


def apply_constraints_and_views(engine: Engine) -> None:
    """Add foreign keys, indexes and analytical views after the data is loaded."""
    for script in ("create_relationships.sql", "create_indexes.sql", "analytical_views.sql"):
        run_sql_file(engine, settings.DATABASE_SQL_DIR / script)


def load_tables(engine: Engine, tables: dict[str, pd.DataFrame], chunksize: int = 5000) -> dict[str, int]:
    """Append each warehouse table in dependency order; returns rows loaded per table."""
    loaded: dict[str, int] = {}
    with engine.begin() as conn:
        for name in WAREHOUSE_LOAD_ORDER:
            df = tables[name]
            df.to_sql(name, conn, if_exists="append", index=False, chunksize=chunksize)
            loaded[name] = len(df)
            logger.info("Loaded %s (%d rows)", name, len(df))
    return loaded


def _json_safe(obj: object) -> object:
    return json.loads(json.dumps(obj, default=str))


def record_run(
    engine: Engine,
    started_at: datetime,
    status: str,
    raw_dir: Path,
    loaded: dict[str, int],
    transform_log: pd.DataFrame,
    quality_report: dict | None,
    notes: str = "",
) -> int:
    """Persist run metadata (timestamp, row counts, transformations, quality report)."""
    with engine.begin() as conn:
        run_id = conn.execute(
            text(
                "INSERT INTO etl_run_log (started_at, finished_at, status, raw_dir, notes) "
                "VALUES (:s, :f, :st, :d, :n) RETURNING run_id"
            ),
            {"s": started_at, "f": datetime.now(timezone.utc), "st": status,
             "d": str(raw_dir), "n": notes},
        ).scalar_one()
        for table, rows in loaded.items():
            conn.execute(
                text("INSERT INTO etl_table_load_log (run_id, table_name, rows_loaded) VALUES (:r, :t, :n)"),
                {"r": run_id, "t": table, "n": rows},
            )
        for rec in transform_log.to_dict("records"):
            conn.execute(
                text(
                    "INSERT INTO etl_transformation_log "
                    "(run_id, table_name, step, rows_before, rows_after, detail) "
                    "VALUES (:r, :t, :s, :b, :a, :d)"
                ),
                {"r": run_id, "t": rec["table"], "s": rec["step"], "b": rec["rows_before"],
                 "a": rec["rows_after"], "d": rec["detail"]},
            )
        if quality_report is not None:
            conn.execute(
                text("INSERT INTO etl_quality_report (run_id, report) VALUES (:r, CAST(:j AS JSONB))"),
                {"r": run_id, "j": json.dumps(_json_safe(quality_report))},
            )
    return run_id


def load_warehouse(
    engine: Engine,
    result: TransformResult,
    raw_dir: Path,
    quality_report: dict | None = None,
    reinitialize: bool = True,
) -> int:
    """Full database load: (re)create tables -> load -> constraints/indexes/views -> log run.

    Returns the etl_run_log run_id.
    """
    started = datetime.now(timezone.utc)
    if reinitialize:
        initialize_schema(engine)
    loaded = load_tables(engine, result.tables)
    apply_constraints_and_views(engine)
    return record_run(
        engine, started, "success", raw_dir, loaded, result.log.to_frame(), quality_report
    )
