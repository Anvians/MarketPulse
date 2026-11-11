"""Customer segmentation: rule-based RFM segments and k-means clusters.

* A customer is a person (``customer_unique_id``); only revenue orders count.
* The reference date for recency is **the day after the last purchase in scope**,
  never today's date (the data is historical, so "days since last purchase"
  measured from today would be meaningless).
* Olist customers rarely buy twice (frequency is 1 for ~97%), so quintile scoring
  of frequency would be degenerate. Frequency is scored 1 / 2 / 3 for 1 / 2 / 3+ orders.
* Segment rules are listed in ``SEGMENT_RULES`` and shown in the UI. K-means is a
  complementary, data-driven view; its clusters are numbered and described only by
  their measured averages (no invented persona names).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy.engine import Engine

from analytics.base import Filters
from analytics.customers import _purchases
from config import settings

SEGMENT_RULES: list[tuple[str, str]] = [
    ("Active repeat", "2+ orders and recency score >= 4 (bought recently)"),
    ("Lapsed repeat", "2+ orders and recency score < 4"),
    ("High-value recent", "1 order, recency score >= 4 and monetary score >= 4"),
    ("New / recent", "1 order, recency score >= 4 and monetary score < 4"),
    ("High-value inactive", "1 order, recency score < 4 and monetary score >= 4"),
    ("Inactive one-time", "1 order, recency score < 4 and monetary score < 4"),
]
SEGMENT_ORDER = [name for name, _ in SEGMENT_RULES]


def _quantile_score(values: pd.Series, bins: int, ascending: bool = True) -> pd.Series:
    """1..bins score by rank (ties broken by order, so bins are equal-sized even when
    many customers share a value). ``ascending=True`` gives larger values higher scores."""
    ranks = values.rank(method="first", ascending=ascending)
    n = len(values)
    return (np.ceil(ranks * bins / n)).clip(1, bins).astype(int)


def build_rfm_table(purchases: pd.DataFrame, bins: int = settings.RFM_BINS) -> pd.DataFrame:
    """RFM table from one-row-per-order ``purchases`` (customer_unique_id, purchase_ts, revenue).

    Columns: customer_unique_id, recency_days, frequency, monetary, r_score, f_score,
    m_score, segment. Empty input gives an empty frame with these columns."""
    cols = ["customer_unique_id", "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score", "segment"]
    if purchases.empty:
        return pd.DataFrame(columns=cols)
    ts = pd.to_datetime(purchases["purchase_ts"])
    ref = ts.max().normalize() + pd.Timedelta(days=1)
    g = purchases.assign(purchase_ts=ts).groupby("customer_unique_id").agg(
        last=("purchase_ts", "max"), frequency=("revenue", "size"), monetary=("revenue", "sum")).reset_index()
    g["recency_days"] = (ref - g["last"].dt.normalize()).dt.days
    g["r_score"] = _quantile_score(g["recency_days"], bins, ascending=False)   # recent = high
    g["m_score"] = _quantile_score(g["monetary"], bins, ascending=True)
    g["f_score"] = g["frequency"].clip(upper=3).astype(int)
    hi = settings.RFM_HIGH_SCORE
    repeat, recent, valuable = g["frequency"] >= 2, g["r_score"] >= hi, g["m_score"] >= hi
    g["segment"] = np.select(
        [repeat & recent, repeat, ~repeat & recent & valuable, ~repeat & recent, ~repeat & valuable],
        SEGMENT_ORDER[:5], default=SEGMENT_ORDER[5])
    return g[cols]


def summarize_segments(rfm: pd.DataFrame) -> pd.DataFrame:
    """Per segment: customers, customer share, revenue, revenue share, averages. All segments listed."""
    cols = ["segment", "customers", "customer_share_pct", "revenue", "revenue_share_pct",
            "avg_recency_days", "avg_frequency", "avg_monetary"]
    if rfm.empty:
        return pd.DataFrame(columns=cols)
    g = rfm.groupby("segment").agg(customers=("customer_unique_id", "size"), revenue=("monetary", "sum"),
                                   avg_recency_days=("recency_days", "mean"), avg_frequency=("frequency", "mean"),
                                   avg_monetary=("monetary", "mean")).reindex(SEGMENT_ORDER).fillna(0).reset_index()
    g["customer_share_pct"] = 100 * g["customers"] / g["customers"].sum()
    g["revenue_share_pct"] = 100 * g["revenue"] / g["revenue"].sum() if g["revenue"].sum() else np.nan
    return g[cols]


def cluster_customers(rfm: pd.DataFrame, k: int | None = None) -> dict:
    """K-means on log-scaled, standardised R, F and M.

    ``k`` is chosen by the best silhouette score within ``KMEANS_K_RANGE`` when not given
    (silhouette computed on a seeded sample for speed). Returns ``table`` (rfm + ``cluster``),
    ``profile`` (per-cluster size and averages), ``k``, ``silhouette`` and ``scores`` (silhouette
    per tried k). ``available`` is False when there are too few customers or no variation."""
    out = {"available": False, "table": rfm.assign(cluster=pd.Series(dtype=int)), "profile": pd.DataFrame(), "k": None,
           "silhouette": None, "scores": {}}
    lo, hi = settings.KMEANS_K_RANGE
    if len(rfm) < max(50, hi * 10):
        return out
    x = np.column_stack([np.log1p(rfm["recency_days"]), np.log1p(rfm["frequency"]), np.log1p(rfm["monetary"])])
    if np.allclose(x.std(axis=0), 0):
        return out
    x = StandardScaler().fit_transform(x)
    rng = np.random.default_rng(settings.ML_RANDOM_STATE)
    idx = rng.choice(len(x), size=min(len(x), settings.SILHOUETTE_SAMPLE), replace=False)
    scores: dict[int, float] = {}
    for kk in ([k] if k else range(lo, hi + 1)):
        labels = KMeans(n_clusters=kk, n_init=10, random_state=settings.ML_RANDOM_STATE).fit_predict(x)
        if len(set(labels[idx])) > 1:
            scores[kk] = float(silhouette_score(x[idx], labels[idx]))
    if not scores:
        return out
    best = k or max(scores, key=scores.get)
    labels = KMeans(n_clusters=best, n_init=10, random_state=settings.ML_RANDOM_STATE).fit_predict(x)
    table = rfm.assign(cluster=labels + 1)
    prof = table.groupby("cluster").agg(customers=("customer_unique_id", "size"), avg_recency_days=("recency_days", "mean"),
                                        avg_frequency=("frequency", "mean"), avg_monetary=("monetary", "mean"),
                                        revenue=("monetary", "sum")).reset_index()
    prof["customer_share_pct"] = 100 * prof["customers"] / prof["customers"].sum()
    prof["revenue_share_pct"] = 100 * prof["revenue"] / prof["revenue"].sum()
    return {"available": True, "table": table, "profile": prof, "k": int(best), "silhouette": scores[best], "scores": scores}


def calculate_rfm(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """RFM table for the customers with a revenue order in the filters."""
    return build_rfm_table(_purchases(engine, f))
