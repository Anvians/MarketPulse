"""Late-delivery risk model.

Question: given what is known **when the order is placed**, how likely is it to arrive after
the estimated delivery date? Features use only purchase-time information (no approval,
carrier or delivery timestamps, which would leak the outcome): customer and seller state,
whether they match, great-circle distance between zip-prefix centroids, item count and value,
freight, weight, volume, the estimated delivery time promised, main category, purchase month
and weekday.

Evaluation is a **time split** (oldest orders train, newest 25% test) so the model is judged on
a future it has not seen. Metrics are compared with the trivial baseline (every order gets the
overall late rate, AUC 0.5). ``Logistic regression`` is the transparent comparison model; the
gradient-boosted model is fixed in advance as the main model (no picking the winner on the test
set). ``usable`` is only True when the main model clearly beats the baseline; otherwise the
UI says the model is not informative. This is a risk score for prioritising checks, not a
guarantee, and it describes 2016-2018 logistics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy.engine import Engine

from analytics.base import Filters, order_scope, read_sql
from config import settings

NUMERIC = ["distance_km", "same_state", "item_count", "seller_count", "items_value", "freight_value", "freight_ratio",
           "total_weight_g", "max_volume_cm3", "estimated_delivery_days", "purchase_month", "purchase_weekday"]
CATEGORICAL = ["customer_state", "seller_state", "category"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "is_late"


def _haversine_km(lat1, lng1, lat2, lng2) -> np.ndarray:
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def load_delivery_dataset(engine: Engine, f: Filters | None = None) -> pd.DataFrame:
    """One row per delivered order with valid dates: purchase-time features + ``is_late``."""
    s = order_scope(f)
    sql = f"""
    WITH main_item AS (
        SELECT DISTINCT ON (order_id) order_id, seller_id, product_id
        FROM fact_order_items ORDER BY order_id, price DESC, order_item_id),
    agg AS (
        SELECT i.order_id, SUM(p.weight_g) AS total_weight_g, MAX(p.volume_cm3) AS max_volume_cm3
        FROM fact_order_items i LEFT JOIN dim_products p ON p.product_id = i.product_id GROUP BY i.order_id)
    SELECT o.order_id, o.purchase_ts, o.customer_state, sl.state AS seller_state, pr.category_en AS category,
           o.item_count, o.seller_count, o.items_value, o.freight_value, o.estimated_delivery_days,
           a.total_weight_g, a.max_volume_cm3,
           EXTRACT(MONTH FROM o.purchase_ts) AS purchase_month, EXTRACT(ISODOW FROM o.purchase_ts) AS purchase_weekday,
           gc.latitude AS c_lat, gc.longitude AS c_lng, gs.latitude AS s_lat, gs.longitude AS s_lng,
           o.is_late::int AS is_late
    FROM {s.from_sql}
    JOIN main_item m ON m.order_id = o.order_id
    LEFT JOIN dim_sellers sl ON sl.seller_id = m.seller_id
    LEFT JOIN dim_products pr ON pr.product_id = m.product_id
    LEFT JOIN agg a ON a.order_id = o.order_id
    LEFT JOIN dim_geolocation gc ON gc.zip_prefix = o.customer_zip_prefix
    LEFT JOIN dim_geolocation gs ON gs.zip_prefix = sl.zip_prefix
    {s.where("o.order_status = 'delivered'", 'o.has_valid_delivery_dates')}
    ORDER BY o.purchase_ts, o.order_id"""
    return prepare_features(read_sql(engine, sql, s.params))


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive distance, same_state and freight_ratio; keep the rarest categories as-is (the encoder groups them)."""
    d = df.copy()
    if d.empty:
        return d
    d["distance_km"] = _haversine_km(d["c_lat"], d["c_lng"], d["s_lat"], d["s_lng"])
    d["same_state"] = (d["customer_state"] == d["seller_state"]).astype(float)
    d["freight_ratio"] = d["freight_value"] / d["items_value"].replace(0, np.nan)
    for c in CATEGORICAL:
        d[c] = d[c].fillna("unknown").astype(str)
    return d


def _pipeline(model, scale: bool) -> Pipeline:
    num = [("imp", SimpleImputer(strategy="median"))] + ([("sc", StandardScaler())] if scale else [])
    pre = ColumnTransformer([
        ("num", Pipeline(num), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False), CATEGORICAL)])
    return Pipeline([("pre", pre), ("model", model)])


def train_delivery_risk_model(data: pd.DataFrame, min_orders: int = settings.DELIVERY_MODEL_MIN_ORDERS,
                              min_late: int = settings.DELIVERY_MODEL_MIN_LATE) -> dict:
    """Train on the oldest orders, evaluate on the newest. See the module docstring.

    Returns ``available`` (+ ``reason``), ``metrics`` (per model: roc_auc, average_precision, brier;
    plus ``base_rate`` and ``brier_baseline``), ``usable``, ``importance`` (permutation importance of
    the main model on the test set, drop in AUC), ``deciles`` (test late rate by predicted-risk decile)
    and ``model`` (fitted main pipeline, trained on the training part only)."""
    out = {"available": False, "reason": None, "usable": False, "metrics": {}, "importance": pd.DataFrame(), "deciles": pd.DataFrame(),
           "model": None, "n_train": 0, "n_test": 0}
    if len(data) < min_orders or int(data[TARGET].sum()) < min_late:
        out["reason"] = (f"Needs at least {min_orders} delivered orders with {min_late} late ones; the current filters give "
                         f"{len(data)} orders and {int(data[TARGET].sum()) if len(data) else 0} late.")
        return out
    d = data.sort_values("purchase_ts", kind="stable").reset_index(drop=True)
    cut = int(len(d) * (1 - settings.DELIVERY_TEST_FRACTION))
    train, test = d.iloc[:cut], d.iloc[cut:]
    if train[TARGET].nunique() < 2 or test[TARGET].nunique() < 2:
        out["reason"] = "Train or test period contains only one outcome class."
        return out
    ytr, yte = train[TARGET].to_numpy(), test[TARGET].to_numpy()
    base = float(ytr.mean())
    models = {
        "Logistic regression": _pipeline(LogisticRegression(max_iter=1000, class_weight=None), scale=True),
        "Gradient boosting": _pipeline(HistGradientBoostingClassifier(random_state=settings.ML_RANDOM_STATE, max_iter=200, learning_rate=0.08,
                                                                      early_stopping=True), scale=False),
    }
    metrics, probs = {}, {}
    for name, pipe in models.items():
        pipe.fit(train[FEATURES], ytr)
        p = pipe.predict_proba(test[FEATURES])[:, 1]
        probs[name] = p
        metrics[name] = {"roc_auc": float(roc_auc_score(yte, p)), "average_precision": float(average_precision_score(yte, p)),
                         "brier": float(brier_score_loss(yte, p))}
    metrics["Baseline (overall late rate)"] = {"roc_auc": 0.5, "average_precision": float(yte.mean()),
                                               "brier": float(brier_score_loss(yte, np.full(len(yte), base)))}
    main = "Gradient boosting"
    sample = test.sample(min(len(test), 5000), random_state=settings.ML_RANDOM_STATE)
    imp = permutation_importance(models[main], sample[FEATURES], sample[TARGET], scoring="roc_auc", n_repeats=3,
                                 random_state=settings.ML_RANDOM_STATE)
    importance = pd.DataFrame({"feature": FEATURES, "auc_drop": imp.importances_mean}).sort_values("auc_drop", ascending=False).reset_index(drop=True)
    dec = pd.DataFrame({"risk": probs[main], "late": yte})
    dec["decile"] = pd.qcut(dec["risk"].rank(method="first"), 10, labels=False) + 1
    deciles = dec.groupby("decile").agg(orders=("late", "size"), predicted_risk=("risk", "mean"), actual_late_rate=("late", "mean")).reset_index()
    m = metrics[main]
    usable = bool(m["roc_auc"] >= 0.60 and m["average_precision"] >= 1.2 * float(yte.mean()))
    out.update(available=True, usable=usable, metrics={**metrics, "base_rate_train": base, "base_rate_test": float(yte.mean()), "main_model": main},
               importance=importance, deciles=deciles, model=models[main], n_train=len(train), n_test=len(test),
               period={"train_from": str(train["purchase_ts"].min())[:10], "train_to": str(train["purchase_ts"].max())[:10],
                       "test_from": str(test["purchase_ts"].min())[:10], "test_to": str(test["purchase_ts"].max())[:10]})
    return out


def predict_risk(model: Pipeline, scenario: dict) -> float:
    """Late probability for one hypothetical order (dict of the FEATURES; missing numeric -> NaN -> imputed)."""
    row = pd.DataFrame([{c: scenario.get(c, np.nan) for c in FEATURES}])
    for c in CATEGORICAL:
        row[c] = row[c].fillna("unknown").astype(str)
    return float(model.predict_proba(row)[:, 1][0])
