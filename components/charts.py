"""Plotly chart builders + ``chart_card`` (title, chart, "View data" table, download).

Rules applied everywhere (dataviz skill): one y-axis (no dual axes), zero baseline
for bars, bars carry direct value labels, series colours come from the fixed
palette and follow the entity, and every chart has a "View data" table so the
numbers do not depend on colour perception.
"""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import theme
from components.tables import downloads
from config import settings

_HEIGHT = 360


def _base(fig: go.Figure, height: int = _HEIGHT) -> go.Figure:
    fig.update_layout(template="marketpulse", height=height, paper_bgcolor=theme.SURFACE, plot_bgcolor=theme.SURFACE)
    return fig


def line_fig(df: pd.DataFrame, x: str, series: dict[str, str], y_title: str = "", money: bool = False,
             colors: dict[str, str] | None = None, height: int = _HEIGHT) -> go.Figure:
    """Line chart; ``series`` maps legend label -> column. Gaps (NaN) stay gaps."""
    fig = go.Figure()
    for i, (label, col) in enumerate(series.items()):
        color = (colors or {}).get(label, theme.CATEGORICAL[i % len(theme.CATEGORICAL)])
        fig.add_scatter(x=df[x], y=df[col], name=label, mode="lines+markers" if len(df) <= 36 else "lines",
                        line=dict(color=color, width=2.5), marker=dict(size=6),
                        hovertemplate=f"%{{x}}<br>{label}: " + ("R$ %{y:,.2f}" if money else "%{y:,.2f}") + "<extra></extra>")
    fig.update_yaxes(title_text=y_title, tickprefix="R$ " if money else "")
    fig.update_layout(showlegend=len(series) > 1)
    return _base(fig, height)


def bar_fig(df: pd.DataFrame, category: str, value: str, horizontal: bool = True, money: bool = False,
            pct: bool = False, color: str | None = None, color_map: dict[str, str] | None = None,
            value_title: str = "", top: int | None = None, height: int | None = None) -> go.Figure:
    """Bar chart with direct value labels. Horizontal bars list the largest first."""
    d = df.head(top) if top else df
    fmt = "R$ %{x:,.0f}" if money else ("%{x:.1f}%" if pct else "%{x:,.2f}")
    text_fmt = "R$ %{x:,.0f}" if money else ("%{x:.1f}%" if pct else "%{x:,.4g}")
    colors = [color_map.get(str(c), theme.NEUTRAL) for c in d[category]] if color_map else (color or theme.BLUE)
    if horizontal:
        d = d.iloc[::-1]
        if color_map:
            colors = [color_map.get(str(c), theme.NEUTRAL) for c in d[category]]
        fig = go.Figure(go.Bar(x=d[value], y=d[category].astype(str), orientation="h", marker_color=colors,
                               text=d[value], texttemplate=text_fmt, textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}<br>" + fmt + "<extra></extra>"))
        fig.update_xaxes(title_text=value_title, showgrid=True, gridcolor=theme.GRID, tickprefix="R$ " if money else "")
        vmax = float(pd.to_numeric(d[value], errors="coerce").max())
        vmin = float(pd.to_numeric(d[value], errors="coerce").min())
        if vmax == vmax:                       # leave room for the outside value labels (not NaN)
            fig.update_xaxes(range=[min(0, vmin * 1.15), max(0, vmax) * 1.18])
        fig.update_yaxes(showgrid=False, ticks="", title_text="")
        h = height or max(260, 28 * len(d) + 70)
    else:
        fmt_y = fmt.replace("%{x", "%{y")
        fig = go.Figure(go.Bar(x=d[category].astype(str), y=d[value], marker_color=colors, text=d[value],
                               texttemplate=text_fmt.replace("%{x", "%{y"), textposition="outside", cliponaxis=False,
                               hovertemplate="%{x}<br>" + fmt_y + "<extra></extra>"))
        fig.update_yaxes(title_text=value_title, tickprefix="R$ " if money else "")
        h = height or _HEIGHT
    fig.update_layout(showlegend=False)
    return _base(fig, h)


def column_fig(df: pd.DataFrame, x: str, y: str, money: bool = False, y_title: str = "",
               color: str | None = None, height: int = _HEIGHT, labels: bool = True) -> go.Figure:
    """Vertical bars over an ordered axis (months, weekdays, scores)."""
    fig = go.Figure(go.Bar(x=df[x].astype(str), y=df[y], marker_color=color or theme.BLUE,
                           text=df[y] if labels else None, texttemplate="%{y:,.3s}" if labels else None,
                           textposition="outside", cliponaxis=False,
                           hovertemplate="%{x}<br>" + ("R$ %{y:,.2f}" if money else "%{y:,.2f}") + "<extra></extra>"))
    fig.update_yaxes(title_text=y_title, tickprefix="R$ " if money else "")
    fig.update_layout(showlegend=False)
    return _base(fig, height)


def histogram_fig(values: pd.Series, x_title: str, nbins: int = 40, height: int = _HEIGHT) -> go.Figure:
    fig = go.Figure(go.Histogram(x=values.dropna(), nbinsx=nbins, marker_color=theme.BLUE,
                                 hovertemplate=f"{x_title}: %{{x}}<br>Count: %{{y:,}}<extra></extra>"))
    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text="Count")
    fig.update_layout(bargap=0.05, showlegend=False)
    return _base(fig, height)


def scatter_fig(df: pd.DataFrame, x: str, y: str, label: str, size: str | None = None, x_title: str = "",
                y_title: str = "", x_ref: float | None = None, y_ref: float | None = None,
                height: int = 420) -> go.Figure:
    """Scatter with optional reference lines (e.g. medians) drawn as thin dashed lines."""
    sizes = None
    if size:
        s = df[size].astype(float)
        sizes = 8 + 24 * (s - s.min()) / ((s.max() - s.min()) or 1)
    fig = go.Figure(go.Scatter(x=df[x], y=df[y], mode="markers", text=df[label],
                               marker=dict(color=theme.BLUE, opacity=0.75, size=sizes if sizes is not None else 9,
                                           line=dict(color=theme.SURFACE, width=1)),
                               hovertemplate="%{text}<br>" + f"{x_title or x}: %{{x:,.2f}}<br>{y_title or y}: %{{y:,.2f}}<extra></extra>"))
    if x_ref is not None:
        fig.add_vline(x=x_ref, line=dict(color=theme.AXIS, dash="dash", width=1))
    if y_ref is not None:
        fig.add_hline(y=y_ref, line=dict(color=theme.AXIS, dash="dash", width=1))
    fig.update_xaxes(title_text=x_title or x, showgrid=True, gridcolor=theme.GRID)
    fig.update_yaxes(title_text=y_title or y)
    fig.update_layout(showlegend=False)
    return _base(fig, height)


def heatmap_fig(z: pd.DataFrame, z_title: str, height: int = 360) -> go.Figure:
    """Sequential single-hue heatmap; ``z`` is a pivoted frame (index = rows)."""
    ramp = [[i / (len(theme.SEQUENTIAL) - 1), c] for i, c in enumerate(theme.SEQUENTIAL)]
    fig = go.Figure(go.Heatmap(z=z.values, x=[str(c) for c in z.columns], y=[str(i) for i in z.index],
                               colorscale=ramp, colorbar=dict(title=z_title, outlinewidth=0),
                               hovertemplate="%{y} / %{x}<br>" + z_title + ": %{z:,.2f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", ticks="")
    return _base(fig, height)


@lru_cache(maxsize=1)
def _geojson() -> dict:
    return json.loads(settings.GEOJSON_STATES_PATH.read_text(encoding="utf-8"))


def choropleth_fig(df: pd.DataFrame, state_col: str, value_col: str, title: str, money: bool = False,
                   height: int = 520) -> go.Figure:
    """Brazil state map from the bundled offline GeoJSON (no internet needed)."""
    ramp = [[i / (len(theme.SEQUENTIAL) - 1), c] for i, c in enumerate(theme.SEQUENTIAL)]
    fig = go.Figure(go.Choroplethmap(
        geojson=_geojson(), locations=df[state_col], z=df[value_col], featureidkey="properties.sigla",
        colorscale=ramp, marker_line_color=theme.SURFACE, marker_line_width=0.8, marker_opacity=0.9,
        colorbar=dict(title=title, outlinewidth=0),
        hovertemplate="%{location}<br>" + title + ": " + ("R$ %{z:,.0f}" if money else "%{z:,.2f}") + "<extra></extra>"))
    # "white-bg" needs no map tiles, so the map works offline (no external requests).
    fig.update_layout(map=dict(style="white-bg", center=dict(lat=-14.2, lon=-52.0), zoom=2.9),
                      margin=dict(l=0, r=0, t=0, b=0))
    return _base(fig, height)


def chart_card(title: str, fig: go.Figure, data: pd.DataFrame | None, key: str, caption: str | None = None,
               help_text: str | None = None) -> None:
    """Bordered card: title, chart, optional caption and a "View data" table."""
    with st.container(border=True):
        st.markdown(f"**{title}**", help=help_text)
        if fig is None or (data is not None and data.empty):
            st.info("No data for the current filters.")
            return
        st.plotly_chart(fig, width="stretch", theme=None, key=f"chart_{key}", config={"displaylogo": False})
        if caption:
            st.caption(caption)
        if data is not None:
            with st.expander("View data"):
                st.dataframe(data, hide_index=True, width="stretch")
                downloads(data, key, f"dl_{key}")


def when(df: pd.DataFrame | None, build):
    """Build a figure only if ``df`` has rows (``chart_card`` shows the empty state)."""
    return build() if df is not None and not df.empty else None
