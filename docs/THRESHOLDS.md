# Rule thresholds

Generated from `config/settings.py` by `python -m scripts.generate_docs` (do not edit by hand). These are analyst-chosen conventions, not statistically derived constants; change them in one place and re-run the tests.

| Constant | Value | Meaning |
|---|---|---|
| `SPARSE_MONTH_FRACTION` | `0.10` | a month with < 10% of the median monthly orders is "sparse" |
| `LOW_REVIEW_THRESHOLD` | `3.5` | average review score below this = poor satisfaction |
| `LATE_RATE_WARNING` | `0.08` | overall late-delivery rate above this is flagged |
| `LOW_REPEAT_RATE` | `0.10` | repeat-purchase rate below this is flagged as weak retention |
| `HIGH_FREIGHT_RATIO` | `0.30` | freight >= 30% of item price = "high freight" product |
| `HIGH_VALUE_QUANTILE` | `0.90` | top 10% of customers by revenue = high value |
| `CATEGORY_MIN_ORDERS` | `30` | minimum orders before a category's review/score is trusted |
| `STATE_MIN_ORDERS` | `100` | minimum delivered orders before a state is ranked/flagged |
| `SELLER_MIN_ORDERS` | `10` | minimum orders before a seller is scored/flagged |
| `SELLER_HIGH_LATE_RATE` | `0.15` | seller late-delivery rate above this = underperforming |
| `LOGISTICS_BOTTLENECK_FACTOR` | `1.5` | late rate >= 1.5 x overall late rate = bottleneck |
| `CURRENCY_SYMBOL` | `"R$"` | the Olist data is in Brazilian reais |
| `CACHE_TTL_SECONDS` | `3600` | analytics results are cached for an hour; "Refresh" clears them |
| `EXCEL_EXPORT_MAX_ROWS` | `5000` | larger tables are exported as CSV only |
| `SUPPLY_GAP_QUANTILE` | `0.75` | states above this quantile of customers-per-seller are "thinly served" |
| `SUPPLY_GAP_MIN_CUSTOMERS` | `100` | a state needs at least this many customers to be assessed |
| `CROSS_SELL_MIN_PAIR_ORDERS` | `10` | a category pair must co-occur in at least this many orders |
| `CROSS_SELL_MIN_LIFT` | `1.0` | lift > 1: the pair co-occurs more often than if independent |
| `ML_RANDOM_STATE` | `42` | every stochastic step is seeded with this |
| `RFM_BINS` | `5` | recency and monetary quintile scores 1-5 |
| `RFM_HIGH_SCORE` | `4` | score >= 4 counts as "high" in the segment rules |
| `COHORT_MIN_SIZE` | `100` | cohorts smaller than this are shown as n/a (retention too noisy) |
| `KMEANS_K_RANGE` | `(2, 6)` | k is chosen by silhouette score within this range |
| `SILHOUETTE_SAMPLE` | `10000` | silhouette is computed on at most this many customers |
| `FORECAST_HORIZON` | `3` | months ahead |
| `FORECAST_MIN_MONTHS` | `12` | full (non-sparse) months needed before any forecast is shown |
| `FORECAST_BACKTEST_MONTHS` | `6` | rolling one-step-ahead backtest over the last N months |
| `DELIVERY_MODEL_MIN_ORDERS` | `500` | delivered orders (valid dates) needed to train |
| `DELIVERY_MODEL_MIN_LATE` | `30` | and at least this many late ones |
| `DELIVERY_TEST_FRACTION` | `0.25` | the most recent 25% of orders form the test set (time split, no shuffling) |
| `TEXT_MIN_TERM_COUNT` | `15` | a term must occur in at least this many comments to be ranked |
