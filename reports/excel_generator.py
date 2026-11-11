"""Excel export helpers (openpyxl)."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

_MAX_SHEET_NAME = 31
_FORBIDDEN = set('[]:*?/\\')


def _sheet_name(name: str, used: set[str]) -> str:
    base = "".join("_" if ch in _FORBIDDEN else ch for ch in name)[:_MAX_SHEET_NAME] or "Sheet"
    candidate, n = base, 2
    while candidate in used:
        suffix = f"_{n}"
        candidate = base[: _MAX_SHEET_NAME - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate


def dataframes_to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """One worksheet per DataFrame (names sanitised and de-duplicated), as .xlsx bytes."""
    if not sheets:
        raise ValueError("At least one DataFrame is required to build a workbook")
    buffer = BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            out = df.copy()
            for col in out.columns:   # Excel cannot store timezone-aware datetimes
                if pd.api.types.is_datetime64_any_dtype(out[col]) and getattr(out[col].dt, "tz", None) is not None:
                    out[col] = out[col].dt.tz_localize(None)
            out.to_excel(writer, sheet_name=_sheet_name(name, used), index=False)
    return buffer.getvalue()
