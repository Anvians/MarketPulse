"""Revenue forecast with an honest backtest.

Method: damped-trend exponential smoothing (statsmodels) on monthly product revenue of
**full months only** (sparse edge months are dropped, see ``base.flag_sparse_months``).
With ~2 years of data a seasonal model cannot be estimated reliably (needs >= 2 full
cycles), so none is used and seasonality is NOT modelled; the UI says so.

Every forecast is accompanied by a rolling-origin backtest: for each of the last N months
the model is refit on earlier months only and forecasts the next one. Its error is compared
with the naive rule "next month = this month". If the model does not beat the naive rule,
``beats_naive`` is False and the page says the forecast is no better than that.
Prediction intervals come from the spread of those backtest errors (approximate).
A forecast of historical data is an illustration of the method, not a statement about the
present business.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from analytics.base import Filters, flag_sparse_months, revenue_by
from config import settings


MIN_TRAIN_MONTHS = 9


def _fit_forecast(y: np.ndarray, steps: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y, trend="add", damped_trend=True, initialization_method="estimated").fit()
        return np.maximum(np.asarray(fit.forecast(steps)), 0.0)


def forecast_series(y: pd.Series, horizon: int = settings.FORECAST_HORIZON,
                    min_months: int = settings.FORECAST_MIN_MONTHS,
                    backtest_months: int = settings.FORECAST_BACKTEST_MONTHS) -> dict:
    """Forecast ``horizon`` months of ``y`` (index = 'YYYY-MM' strings, ascending, full months).

    Returns a dict: ``available``; ``reason`` when not; ``forecast`` (month, forecast, lower, upper);
    ``backtest`` (month, actual, model, naive); ``metrics`` (mae/mape of model and naive, ``beats_naive``)."""
    out = {"available": False, "reason": None, "forecast": pd.DataFrame(), "backtest": pd.DataFrame(), "metrics": {}, "n_months": int(len(y))}
    if len(y) < min_months:
        out["reason"] = f"Needs at least {min_months} full months of data; {len(y)} available for the current filters."
        return out
    vals = y.astype(float).to_numpy()
    n_bt = min(backtest_months, len(vals) - MIN_TRAIN_MONTHS)      # every backtest fit sees >= 9 months
    rows = []
    for t in range(len(vals) - n_bt, len(vals)):
        rows.append({"month": y.index[t], "actual": vals[t], "model": float(_fit_forecast(vals[:t], 1)[0]), "naive": vals[t - 1]})
    bt = pd.DataFrame(rows)
    err_m, err_n = bt["actual"] - bt["model"], bt["actual"] - bt["naive"]
    nz = bt["actual"] != 0
    metrics = {
        "mae_model": float(err_m.abs().mean()), "mae_naive": float(err_n.abs().mean()),
        "mape_model": float((err_m.abs() / bt["actual"])[nz].mean() * 100) if nz.any() else None,
        "mape_naive": float((err_n.abs() / bt["actual"])[nz].mean() * 100) if nz.any() else None,
        "backtest_months": int(len(bt)),
    }
    metrics["beats_naive"] = bool(metrics["mae_model"] < metrics["mae_naive"])
    sd = float(err_m.std(ddof=1)) if len(bt) > 1 else float(err_m.abs().mean())
    fc = _fit_forecast(vals, horizon)
    last = pd.Period(y.index[-1])
    months = [str(last + i) for i in range(1, horizon + 1)]
    width = 1.96 * sd * np.sqrt(np.arange(1, horizon + 1))
    out.update(available=True, backtest=bt, metrics=metrics,
               forecast=pd.DataFrame({"month": months, "forecast": fc, "lower": np.maximum(fc - width, 0.0), "upper": fc + width}))
    return out


def monthly_revenue_series(engine: Engine, f: Filters | None = None) -> pd.Series:
    """Full-month product revenue indexed by 'YYYY-MM' (sparse edge months removed)."""
    m = flag_sparse_months(revenue_by(engine, f, "month"))
    m = m[~m["is_sparse"]] if not m.empty else m
    return pd.Series(m["revenue"].astype(float).to_numpy(), index=m["year_month"].to_numpy(), name="revenue") if not m.empty else pd.Series(dtype=float)


def forecast_revenue(engine: Engine, f: Filters | None = None, horizon: int = settings.FORECAST_HORIZON, **kw) -> dict:
    """Forecast for the filters ``f`` (see :func:`forecast_series`); includes the ``history`` series."""
    y = monthly_revenue_series(engine, f)
    res = forecast_series(y, horizon, **kw)
    res["history"] = y.rename_axis("month").reset_index()
    return res
