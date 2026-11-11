"""CSV export helpers (UTF-8 with BOM so Excel opens accented Portuguese text correctly)."""
from __future__ import annotations

import pandas as pd


def dataframe_to_csv_bytes(df: pd.DataFrame, index: bool = False) -> bytes:
    """Serialise a DataFrame to CSV bytes. An empty frame still yields its header row."""
    return df.to_csv(index=index).encode("utf-8-sig")


def export_filtered_results(df: pd.DataFrame, filename_stem: str) -> tuple[str, bytes, str]:
    """``(file_name, data, mime)`` ready for a download button."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in filename_stem).strip("_") or "export"
    return f"{safe}.csv", dataframe_to_csv_bytes(df), "text/csv"


def dataframes_to_zip_bytes(frames: "dict[str, pd.DataFrame]") -> bytes:
    """A zip with one CSV per DataFrame (names sanitised like ``export_filtered_results``)."""
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in frames.items():
            fname, blob, _ = export_filtered_results(df, name)
            z.writestr(fname, blob)
    return buf.getvalue()
