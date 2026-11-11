"""Cached access to the analytics layer.

The database engine is a cached resource; analytics results are cached by
(function, filters, arguments) for ``CACHE_TTL_SECONDS``. ``refresh()`` clears them.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable

import streamlit as st
from sqlalchemy.engine import Engine

from analytics.base import Filters
from config import settings
from config.database import check_connection, get_engine


@st.cache_resource(show_spinner=False)
def engine() -> Engine:
    """One pooled engine per server process (credentials come from DB_* env vars)."""
    return get_engine()


def database_ready() -> tuple[bool, str]:
    """(ok, message) - can we connect, and is the warehouse loaded?"""
    from analytics.system import warehouse_is_loaded

    try:
        ok, msg = check_connection(engine())
        if not ok:
            return False, msg
        if not warehouse_is_loaded(engine()):
            return False, "The database is reachable but empty. Run `python -m ingestion.run_pipeline` first."
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 - shown to the user, not swallowed
        return False, f"{type(exc).__name__}: {exc}"


@st.cache_data(ttl=settings.CACHE_TTL_SECONDS, show_spinner=False, max_entries=512)
def _cached(_engine: Engine, module: str, name: str, filters: Filters | None, args: tuple, kwargs: tuple) -> Any:
    fn = getattr(importlib.import_module(module), name)
    kw = dict(kwargs)
    if filters is None:
        return fn(_engine, *args, **kw)
    return fn(_engine, filters, *args, **kw)


def q(fn: Callable, filters: Filters | None = None, *args: Any, **kwargs: Any) -> Any:
    """Call ``fn(engine, [filters,] *args, **kwargs)`` with caching.

    Pass ``filters=None`` for functions that take no filters (system queries)."""
    return _cached(engine(), fn.__module__, fn.__name__, filters, args, tuple(sorted(kwargs.items())))


def refresh() -> None:
    """Drop every cached analytics result."""
    st.cache_data.clear()


@st.cache_data(ttl=settings.CACHE_TTL_SECONDS, show_spinner=False)
def filter_options() -> dict:
    from analytics.system import get_filter_options

    return get_filter_options(engine())
