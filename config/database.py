"""Database connection helpers (SQLAlchemy + psycopg 3)."""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

from config.settings import DatabaseSettings
from ingestion.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)


def build_url(settings: DatabaseSettings) -> URL:
    """Build a SQLAlchemy URL. Using URL.create keeps special characters in the
    password safe (no manual string formatting)."""
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.user,
        password=settings.password or None,
        host=settings.host,
        port=settings.port,
        database=settings.name,
    )


def get_engine(settings: DatabaseSettings | None = None) -> Engine:
    """Create an engine. Connections are verified lazily, so call
    :func:`check_connection` to test reachability."""
    settings = settings or DatabaseSettings.from_env()
    return create_engine(build_url(settings), pool_pre_ping=True, future=True)


def check_connection(engine: Engine) -> tuple[bool, str]:
    """Return ``(ok, message)``; never raises for connection problems."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
        return True, str(version)
    except SQLAlchemyError as exc:
        return False, f"{type(exc).__name__}: {str(exc.__cause__ or exc).splitlines()[0]}"


def ensure_database_exists(settings: DatabaseSettings) -> bool:
    """Create the target database if missing. Returns True if it was created.

    Connects to the maintenance database ``postgres`` with autocommit because
    CREATE DATABASE cannot run inside a transaction.
    """
    try:
        with psycopg.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password or None,
            dbname="postgres",
            autocommit=True,
        ) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (settings.name,)
            ).fetchone()
            if exists:
                return False
            # Identifiers cannot be parameterised; quote safely via psycopg.sql.
            from psycopg import sql

            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.name)))
            logger.info("Created database %s", settings.name)
            return True
    except psycopg.Error as exc:
        raise DatabaseConnectionError(
            f"Cannot connect to PostgreSQL at {settings.host}:{settings.port} "
            f"as {settings.user!r}: {exc}"
        ) from exc


def run_sql_file(engine: Engine, path: Path) -> None:
    """Execute a multi-statement SQL script atomically."""
    if not path.exists():
        raise FileNotFoundError(f"SQL script not found: {path}")
    script = path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(script)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    logger.info("Executed %s", path.name)
