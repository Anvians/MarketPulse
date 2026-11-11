"""Cohort retention: of the customers who first bought in month M, what share bought again in month M+k?

A cohort is the month of a customer's first purchase **within the active filters**.
Retention at k = distinct customers with a revenue order in month M+k / cohort size
(k = 0 is 100% by definition; a second order in the same month is not counted as retention).
Cohorts smaller than ``COHORT_MIN_SIZE`` are returned with NaN retention: a percentage of
a handful of customers is noise. Observed history only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from analytics.base import Filters
from analytics.customers import _purchases
from config import settings


def build_cohort_table(purchases: pd.DataFrame, min_size: int = settings.COHORT_MIN_SIZE) -> pd.DataFrame:
    """Long table: cohort (YYYY-MM), months_since, customers, cohort_size, retention (fraction), is_small."""
    cols = ["cohort", "months_since", "customers", "cohort_size", "retention", "is_small"]
    if purchases.empty:
        return pd.DataFrame(columns=cols)
    ts = pd.to_datetime(purchases["purchase_ts"])
    df = pd.DataFrame({"c": purchases["customer_unique_id"].values, "m": ts.dt.to_period("M").values})
    first = df.groupby("c")["m"].min().rename("cohort")
    df = df.join(first, on="c")
    df["months_since"] = (df["m"] - df["cohort"]).map(lambda d: d.n)
    t = df.groupby(["cohort", "months_since"])["c"].nunique().rename("customers").reset_index()
    size = t[t["months_since"] == 0].set_index("cohort")["customers"].rename("cohort_size")
    t = t.join(size, on="cohort")
    t["is_small"] = t["cohort_size"] < min_size
    t["retention"] = np.where(t["is_small"], np.nan, t["customers"] / t["cohort_size"])
    t["cohort"] = t["cohort"].astype(str)
    return t[cols].sort_values(["cohort", "months_since"]).reset_index(drop=True)


def cohort_matrix(table: pd.DataFrame, max_months: int = 12) -> pd.DataFrame:
    """Pivot of retention % (rows cohorts, columns months since first purchase)."""
    if table.empty:
        return pd.DataFrame()
    m = table[table["months_since"] <= max_months].pivot(index="cohort", columns="months_since", values="retention") * 100
    return m


def calculate_cohort_retention(engine: Engine, f: Filters | None = None, min_size: int = settings.COHORT_MIN_SIZE) -> pd.DataFrame:
    return build_cohort_table(_purchases(engine, f), min_size)


def summarize_retention(table: pd.DataFrame, month: int = 1) -> dict:
    """Customer-weighted average retention at ``month`` over cohorts that are large enough and old
    enough to have reached it. ``None`` when no cohort qualifies. (Weighted by cohort size so a
    cohort of 200 does not count the same as one of 5,000.)"""
    if table.empty:
        return {"month": month, "retention": None, "cohorts_used": 0}
    k = table[(table["months_since"] == month) & ~table["is_small"]]
    # a cohort can only be judged at k if its calendar month M+k is not beyond the last month observed
    obs_end = max(pd.Period(c) + int(m) for c, m in zip(table["cohort"], table["months_since"]))
    k = k[[pd.Period(c) + month <= obs_end for c in k["cohort"]]]
    base = table[(table["months_since"] == 0) & ~table["is_small"]]
    base = base[[pd.Period(c) + month <= obs_end for c in base["cohort"]]]
    if base.empty:
        return {"month": month, "retention": None, "cohorts_used": 0}
    kept = k["customers"].sum()
    return {"month": month, "retention": float(kept / base["customers"].sum()), "cohorts_used": int(len(base))}
