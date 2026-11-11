"""Tables with CSV / Excel download."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from reports.csv_exporter import export_filtered_results
from reports.excel_generator import dataframes_to_excel_bytes


def downloads(df: pd.DataFrame, name: str, key: str) -> None:
    """CSV (always) and Excel (up to ``EXCEL_EXPORT_MAX_ROWS`` rows) buttons."""
    fname, blob, mime = export_filtered_results(df, name)
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("Download CSV", blob, file_name=fname, mime=mime, key=f"{key}_csv", width="stretch")
    if len(df) <= settings.EXCEL_EXPORT_MAX_ROWS:
        c2.download_button("Download Excel", dataframes_to_excel_bytes({name[:31]: df}),
                           file_name=fname.replace(".csv", ".xlsx"),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"{key}_xlsx", width="stretch")


def data_table(df: pd.DataFrame, name: str, key: str, column_config: dict | None = None,
               height: int | None = None) -> None:
    """Sortable table plus downloads. Empty results show a message, never a blank grid."""
    if df is None or df.empty:
        st.info("No rows for the current filters.")
        return
    kw = {"height": height} if height else {}
    shown = df.copy()
    for c in shown.select_dtypes("float").columns:       # tidy display; downloads keep full precision
        shown[c] = shown[c].round(3)
    st.dataframe(shown, hide_index=True, width="stretch", column_config=column_config or {}, **kw)
    downloads(df, name, key)
