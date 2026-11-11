"""Statistical tests on order-level facts.

Each test returns a dict with the statistic, p-value, an **effect size** and a plain-language
reading. With ~100k orders almost any difference is "significant", so the effect size (not the
p-value) decides whether a difference matters; the reading says so. Tests describe
association in 2016-2018 data and never establish cause. Several tests are run, so treat a lone
borderline p-value with caution (no multiple-comparison correction is applied; the effect sizes
are what the page leads with).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy.engine import Engine
from statsmodels.stats.proportion import proportion_confint

from analytics.base import Filters, order_scope, read_sql


def load_order_facts(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """Delivered orders with valid dates: review_score (may be NULL), is_late, delivery_days,
    freight_value, items_value, primary_payment_type, customer_state."""
    s = order_scope(f)
    return read_sql(
        engine,
        "SELECT o.order_id, r.review_score, o.is_late::int AS is_late, o.delivery_days, o.freight_value, o.items_value, "
        "o.primary_payment_type, o.customer_state\n"
        f"FROM {s.from_sql}\nLEFT JOIN vw_order_review r ON r.order_id = o.order_id\n"
        f"{s.where('o.has_valid_delivery_dates', "o.order_status = 'delivered'")}", s.params)


def _magnitude(v: float, small: float, medium: float, large: float) -> str:
    a = abs(v)
    return "negligible" if a < small else "small" if a < medium else "medium" if a < large else "large"


def _unavailable(name: str, reason: str) -> dict:
    return {"test": name, "available": False, "reason": reason}


def late_vs_review_score(df: pd.DataFrame) -> dict:
    """Mann-Whitney U: are review scores of late orders lower than those of on-time orders?
    Effect size: rank-biserial correlation (-1..1; |r| < 0.1 negligible, < 0.3 small, < 0.5 medium)."""
    d = df.dropna(subset=["review_score"])
    late, ok = d.loc[d["is_late"] == 1, "review_score"], d.loc[d["is_late"] == 0, "review_score"]
    if len(late) < 5 or len(ok) < 5:
        return _unavailable("Late vs on-time review score (Mann-Whitney U)", "Needs at least 5 reviewed orders in each group.")
    u, p = stats.mannwhitneyu(late, ok, alternative="two-sided")
    r = 1 - 2 * u / (len(late) * len(ok))        # rank-biserial for the 'late' group
    mag = _magnitude(r, 0.1, 0.3, 0.5)
    return {"test": "Late vs on-time review score (Mann-Whitney U)", "available": True, "statistic": float(u), "p_value": float(p),
            "effect_size": float(r), "effect_name": "rank-biserial correlation (positive = late orders score lower)", "magnitude": mag,
            "late_median": float(late.median()), "on_time_median": float(ok.median()), "late_mean": float(late.mean()),
            "on_time_mean": float(ok.mean()), "n_late": int(len(late)), "n_on_time": int(len(ok)),
            "reading": f"Late orders score {late.mean():.2f} on average vs {ok.mean():.2f} for on-time orders; the effect is {mag}"
                       f" (r = {r:.2f}). Association only: late orders may also differ in category, seller or region."}


def payment_vs_late(df: pd.DataFrame, min_group: int = 30) -> dict:
    """Chi-square test of independence between primary payment type and lateness (groups with fewer
    than ``min_group`` orders are dropped). Effect size: Cramér's V (< 0.1 negligible, < 0.3 small, < 0.5 medium)."""
    d = df.dropna(subset=["primary_payment_type"])
    counts = d["primary_payment_type"].value_counts()
    d = d[d["primary_payment_type"].isin(counts[counts >= min_group].index)]
    tab = pd.crosstab(d["primary_payment_type"], d["is_late"])
    if tab.shape[0] < 2 or tab.shape[1] < 2:
        return _unavailable("Payment type vs late delivery (chi-square)", "Needs two payment types and both outcomes.")
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    v = float(np.sqrt(chi2 / (tab.values.sum() * (min(tab.shape) - 1))))
    rates = (tab[1] / tab.sum(axis=1)).rename("late_rate").reset_index()
    mag = _magnitude(v, 0.1, 0.3, 0.5)
    return {"test": "Payment type vs late delivery (chi-square)", "available": True, "statistic": float(chi2), "p_value": float(p), "dof": int(dof),
            "effect_size": v, "effect_name": "Cramér's V", "magnitude": mag, "late_rate_by_payment": rates,
            "reading": f"Late rates differ by payment type with a {mag} effect (V = {v:.2f}). Payment type is probably a proxy for "
                       "something else (region, order value), not a cause of lateness."}


def freight_vs_delivery_time(df: pd.DataFrame) -> dict:
    """Spearman rank correlation between freight value and delivery days (|rho| < 0.1 negligible, < 0.3 small, < 0.5 medium)."""
    d = df.dropna(subset=["freight_value", "delivery_days"])
    if len(d) < 10:
        return _unavailable("Freight vs delivery time (Spearman)", "Needs at least 10 orders.")
    rho, p = stats.spearmanr(d["freight_value"], d["delivery_days"])
    mag = _magnitude(rho, 0.1, 0.3, 0.5)
    return {"test": "Freight vs delivery time (Spearman)", "available": True, "statistic": float(rho), "p_value": float(p),
            "effect_size": float(rho), "effect_name": "Spearman rho", "magnitude": mag, "n": int(len(d)),
            "reading": f"Higher freight goes with {'longer' if rho > 0 else 'shorter'} delivery times, a {mag} association (rho = {rho:.2f}). "
                       "Freight largely reflects distance and weight, so this is not freight causing delay."}


def state_vs_review_score(df: pd.DataFrame, min_group: int = 30) -> dict:
    """Kruskal-Wallis across customer states with at least ``min_group`` reviewed orders.
    Effect size: epsilon-squared (< 0.01 negligible, < 0.06 small, < 0.14 medium)."""
    d = df.dropna(subset=["review_score", "customer_state"])
    counts = d["customer_state"].value_counts()
    d = d[d["customer_state"].isin(counts[counts >= min_group].index)]
    groups = [g["review_score"].to_numpy() for _, g in d.groupby("customer_state")]
    if len(groups) < 2:
        return _unavailable("Review score across states (Kruskal-Wallis)", f"Needs two states with >= {min_group} reviewed orders.")
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    eps = float(h * (n + 1) / (n ** 2 - 1))
    mag = _magnitude(eps, 0.01, 0.06, 0.14)
    return {"test": "Review score across states (Kruskal-Wallis)", "available": True, "statistic": float(h), "p_value": float(p),
            "effect_size": eps, "effect_name": "epsilon-squared", "magnitude": mag, "states": len(groups), "n": int(n),
            "reading": f"Average review scores differ between {len(groups)} states with a {mag} effect (epsilon-squared = {eps:.3f})."}


def confidence_intervals(df: pd.DataFrame, confidence: float = 0.95) -> pd.DataFrame:
    """Confidence intervals for the late-delivery rate (Wilson) and the mean review score (t)."""
    rows = []
    if len(df):
        k, n = int(df["is_late"].sum()), len(df)
        lo, hi = proportion_confint(k, n, alpha=1 - confidence, method="wilson")
        rows.append({"metric": "Late-delivery rate", "estimate": k / n, "lower": float(lo), "upper": float(hi), "n": n, "method": "Wilson interval"})
    r = df["review_score"].dropna() if "review_score" in df else pd.Series(dtype=float)
    if len(r) >= 2 and r.std() > 0:
        lo, hi = stats.t.interval(confidence, len(r) - 1, loc=r.mean(), scale=stats.sem(r))
        lo, hi = max(float(lo), 1.0), min(float(hi), 5.0)          # the score scale is 1-5
        rows.append({"metric": "Average review score", "estimate": float(r.mean()), "lower": lo, "upper": hi, "n": len(r), "method": "t interval"})
    return pd.DataFrame(rows, columns=["metric", "estimate", "lower", "upper", "n", "method"])


def run_all_tests(df: pd.DataFrame) -> list[dict]:
    return [late_vs_review_score(df), payment_vs_late(df), freight_vs_delivery_time(df), state_vs_review_score(df)]
