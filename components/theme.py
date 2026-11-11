"""Visual theme: validated chart palette, Plotly template and page CSS.

The categorical palette is the dataviz reference palette (light mode), validated
with its validator: eight hues in a FIXED order (never cycled). Three slots sit
below 3:1 contrast on the chart surface, so every chart ships direct value labels
and a "View data" table (the palette's relief rule). Sequential encoding is one
hue (blue), light to dark. Status colours are not used for series.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---- palette (light) -------------------------------------------------------
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
NAVY = "#0d366b"
BLUE = CATEGORICAL[0]
ORANGE = CATEGORICAL[1]
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL = "#b9b7ae"          # "Other", missing, no-data

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Stable colour per entity (colour follows the entity, never its rank).
_ENTITY_ORDER = {
    "payment": ["credit_card", "boleto", "voucher", "debit_card"],
    "status": ["delivered", "shipped", "invoiced", "processing", "approved", "created", "canceled", "unavailable"],
    "segment": ["one_time", "repeat", "loyal"],
    "customer_kind": ["new", "returning"],
    "delivery": ["On time", "Late"],
    "quadrant": ["Star", "Fix quality", "Grow / promote", "Rethink", "Insufficient data"],
}


def entity_color(kind: str, name: str) -> str:
    """Fixed colour for a named entity of a known kind (neutral grey if unknown)."""
    order = _ENTITY_ORDER.get(kind, [])
    if name in order:
        idx = order.index(name)
        return NEUTRAL if (kind == "quadrant" and name == "Insufficient data") else CATEGORICAL[idx % len(CATEGORICAL)]
    return NEUTRAL


def _build_template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        colorway=CATEGORICAL,
        margin=dict(l=8, r=16, t=16, b=8),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=AXIS, tickcolor=AXIS, ticks="outside", ticklen=4,
                   title=dict(font=dict(color=MUTED, size=12)), tickfont=dict(color=MUTED), automargin=True),
        yaxis=dict(gridcolor=GRID, gridwidth=1, zeroline=False, showline=False, ticks="",
                   title=dict(font=dict(color=MUTED, size=12)), tickfont=dict(color=MUTED), automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color=INK_2)),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=AXIS, font=dict(family=FONT, color=INK, size=12)),
        bargap=0.35, barcornerradius=4,
    )
    return t


pio.templates["marketpulse"] = _build_template()
pio.templates.default = "marketpulse"

_CSS = """
<style>
/* page rhythm */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }
h1 { font-size: 1.9rem !important; letter-spacing: -0.01em; color: %(navy)s; margin-bottom: 0.1rem; }
h2, h3 { color: %(navy)s; letter-spacing: -0.005em; }
/* KPI cards (st.metric with border) */
[data-testid="stMetric"] { background: %(surface)s; border-radius: 12px; box-shadow: 0 1px 2px rgba(13,54,107,0.08); }
[data-testid="stMetricLabel"] p { font-size: 0.82rem; color: %(ink2)s; font-weight: 600; }
[data-testid="stMetricValue"] { font-size: 1.55rem; color: %(navy)s; font-weight: 700; }
/* bordered containers (chart cards) */
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
/* sidebar */
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a { border-radius: 8px; }
.mp-status { font-size: 0.8rem; line-height: 1.5; opacity: 0.92; }
.mp-status b { font-weight: 600; }
.mp-banner { background: %(seq1)s; color: %(navy)s; border-radius: 10px; padding: 0.45rem 0.8rem; font-size: 0.85rem; margin: 0.25rem 0 0.9rem 0; }
.mp-sub { color: %(ink2)s; margin-top: -0.2rem; margin-bottom: 0.6rem; }
</style>
""" % {"navy": NAVY, "surface": SURFACE, "ink2": INK_2, "seq1": SEQUENTIAL[0]}


def inject_css() -> None:
    """Add the app CSS (call once per run from app.py)."""
    st.markdown(_CSS, unsafe_allow_html=True)
