"""Generate the reference docs that must never drift from the code.

    python -m scripts.generate_docs          # rewrites docs/KPI_REFERENCE.md and docs/THRESHOLDS.md

``tests/test_docs.py`` fails when the committed files differ from what this renders, so a KPI or
threshold change cannot ship without its documentation.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import settings
from config.kpi_definitions import KPI_DEFINITIONS

DOCS = settings.PROJECT_ROOT / "docs"


def render_kpi_reference() -> str:
    lines = ["# KPI reference", "",
             "Generated from `config/kpi_definitions.py` by `python -m scripts.generate_docs` (do not edit by hand). "
             "The same text is the tooltip on every KPI card. Revenue means product revenue (item prices on non-canceled orders "
             "with at least one item); it is not profit.", "",
             "| KPI | Formula | Denominator | Missing / empty data |", "|---|---|---|---|"]
    for d in KPI_DEFINITIONS.values():
        lines.append(f"| {d.label} | {d.formula} | {d.denominator} | {d.null_handling} |".replace("\n", " "))
    return "\n".join(lines) + "\n"


_CONST = re.compile(r"^([A-Z][A-Z0-9_]+)\s*(?::[^=]+)?=\s*(.+?)(?:\s+#\s*(.*))?$")


def render_thresholds() -> str:
    """Every business-rule constant in ``config/settings.py`` with its value and the comment beside it."""
    lines = ["# Rule thresholds", "",
             "Generated from `config/settings.py` by `python -m scripts.generate_docs` (do not edit by hand). "
             "These are analyst-chosen conventions, not statistically derived constants; change them in one place and re-run the tests.", "",
             "| Constant | Value | Meaning |", "|---|---|---|"]
    skip = {"PROJECT_ROOT", "RAW_DATA_DIR", "PROCESSED_DATA_DIR", "DATABASE_SQL_DIR", "RAW_FILES", "KAGGLE_DATASET_URL",
            "GEOJSON_STATES_PATH", "BRAZIL_REGIONS", "DATA_PERIOD_NOTICE"}
    for raw in Path(settings.__file__).read_text(encoding="utf-8").splitlines():
        m = _CONST.match(raw)
        if not m or m.group(1) in skip or not m.group(3):
            continue
        lines.append(f"| `{m.group(1)}` | `{m.group(2).strip()}` | {m.group(3).strip()} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "KPI_REFERENCE.md").write_text(render_kpi_reference(), encoding="utf-8")
    (DOCS / "THRESHOLDS.md").write_text(render_thresholds(), encoding="utf-8")
    print("wrote docs/KPI_REFERENCE.md and docs/THRESHOLDS.md")


if __name__ == "__main__":
    main()
