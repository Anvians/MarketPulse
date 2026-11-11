"""Central configuration for MarketPulse.

All paths, dataset file names and business-rule constants live here so that
ingestion, analytics and the UI share one definition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

RAW_DATA_DIR: Path = Path(os.getenv("MARKETPULSE_RAW_DIR", PROJECT_ROOT / "data" / "raw"))
PROCESSED_DATA_DIR: Path = Path(
    os.getenv("MARKETPULSE_PROCESSED_DIR", PROJECT_ROOT / "data" / "processed")
)
DATABASE_SQL_DIR: Path = PROJECT_ROOT / "database"

# Logical table name -> expected CSV file name (Olist Brazilian E-Commerce dataset).
RAW_FILES: dict[str, str] = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

KAGGLE_DATASET_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"

# ---------------------------------------------------------------- business rules
# An order is a "revenue order" when its status is not in this tuple AND it has
# at least one item. Documented in data/DATA_DICTIONARY.md.
NON_REVENUE_STATUSES: tuple[str, ...] = ("canceled", "unavailable")
DELIVERED_STATUS = "delivered"

# Coordinates outside this box are not in Brazil (the raw geolocation file
# contains such outliers). Used only to filter geolocation rows.
BRAZIL_LAT_RANGE: tuple[float, float] = (-34.0, 6.0)
BRAZIL_LNG_RANGE: tuple[float, float] = (-74.5, -34.0)

REVIEW_SCORE_RANGE: tuple[int, int] = (1, 5)

# Tolerance (in currency units) when reconciling summed monetary columns.
MONEY_TOLERANCE = 0.01

DATA_PERIOD_NOTICE = (
    "This dataset contains historical Olist marketplace activity from 2016-2018. "
    "Results describe that period only and are not current business performance."
)


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL connection settings (read from environment variables)."""

    host: str = "localhost"
    port: int = 5432
    name: str = "marketpulse"
    user: str = "postgres"
    password: str = ""

    @classmethod
    def from_env(cls, **overrides: object) -> "DatabaseSettings":
        """Build settings from DB_* environment variables; kwargs override them."""
        raw_port = os.getenv("DB_PORT", "5432")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError(f"DB_PORT must be an integer, got {raw_port!r}") from exc
        values: dict[str, object] = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": port,
            "name": os.getenv("DB_NAME", "marketpulse"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        values.update(overrides)
        return cls(**values)  # type: ignore[arg-type]


# ------------------------------------------------- analytics business rules (M2)
# Every threshold used by a rule-based insight / flag lives here so that it is
# transparent and changeable in one place. They are analyst-chosen conventions,
# NOT statistically derived constants; the UI shows them next to each finding.
SPARSE_MONTH_FRACTION = 0.10     # a month with < 10% of the median monthly orders is "sparse"
LOW_REVIEW_THRESHOLD = 3.5       # average review score below this = poor satisfaction
LATE_RATE_WARNING = 0.08         # overall late-delivery rate above this is flagged
LOW_REPEAT_RATE = 0.10           # repeat-purchase rate below this is flagged as weak retention
HIGH_FREIGHT_RATIO = 0.30        # freight >= 30% of item price = "high freight" product
HIGH_VALUE_QUANTILE = 0.90       # top 10% of customers by revenue = high value
CATEGORY_MIN_ORDERS = 30         # minimum orders before a category's review/score is trusted
STATE_MIN_ORDERS = 100           # minimum delivered orders before a state is ranked/flagged
SELLER_MIN_ORDERS = 10           # minimum orders before a seller is scored/flagged
SELLER_HIGH_LATE_RATE = 0.15     # seller late-delivery rate above this = underperforming
LOGISTICS_BOTTLENECK_FACTOR = 1.5  # late rate >= 1.5 x overall late rate = bottleneck

# Seller scorecard weights (must sum to 1). Components are percentile ranks (0-1).
SELLER_SCORE_WEIGHTS: dict[str, float] = {
    "revenue": 0.30,
    "orders": 0.20,
    "on_time": 0.25,
    "satisfaction": 0.25,
}
# (minimum score, tier label), highest first.
SELLER_TIERS: tuple[tuple[float, str], ...] = (
    (75.0, "Excellent"), (50.0, "Good"), (25.0, "Needs attention"), (0.0, "Underperforming"),
)


# ------------------------------------------------------------- geography (M3)
# Official IBGE macro-regions of Brazil. State codes -> region name.
BRAZIL_REGIONS: dict[str, str] = {
    **{s: "North" for s in ("AC", "AP", "AM", "PA", "RO", "RR", "TO")},
    **{s: "Northeast" for s in ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE")},
    **{s: "Central-West" for s in ("DF", "GO", "MT", "MS")},
    **{s: "Southeast" for s in ("ES", "MG", "RJ", "SP")},
    **{s: "South" for s in ("PR", "RS", "SC")},
}
GEOJSON_STATES_PATH = PROJECT_ROOT / "data" / "geo" / "brazil_states.geojson"

# A single category / the top-10 sellers holding at least this share of revenue is flagged.
CONCENTRATION_ALERT_PCT = 25.0


# ----------------------------------------------------------------- application (M3)
APP_NAME = "MarketPulse"
CURRENCY_SYMBOL = "R$"             # the Olist data is in Brazilian reais
CACHE_TTL_SECONDS = 3600           # analytics results are cached for an hour; "Refresh" clears them
TABLE_PAGE_SIZE = 25
EXCEL_EXPORT_MAX_ROWS = 5000       # larger tables are exported as CSV only


# ----------------------------------------------------- opportunities & growth (M4)
SUPPLY_GAP_QUANTILE = 0.75         # states above this quantile of customers-per-seller are "thinly served"
SUPPLY_GAP_MIN_CUSTOMERS = 100     # a state needs at least this many customers to be assessed
CROSS_SELL_MIN_PAIR_ORDERS = 10    # a category pair must co-occur in at least this many orders
CROSS_SELL_MIN_LIFT = 1.0          # lift > 1: the pair co-occurs more often than if independent


# ------------------------------------------------- advanced analytics (M5)
ML_RANDOM_STATE = 42               # every stochastic step is seeded with this
RFM_BINS = 5                       # recency and monetary quintile scores 1-5
RFM_HIGH_SCORE = 4                 # score >= 4 counts as "high" in the segment rules
COHORT_MIN_SIZE = 100              # cohorts smaller than this are shown as n/a (retention too noisy)
KMEANS_K_RANGE = (2, 6)            # k is chosen by silhouette score within this range
SILHOUETTE_SAMPLE = 10000          # silhouette is computed on at most this many customers
FORECAST_HORIZON = 3               # months ahead
FORECAST_MIN_MONTHS = 12           # full (non-sparse) months needed before any forecast is shown
FORECAST_BACKTEST_MONTHS = 6       # rolling one-step-ahead backtest over the last N months
DELIVERY_MODEL_MIN_ORDERS = 500    # delivered orders (valid dates) needed to train
DELIVERY_MODEL_MIN_LATE = 30       # and at least this many late ones
DELIVERY_TEST_FRACTION = 0.25      # the most recent 25% of orders form the test set (time split, no shuffling)
TEXT_MIN_TERM_COUNT = 15           # a term must occur in at least this many comments to be ranked
