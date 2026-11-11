"""KPI cards: every card gets the formula / denominator / null-handling tooltip
from ``config.kpi_definitions`` (a missing definition is an error, not a blank tooltip)."""
from __future__ import annotations

import streamlit as st

from config.kpi_definitions import get_definition


def kpi_card(container, key: str, value_text: str, label: str | None = None, delta: str | None = None,
             delta_color: str = "normal") -> None:
    d = get_definition(key)
    container.metric(label or d.label, value_text, delta=delta, delta_color=delta_color,
                     help=d.tooltip(), border=True)


def kpi_row(items: list[tuple], per_row: int = 4) -> None:
    """``items``: ``(key, value_text[, label[, delta]])`` tuples laid out in rows."""
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(per_row)
        for col, item in zip(cols, chunk):
            key, value = item[0], item[1]
            label = item[2] if len(item) > 2 else None
            delta = item[3] if len(item) > 3 else None
            kpi_card(col, key, value, label, delta)
