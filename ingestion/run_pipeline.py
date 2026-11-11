"""Command-line entry point for the MarketPulse data foundation.

Examples
--------
Full run (read CSVs -> validate -> transform -> create DB -> load):
    python -m ingestion.run_pipeline

Validate and transform only, no database needed:
    python -m ingestion.run_pipeline --skip-db

Use a different raw-data folder or database name:
    python -m ingestion.run_pipeline --raw-dir /path/to/csvs --db-name marketpulse_dev
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from config import settings
from config.database import check_connection, ensure_database_exists, get_engine
from ingestion.exceptions import DataFoundationError
from ingestion.load_data import load_warehouse, read_raw_tables
from ingestion.transform_data import transform_all
from ingestion.validate_data import (
    FAIL,
    generate_data_quality_report,
    validate_database_reconciliation,
)

logger = logging.getLogger("marketpulse.pipeline")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MarketPulse data foundation pipeline")
    p.add_argument("--raw-dir", type=Path, default=settings.RAW_DATA_DIR,
                   help="folder containing the nine Olist CSV files")
    p.add_argument("--db-name", default=None, help="override DB_NAME")
    p.add_argument("--skip-db", action="store_true", help="validate/transform only; do not touch PostgreSQL")
    p.add_argument("--save-processed", action="store_true",
                   help="also write processed tables as CSV into data/processed/")
    p.add_argument("--allow-failed-checks", action="store_true",
                   help="load even if a data-quality check FAILs (not recommended)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    logger.info("Step 1/5: reading raw files from %s", args.raw_dir)
    raw = read_raw_tables(args.raw_dir)

    logger.info("Step 2/5: transforming")
    result = transform_all(raw)

    logger.info("Step 3/5: validating")
    report = generate_data_quality_report(raw, result.tables)
    out_dir = settings.PROCESSED_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data_quality_report.json").write_text(json.dumps(report.to_dict(), indent=2, default=str))
    result.log.to_frame().to_csv(out_dir / "transformation_log.csv", index=False)
    summary = report.to_dict()["summary"]
    logger.info("Data quality: %s (PASS=%d WARN=%d FAIL=%d)", report.overall_status,
                summary["PASS"], summary["WARN"], summary["FAIL"])
    for c in report.checks:
        if c.status != "PASS":
            logger.warning("[%s] %s - %s", c.status, c.name, c.message)

    if args.save_processed:
        for name, df in result.tables.items():
            df.to_csv(out_dir / f"{name}.csv", index=False)
        logger.info("Processed tables written to %s", out_dir)

    if report.overall_status == FAIL and not args.allow_failed_checks:
        logger.error("Aborting: data-quality FAIL checks present (see data_quality_report.json).")
        return 2

    if args.skip_db:
        logger.info("--skip-db set: finished without loading PostgreSQL")
        return 0

    logger.info("Step 4/5: preparing database")
    db_settings = settings.DatabaseSettings.from_env(**({"name": args.db_name} if args.db_name else {}))
    created = ensure_database_exists(db_settings)
    logger.info("Database %s %s", db_settings.name, "created" if created else "already exists")
    engine = get_engine(db_settings)
    ok, msg = check_connection(engine)
    if not ok:
        logger.error("Cannot connect to database: %s", msg)
        return 3

    logger.info("Step 5/5: loading warehouse")
    run_id = load_warehouse(engine, result, args.raw_dir, quality_report=report.to_dict())
    db_checks = validate_database_reconciliation(engine)
    failed = [c for c in db_checks if c.status == FAIL]
    for c in db_checks:
        logger.info("[%s] %s - %s", c.status, c.name, c.message)
    if failed:
        logger.error("Database reconciliation failed for %d check(s); run_id=%s", len(failed), run_id)
        return 4
    logger.info("Done. etl_run_log.run_id=%s", run_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except DataFoundationError as exc:
        logging.basicConfig(level=logging.ERROR)
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
