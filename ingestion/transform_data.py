"""Clean raw Olist tables and build the star-schema DataFrames.

Every transformation that changes, drops or derives data is recorded in a
:class:`TransformLog` so that nothing happens silently (project requirement:
"document every transformation").

Key modelling decisions (also documented in data/DATA_DICTIONARY.md):

* ``customer_id`` is generated per order in Olist; people are identified by
  ``customer_unique_id``. dim_customers is keyed on the latter.
* ``fact_orders`` has one row per order with item/payment totals pre-aggregated,
  so order-level KPIs never join to a one-to-many table.
* Revenue = sum(item price) on *revenue orders* (status not canceled /
  unavailable and at least one item). Freight is kept separate.
* Delivery lateness compares DATES: delivered date <= estimated date is on time.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from config import settings
from ingestion.exceptions import EmptyDatasetError, TransformationError

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ logging
@dataclass
class TransformStep:
    table: str
    step: str
    rows_before: int
    rows_after: int
    detail: str = ""


class TransformLog:
    """Ordered record of every transformation applied."""

    def __init__(self) -> None:
        self.steps: list[TransformStep] = []

    def add(self, table: str, step: str, before: int, after: int, detail: str = "") -> None:
        self.steps.append(TransformStep(table, step, int(before), int(after), detail))
        logger.info("%s | %s | %d -> %d %s", table, step, before, after, detail)

    def to_frame(self) -> pd.DataFrame:
        cols = ["table", "step", "rows_before", "rows_after", "detail"]
        return pd.DataFrame([asdict(s) for s in self.steps], columns=cols)


@dataclass
class TransformResult:
    tables: dict[str, pd.DataFrame]
    log: TransformLog


# ------------------------------------------------------------------ helpers
def _ids(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip()
    return out.mask(out == "")


def _lower(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.lower()
    return out.mask(out == "")


def _upper(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.upper()
    return out.mask(out == "")


def _zip(s: pd.Series) -> pd.Series:
    """Zip prefixes are text (leading zeros matter); normalise to 5 digits."""
    z = s.astype("string").str.strip().str.replace(r"\D", "", regex=True)
    z = z.mask(z == "")
    return z.str.zfill(5)


def _text(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip()
    return out.mask(out == "")


def _datetime(s: pd.Series, table: str, column: str, log: TransformLog) -> pd.Series:
    parsed = pd.to_datetime(s, errors="coerce")
    bad = int((s.notna() & parsed.isna()).sum())
    if bad:
        log.add(table, f"invalid {column} set to NULL", len(s), len(s), f"{bad} unparseable values")
    return parsed


def _number(s: pd.Series, table: str, column: str, log: TransformLog) -> pd.Series:
    parsed = pd.to_numeric(s, errors="coerce")
    bad = int((s.notna() & parsed.isna()).sum())
    if bad:
        log.add(table, f"non-numeric {column} set to NULL", len(s), len(s), f"{bad} values")
    return parsed


def _dedupe(df: pd.DataFrame, subset: list[str], table: str, log: TransformLog,
            keep: str = "first") -> pd.DataFrame:
    before = len(df)
    out = df.drop_duplicates(subset=subset, keep=keep)
    if len(out) != before:
        log.add(table, f"dropped duplicate rows on {subset}", before, len(out))
    return out.reset_index(drop=True)


def _drop_null_keys(df: pd.DataFrame, cols: list[str], table: str, log: TransformLog) -> pd.DataFrame:
    before = len(df)
    out = df.dropna(subset=cols)
    if len(out) != before:
        log.add(table, f"dropped rows with NULL key {cols}", before, len(out))
    return out.reset_index(drop=True)


def _date_key(ts: pd.Series) -> pd.Series:
    key = ts.dt.year * 10000 + ts.dt.month * 100 + ts.dt.day
    return key.astype("Int64")


# ------------------------------------------------------------ table cleaners
def clean_customers(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "customer_id": _ids(df["customer_id"]),
        "customer_unique_id": _ids(df["customer_unique_id"]),
        "zip_prefix": _zip(df["customer_zip_code_prefix"]),
        "city": _lower(df["customer_city"]),
        "state": _upper(df["customer_state"]),
    })
    out = _drop_null_keys(out, ["customer_id", "customer_unique_id"], "customers", log)
    return _dedupe(out, ["customer_id"], "customers", log)


def clean_orders(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "order_id": _ids(df["order_id"]),
        "customer_id": _ids(df["customer_id"]),
        "order_status": _lower(df["order_status"]),
        "purchase_ts": _datetime(df["order_purchase_timestamp"], "orders", "order_purchase_timestamp", log),
        "approved_ts": _datetime(df["order_approved_at"], "orders", "order_approved_at", log),
        "carrier_delivery_ts": _datetime(df["order_delivered_carrier_date"], "orders", "order_delivered_carrier_date", log),
        "customer_delivery_ts": _datetime(df["order_delivered_customer_date"], "orders", "order_delivered_customer_date", log),
        "estimated_delivery_date": _datetime(df["order_estimated_delivery_date"], "orders", "order_estimated_delivery_date", log).dt.normalize(),
    })
    out = _drop_null_keys(out, ["order_id", "customer_id", "order_status"], "orders", log)
    return _dedupe(out, ["order_id"], "orders", log)


def clean_order_items(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "order_id": _ids(df["order_id"]),
        "order_item_id": _number(df["order_item_id"], "order_items", "order_item_id", log),
        "product_id": _ids(df["product_id"]),
        "seller_id": _ids(df["seller_id"]),
        "shipping_limit_ts": _datetime(df["shipping_limit_date"], "order_items", "shipping_limit_date", log),
        "price": _number(df["price"], "order_items", "price", log),
        "freight_value": _number(df["freight_value"], "order_items", "freight_value", log),
    })
    out = _drop_null_keys(
        out, ["order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value"],
        "order_items", log,
    )
    before = len(out)
    out = out[(out["price"] >= 0) & (out["freight_value"] >= 0)]
    if len(out) != before:
        log.add("order_items", "dropped rows with negative price/freight", before, len(out))
    out = out.assign(order_item_id=out["order_item_id"].astype("int64"))
    return _dedupe(out, ["order_id", "order_item_id"], "order_items", log)


def clean_payments(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "order_id": _ids(df["order_id"]),
        "payment_sequential": _number(df["payment_sequential"], "payments", "payment_sequential", log),
        "payment_type": _lower(df["payment_type"]),
        "payment_installments": _number(df["payment_installments"], "payments", "payment_installments", log),
        "payment_value": _number(df["payment_value"], "payments", "payment_value", log),
    })
    out = _drop_null_keys(out, ["order_id", "payment_sequential", "payment_type", "payment_value"], "payments", log)
    before = len(out)
    out = out[out["payment_value"] >= 0]
    if len(out) != before:
        log.add("payments", "dropped rows with negative payment_value", before, len(out))
    out = out.assign(
        payment_sequential=out["payment_sequential"].astype("int64"),
        payment_installments=out["payment_installments"].astype("Int64"),
    )
    return _dedupe(out, ["order_id", "payment_sequential"], "payments", log)


def clean_reviews(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "review_id": _ids(df["review_id"]),
        "order_id": _ids(df["order_id"]),
        "review_score": _number(df["review_score"], "reviews", "review_score", log),
        "review_comment_title": _text(df["review_comment_title"]),
        "review_comment_message": _text(df["review_comment_message"]),
        "review_creation_ts": _datetime(df["review_creation_date"], "reviews", "review_creation_date", log),
        "review_answer_ts": _datetime(df["review_answer_timestamp"], "reviews", "review_answer_timestamp", log),
    })
    out = _drop_null_keys(out, ["review_id", "order_id", "review_score"], "reviews", log)
    lo, hi = settings.REVIEW_SCORE_RANGE
    before = len(out)
    valid = out["review_score"].between(lo, hi) & (out["review_score"] == out["review_score"].round())
    out = out[valid]
    if len(out) != before:
        log.add("reviews", f"dropped rows with review_score outside {lo}-{hi}", before, len(out))
    out = out.assign(review_score=out["review_score"].astype("int64"))
    # Keep the most recently answered record for each (review_id, order_id).
    out = out.sort_values(["review_answer_ts", "review_creation_ts"], na_position="first")
    return _dedupe(out, ["review_id", "order_id"], "reviews", log, keep="last")


def clean_products(df: pd.DataFrame, translation: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    tr = pd.DataFrame({
        "category_pt": _lower(translation["product_category_name"]),
        "category_en": _lower(translation["product_category_name_english"]),
    }).dropna()
    tr = _dedupe(tr, ["category_pt"], "category_translation", log)

    out = pd.DataFrame({
        "product_id": _ids(df["product_id"]),
        "category_pt": _lower(df["product_category_name"]),
        "name_length": _number(df["product_name_lenght"], "products", "product_name_lenght", log),
        "description_length": _number(df["product_description_lenght"], "products", "product_description_lenght", log),
        "photos_qty": _number(df["product_photos_qty"], "products", "product_photos_qty", log),
        "weight_g": _number(df["product_weight_g"], "products", "product_weight_g", log),
        "length_cm": _number(df["product_length_cm"], "products", "product_length_cm", log),
        "height_cm": _number(df["product_height_cm"], "products", "product_height_cm", log),
        "width_cm": _number(df["product_width_cm"], "products", "product_width_cm", log),
    })
    out = _drop_null_keys(out, ["product_id"], "products", log)
    out = _dedupe(out, ["product_id"], "products", log)

    for col in ("name_length", "description_length", "photos_qty"):
        out[col] = out[col].round().astype("Int64")
    for col in ("weight_g", "length_cm", "height_cm", "width_cm"):
        negative = out[col] < 0
        if negative.any():
            log.add("products", f"negative {col} set to NULL", len(out), len(out), f"{int(negative.sum())} values")
            out.loc[negative, col] = np.nan

    out = out.merge(tr, on="category_pt", how="left")
    untranslated = out["category_en"].isna() & out["category_pt"].notna()
    if untranslated.any():
        names = sorted(out.loc[untranslated, "category_pt"].dropna().unique())
        log.add(
            "products", "category without English translation: kept Portuguese name",
            len(out), len(out), f"{len(names)} categories: {', '.join(names)}",
        )
    out["category_en"] = out["category_en"].fillna(out["category_pt"])
    no_category = out["category_en"].isna()
    if no_category.any():
        log.add("products", "missing category labelled 'unknown'", len(out), len(out), f"{int(no_category.sum())} products")
    out["category_en"] = out["category_en"].fillna("unknown")

    out["volume_cm3"] = out["length_cm"] * out["height_cm"] * out["width_cm"]
    return out


def clean_sellers(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    out = pd.DataFrame({
        "seller_id": _ids(df["seller_id"]),
        "zip_prefix": _zip(df["seller_zip_code_prefix"]),
        "city": _lower(df["seller_city"]),
        "state": _upper(df["seller_state"]),
    })
    out = _drop_null_keys(out, ["seller_id"], "sellers", log)
    return _dedupe(out, ["seller_id"], "sellers", log)


def build_dim_geolocation(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    """Collapse the many-rows-per-prefix raw file to one row per zip prefix."""
    g = pd.DataFrame({
        "zip_prefix": _zip(df["geolocation_zip_code_prefix"]),
        "lat": pd.to_numeric(df["geolocation_lat"], errors="coerce"),
        "lng": pd.to_numeric(df["geolocation_lng"], errors="coerce"),
        "city": _lower(df["geolocation_city"]),
        "state": _upper(df["geolocation_state"]),
    })
    before = len(g)
    g = g.dropna(subset=["zip_prefix", "lat", "lng"])
    if len(g) != before:
        log.add("geolocation", "dropped rows with NULL zip/lat/lng", before, len(g))

    lat_lo, lat_hi = settings.BRAZIL_LAT_RANGE
    lng_lo, lng_hi = settings.BRAZIL_LNG_RANGE
    before = len(g)
    g = g[g["lat"].between(lat_lo, lat_hi) & g["lng"].between(lng_lo, lng_hi)]
    if len(g) != before:
        log.add("geolocation", "dropped coordinates outside Brazil bounding box", before, len(g))

    if g.empty:
        raise EmptyDatasetError("geolocation has no usable rows after cleaning")

    coords = g.groupby("zip_prefix").agg(
        latitude=("lat", "mean"), longitude=("lng", "mean"), source_row_count=("lat", "size")
    )

    def modal(col: str) -> pd.Series:
        counts = (
            g.dropna(subset=[col]).groupby(["zip_prefix", col]).size().reset_index(name="n")
            .sort_values(["zip_prefix", "n", col], ascending=[True, False, True])
            .drop_duplicates("zip_prefix")
        )
        return counts.set_index("zip_prefix")[col]

    out = coords.join(modal("city").rename("city")).join(modal("state").rename("state"))
    out = out.reset_index()
    log.add(
        "geolocation", "aggregated to one row per zip prefix (mean lat/lng, modal city/state)",
        len(g), len(out),
    )
    return out[["zip_prefix", "latitude", "longitude", "city", "state", "source_row_count"]]


# ------------------------------------------------------- referential cleaning
def _keep_known(df: pd.DataFrame, col: str, valid: pd.Series, table: str,
                parent: str, log: TransformLog) -> pd.DataFrame:
    before = len(df)
    out = df[df[col].isin(valid)]
    if len(out) != before:
        log.add(table, f"dropped orphan rows (no matching {parent})", before, len(out))
    return out.reset_index(drop=True)


def ensure_dimension_members(
    items: pd.DataFrame, products: pd.DataFrame, sellers: pd.DataFrame, log: TransformLog
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add id-only 'unknown' members for products/sellers referenced by items but
    absent from their dimension, so revenue is never silently dropped."""
    missing_p = sorted(set(items["product_id"]) - set(products["product_id"]))
    if missing_p:
        add = pd.DataFrame({"product_id": missing_p})
        for col in products.columns:
            if col not in add:
                add[col] = pd.NA
        add["category_en"] = "unknown"
        products = pd.concat([products, add[products.columns]], ignore_index=True)
        log.add("products", "added 'unknown' members for products referenced by items",
                len(products) - len(missing_p), len(products), f"{len(missing_p)} products")
    missing_s = sorted(set(items["seller_id"]) - set(sellers["seller_id"]))
    if missing_s:
        add = pd.DataFrame({"seller_id": missing_s})
        for col in sellers.columns:
            if col not in add:
                add[col] = pd.NA
        sellers = pd.concat([sellers, add[sellers.columns]], ignore_index=True)
        log.add("sellers", "added 'unknown' members for sellers referenced by items",
                len(sellers) - len(missing_s), len(sellers), f"{len(missing_s)} sellers")
    return products, sellers


# ------------------------------------------------------------------ builders
def build_fact_orders(
    orders: pd.DataFrame, customers: pd.DataFrame, items: pd.DataFrame,
    payments: pd.DataFrame, log: TransformLog,
) -> pd.DataFrame:
    """One row per order with pre-aggregated item/payment totals and delivery metrics."""
    cust = customers.rename(columns={
        "zip_prefix": "customer_zip_prefix", "city": "customer_city", "state": "customer_state",
    })
    fo = orders.merge(cust, on="customer_id", how="left", validate="many_to_one")

    item_agg = items.groupby("order_id").agg(
        item_count=("order_item_id", "size"),
        seller_count=("seller_id", "nunique"),
        items_value=("price", "sum"),
        freight_value=("freight_value", "sum"),
    ).reset_index()
    fo = fo.merge(item_agg, on="order_id", how="left", validate="one_to_one")
    for col in ("item_count", "seller_count"):
        fo[col] = fo[col].fillna(0).astype("int64")
    for col in ("items_value", "freight_value"):
        fo[col] = fo[col].fillna(0.0).round(2)
    fo["order_total_value"] = (fo["items_value"] + fo["freight_value"]).round(2)

    pay_agg = payments.groupby("order_id").agg(
        payment_value=("payment_value", "sum"),
        payment_count=("payment_sequential", "size"),
        max_installments=("payment_installments", "max"),
    ).reset_index()
    pay_agg["payment_value"] = pay_agg["payment_value"].round(2)
    primary = (
        payments.sort_values(["order_id", "payment_value", "payment_sequential"],
                             ascending=[True, False, True])
        .drop_duplicates("order_id")[["order_id", "payment_type"]]
        .rename(columns={"payment_type": "primary_payment_type"})
    )
    fo = fo.merge(pay_agg, on="order_id", how="left", validate="one_to_one")
    fo = fo.merge(primary, on="order_id", how="left", validate="one_to_one")
    fo["payment_count"] = fo["payment_count"].astype("Int64")
    fo["max_installments"] = fo["max_installments"].astype("Int64")

    fo["purchase_date_key"] = _date_key(fo["purchase_ts"])
    fo["delivered_date_key"] = _date_key(fo["customer_delivery_ts"])

    valid = (
        (fo["order_status"] == settings.DELIVERED_STATUS)
        & fo["purchase_ts"].notna()
        & fo["customer_delivery_ts"].notna()
        & fo["estimated_delivery_date"].notna()
        & (fo["customer_delivery_ts"] >= fo["purchase_ts"])
    )
    fo["has_valid_delivery_dates"] = valid

    days = (fo["customer_delivery_ts"] - fo["purchase_ts"]).dt.total_seconds() / 86400
    fo["delivery_days"] = days.where(valid).round(2)
    est_days = (fo["estimated_delivery_date"] - fo["purchase_ts"].dt.normalize()).dt.days
    fo["estimated_delivery_days"] = est_days.where(valid).astype("float64")
    delay = (fo["customer_delivery_ts"].dt.normalize() - fo["estimated_delivery_date"]).dt.days
    fo["delivery_delay_days"] = delay.where(valid).astype("Int64")
    fo["is_late"] = (fo["delivery_delay_days"] > 0).astype("boolean").where(valid)

    fo["is_revenue_order"] = (
        ~fo["order_status"].isin(settings.NON_REVENUE_STATUSES) & (fo["item_count"] > 0)
    )
    invalid_delivered = int(
        ((fo["order_status"] == settings.DELIVERED_STATUS) & ~valid).sum()
    )
    log.add(
        "fact_orders", "derived delivery metrics, revenue flag and item/payment aggregates",
        len(fo), len(fo),
        f"{int(valid.sum())} orders with valid delivery dates; "
        f"{invalid_delivered} 'delivered' orders excluded from delivery metrics (missing/inconsistent dates); "
        f"{int(fo['is_revenue_order'].sum())} revenue orders",
    )

    columns = [
        "order_id", "customer_id", "customer_unique_id", "order_status",
        "purchase_ts", "approved_ts", "carrier_delivery_ts", "customer_delivery_ts",
        "estimated_delivery_date", "customer_zip_prefix", "customer_city", "customer_state",
        "purchase_date_key", "delivered_date_key",
        "item_count", "seller_count", "items_value", "freight_value", "order_total_value",
        "payment_value", "payment_count", "primary_payment_type", "max_installments",
        "delivery_days", "estimated_delivery_days", "delivery_delay_days",
        "has_valid_delivery_dates", "is_late", "is_revenue_order",
    ]
    return fo[columns]


def build_dim_customers(customers: pd.DataFrame, orders: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    """One row per person; location taken from their most recent order."""
    merged = customers.merge(orders[["customer_id", "purchase_ts"]], on="customer_id", how="left")
    merged = merged.sort_values("purchase_ts", na_position="first", kind="stable")
    multi = int(
        (merged.groupby("customer_unique_id")[["zip_prefix", "state"]].nunique(dropna=True) > 1)
        .any(axis=1).sum()
    )
    out = merged.drop_duplicates("customer_unique_id", keep="last")[
        ["customer_unique_id", "zip_prefix", "city", "state"]
    ].reset_index(drop=True)
    log.add(
        "dim_customers", "collapsed customer_id (per order) to customer_unique_id (per person)",
        len(customers), len(out),
        f"{multi} people appear with more than one location; most recent order's location kept",
    )
    return out


def build_dim_date(orders: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    stamps = pd.concat([
        orders["purchase_ts"], orders["approved_ts"], orders["carrier_delivery_ts"],
        orders["customer_delivery_ts"], orders["estimated_delivery_date"],
    ]).dropna()
    if stamps.empty:
        raise EmptyDatasetError("orders contain no valid dates; cannot build dim_date")
    days = pd.date_range(stamps.min().normalize(), stamps.max().normalize(), freq="D")
    out = pd.DataFrame({"full_date": days})
    out["date_key"] = (days.year * 10000 + days.month * 100 + days.day).astype("int64")
    out["calendar_year"] = days.year.astype("int64")
    out["calendar_quarter"] = days.quarter.astype("int64")
    out["calendar_month"] = days.month.astype("int64")
    out["month_name"] = days.month_name()
    out["year_month"] = days.strftime("%Y-%m")
    out["day_of_month"] = days.day.astype("int64")
    out["iso_weekday"] = (days.dayofweek + 1).astype("int64")
    out["weekday_name"] = days.day_name()
    out["is_weekend"] = days.dayofweek >= 5
    log.add("dim_date", "generated continuous calendar", 0, len(out),
            f"{days.min().date()} to {days.max().date()}")
    return out[[
        "date_key", "full_date", "calendar_year", "calendar_quarter", "calendar_month",
        "month_name", "year_month", "day_of_month", "iso_weekday", "weekday_name", "is_weekend",
    ]]


# ---------------------------------------------------------------- orchestrator
def transform_all(raw: dict[str, pd.DataFrame]) -> TransformResult:
    """Run the full cleaning + modelling pipeline on raw tables."""
    log = TransformLog()

    for name in ("customers", "orders", "order_items"):
        if raw[name].empty:
            raise EmptyDatasetError(f"Raw table '{name}' has no rows")

    customers = clean_customers(raw["customers"], log)
    orders = clean_orders(raw["orders"], log)
    items = clean_order_items(raw["order_items"], log)
    payments = clean_payments(raw["payments"], log)
    reviews = clean_reviews(raw["reviews"], log)
    products = clean_products(raw["products"], raw["category_translation"], log)
    sellers = clean_sellers(raw["sellers"], log)
    geolocation = build_dim_geolocation(raw["geolocation"], log)

    # Orders must resolve to a customer (otherwise no customer_unique_id).
    orders = _keep_known(orders, "customer_id", customers["customer_id"], "orders", "customer", log)
    order_ids = orders["order_id"]
    items = _keep_known(items, "order_id", order_ids, "order_items", "order", log)
    payments = _keep_known(payments, "order_id", order_ids, "payments", "order", log)
    reviews = _keep_known(reviews, "order_id", order_ids, "reviews", "order", log)
    products, sellers = ensure_dimension_members(items, products, sellers, log)

    fact_orders = build_fact_orders(orders, customers, items, payments, log)
    dim_customers = build_dim_customers(customers, orders, log)
    dim_date = build_dim_date(orders, log)

    # Guard: pre-aggregated totals must equal the item-level sums (no double counting).
    diff = abs(float(fact_orders["items_value"].sum()) - float(items["price"].sum()))
    if diff > settings.MONEY_TOLERANCE:
        raise TransformationError(
            f"fact_orders.items_value ({fact_orders['items_value'].sum():.2f}) does not reconcile "
            f"with item-level price total ({items['price'].sum():.2f})"
        )

    for df in (items, payments):
        for col in ("price", "freight_value", "payment_value"):
            if col in df:
                df[col] = df[col].round(2)

    tables = {
        "dim_date": dim_date,
        "dim_geolocation": geolocation,
        "dim_customers": dim_customers,
        "dim_products": products[[
            "product_id", "category_pt", "category_en", "name_length", "description_length",
            "photos_qty", "weight_g", "length_cm", "height_cm", "width_cm", "volume_cm3",
        ]],
        "dim_sellers": sellers,
        "fact_orders": fact_orders,
        "fact_order_items": items,
        "fact_payments": payments,
        "fact_reviews": reviews,
    }
    return TransformResult(tables=tables, log=log)
