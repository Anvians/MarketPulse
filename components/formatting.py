"""Number formatting for the UI. ``None`` / NaN always renders as ``n/a``."""
from __future__ import annotations

import math

from config import settings

NA = "n/a"


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def number(v, digits: int = 0) -> str:
    """Integer-style number with thousands separators."""
    return NA if _missing(v) else f"{v:,.{digits}f}"


def money(v, compact: bool = False, digits: int = 2) -> str:
    """Amount in reais. ``compact`` abbreviates large values (R$ 13.49M)."""
    if _missing(v):
        return NA
    sign = "-" if v < 0 else ""
    a = abs(float(v))
    if compact and a >= 1e6:
        return f"{sign}{settings.CURRENCY_SYMBOL} {a / 1e6:,.2f}M"
    if compact and a >= 1e4:
        return f"{sign}{settings.CURRENCY_SYMBOL} {a / 1e3:,.1f}K"
    return f"{sign}{settings.CURRENCY_SYMBOL} {a:,.{digits}f}"


def pct(v, digits: int = 1) -> str:
    """A FRACTION (0.034) as a percentage ('3.4%')."""
    return NA if _missing(v) else f"{100 * float(v):.{digits}f}%"


def pct_points(v, digits: int = 1, signed: bool = False) -> str:
    """A value that is ALREADY a percentage (12.5 -> '12.5%')."""
    if _missing(v):
        return NA
    return f"{float(v):+.{digits}f}%" if signed else f"{float(v):.{digits}f}%"


def days(v, digits: int = 1) -> str:
    return NA if _missing(v) else f"{float(v):.{digits}f} days"


def score(v, digits: int = 2) -> str:
    return NA if _missing(v) else f"{float(v):.{digits}f} / 5"


def text(v) -> str:
    return NA if _missing(v) else str(v)
