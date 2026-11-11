# Architecture

```
Olist CSVs (9)            data/raw/   (not committed)
     │  ingestion/validate_data.py   schema + quality checks, FAIL stops the load
     │  ingestion/transform_data.py  documented, logged cleaning steps
     ▼
PostgreSQL star schema    database/*.sql   fact_orders (order grain), fact_order_items,
     │                    fact_payments, fact_reviews; dim_customers/products/sellers/geolocation/date;
     │                    analytical views (vw_order_review ...); etl_runs / load logs / stored quality report
     ▼
analytics/                UI-free functions (engine, Filters) -> numbers / DataFrames / Insight objects
     │  base.py             Filters, item_scope vs order_scope, revenue_by, sparse-month rule
     │  executive … geography, opportunities, growth        descriptive + rule-based findings
     │  segmentation, cohorts, forecasting, delivery_model, stats_tests, text_analysis   advanced methods
     ▼
components/ + pages/      Streamlit UI: sidebar filters, KPI cards, chart cards, tables, 18 pages
reports/                  one Report object -> PDF (ReportLab), Excel (openpyxl), CSV zip
```

## Decisions that matter

| Decision | Why |
|---|---|
| **Order grain table pre-aggregated** (`fact_orders`) | Joining orders to items and payments multiplies rows; summing money after such a join double counts. Items, payments and reviews are aggregated to the order first, and reconciliation checks fail the load if totals drift. |
| **Two scopes in `analytics/base.py`** | *Item scope* (one row per item) for revenue/category/seller metrics; *order scope* (one row per order) for delivery, review and customer-timing metrics. A category/seller filter selects items in the first and "orders containing a matching item" in the second. Neither scope can multiply an order. |
| **Customer = person** | `customer_unique_id`, not the per-order `customer_id` (which makes every customer look new). |
| **Revenue = product revenue** | Sum of item price on non-canceled orders with items. Freight is separate. Never called profit: there is no cost data. |
| **Rates are fractions; `*_pct` columns are percent; `None` means "not computable"** | A rate with an empty denominator is unknown, not zero. The UI shows `n/a`. |
| **Date-based lateness** | Late = delivered *date* after the estimated *date* (the estimate has no time of day). This gives ~6.8% on the real data, below the ~8% sometimes quoted from timestamp comparison. |
| **Rules are data, not prose** | Every threshold is in `config/settings.py` ([THRESHOLDS.md](THRESHOLDS.md)); every finding is an `Insight` carrying its rule and evidence. |
| **Parameterised SQL only** | Filter values are bind parameters; nothing user-supplied is formatted into SQL. |
| **Caching** | `st.cache_data` keyed on (function, filters, arguments), one hour; "Refresh data cache" clears it. The engine is a cached resource. |
| **No placeholder pages** | A page appears in the navigation only when its analytics exist and are tested. |

## Layers and their rules

* `analytics/` never imports Streamlit. Everything there is testable with a plain engine.
* `components/` holds presentation only (formatting, theme, charts, filters). Numbers come from `analytics/`.
* `reports/` takes the same analytics output as the pages, so PDF, Excel, CSV and screen agree.
* Configuration comes from environment variables (`DB_*`) and `config/settings.py`; `.env` is never committed or baked into the image.

## Testing strategy

| Layer | How |
|---|---|
| Transformations and metric definitions | Hand-computable synthetic fixture (`tests/conftest.py`): every expected value is derivable by hand and written in the test |
| Database | Throwaway `marketpulse_test` database: constraints, indexes, idempotent reload, reconciliation |
| Analytics | Same fixture; item vs order scope; filters; empty results; `None` vs 0 |
| Advanced methods | Seeded synthetic data with a **planted** signal (must be found) and pure noise (must not be reported as useful) |
| App | `streamlit.testing.AppTest` on every page, with and without data; filter persistence; empty-state rendering |
| Docs and deployment files | `tests/test_docs.py`: reference docs match the code, every page is documented, compose/Docker files contain no secrets |

Fixtures are synthetic and labelled as such; no result in the application is derived from them.
