# MarketPulse — E-Commerce Business Intelligence & Decision Support Platform

An end-to-end analytics project on the **Olist Brazilian E-Commerce Public Dataset**
(about 100k orders, **historical data from 2016–2018**): validated ingestion → PostgreSQL star
schema → tested analytics engine → 18-page Streamlit app with filters, exports, rule-based findings
and honestly evaluated machine learning.

**Read this first.** Everything describes a historical period, not today's business. Revenue means
*product revenue* (item prices on non-canceled orders); it is **not profit** because the dataset has no
costs. There is no inventory data. Findings are rules with their evidence shown, not forecasts or proof of cause.
Details: [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

| | |
|---|---|
| Stack | Python 3.11+, pandas, NumPy, SQLAlchemy + psycopg, PostgreSQL 14+, SciPy, statsmodels, scikit-learn, Streamlit, Plotly, ReportLab, openpyxl |
| Status | All six milestones built; 284 tests (run `pytest`) |
| Not verified here | The Docker files were written and validated with `docker compose config`, but the image was not built in the authoring environment (no Docker daemon). See *Docker* below |

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # set DB_PASSWORD etc.; never commit .env
# download the 9 Olist CSVs into data/raw/   (see data/README.md)

python -m ingestion.run_pipeline    # validate, transform, create the database, load
streamlit run app.py                # http://localhost:8501
pytest                              # tests (DB tests use a separate marketpulse_test database)
```

Pipeline options: `--skip-db` (validate + transform only), `--raw-dir PATH`, `--db-name NAME`, `--save-processed`.
The pipeline writes `data/processed/data_quality_report.json` and `transformation_log.csv` and refuses to load if any check **FAIL**s.

## Docker

```bash
cp .env.example .env                                  # set DB_PASSWORD (compose refuses to start without it)
# put the 9 CSVs in ./data/raw
docker compose up -d db
docker compose --profile tools run --rm pipeline      # validate, transform, load
docker compose up -d app                              # http://localhost:8501
```

The database is not published to the host and the app is bound to `127.0.0.1`. Secrets come from `.env`
and are not baked into the image; the raw data is mounted read-only. Inside compose the app uses host `db`.

## Analytics engine

`analytics/` holds UI-free metric functions; every one takes `(engine, filters=None, ...)`:

```python
from datetime import date
from config.database import get_engine
from analytics.base import Filters
from analytics import executive, sellers

engine = get_engine()
f = Filters(states=("SP", "RJ"), date_from=date(2017, 1, 1))
executive.calculate_executive_kpis(engine, f)      # the nine KPI cards
executive.generate_executive_insights(engine, f)   # rule-based findings, each with its rule
sellers.generate_seller_scorecard(engine, f)       # transparent weighted score
```

Rates are fractions in [0, 1]; revenue/category/seller metrics read the item grain, delivery/review metrics the
order grain, so joins never double count; growth skips near-empty "sparse" edge months; every threshold lives in
`config/settings.py`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The app

```bash
streamlit run app.py          # needs the database loaded (python -m ingestion.run_pipeline)
```

| Section | Pages |
|---|---|
| Overview | Executive Dashboard |
| Revenue & Sales | Revenue Intelligence, Sales Analytics, Product Performance |
| Customers | Customer Analytics, Customer Segmentation, Customer Satisfaction |
| Operations | Seller Performance, Logistics Analytics, Geographic Intelligence |
| Advanced Analytics | Revenue Forecast, Delivery Risk, Statistical Tests, Review Text Analysis |
| Opportunities | Business Opportunity Finder, Growth Opportunities |
| System | Business Reports, Data Quality & Information (includes every KPI formula) |

* **Global filters** (sidebar, shared by all pages): purchase date, customer state, category, seller, payment type, order status. The active filters are echoed in each page header.
* **KPI cards** carry a tooltip with the formula, denominator and null handling (`config/kpi_definitions.py`). Values that cannot be computed show `n/a`, never 0.
* **Charts** are Plotly with one fixed palette, direct value labels and a "View data" table under each chart; tables download as CSV, and as Excel up to 5,000 rows.
* **Insights** are rule-based; "Why am I seeing this?" shows the rule and the evidence. Thresholds live in `config/settings.py`.
* The Brazil map uses a bundled GeoJSON and no map tiles, so it works offline.
* Results are cached for an hour; "Refresh data cache" in the sidebar clears them.
* Every page states that the data is historical (2016–2018); revenue is product revenue, not profit, and there is no inventory data.

### Opportunities, growth and reports

* **Business Opportunity Finder** (`analytics/opportunities.py`): one table of rule-based findings (weak or well-reviewed-but-small categories, state/seller delivery bottlenecks, sellers breaching service rules, high-freight categories, low repeat rate, low satisfaction). Each row shows its evidence and its rule, and rows are ranked by **observed revenue** of the entity involved. That sizes what to look at; it is not a forecast of gain.
* **Growth Opportunities** (`analytics/growth.py`): categories and states whose revenue rose between the last 3 and the previous 3 full months (needs 6 full months), thinly served states (customers per seller), and category pairs bought together (with lift). Observed history only.
* **Business Reports** (`reports/`): one `Report` object feeds the PDF (ReportLab), Excel and CSV-zip downloads so they always agree. Each report opens with the data-period, not-profit and no-inventory limitations.
* Thresholds for all rules are in `config/settings.py`.

### Advanced analytics

| Page | Method | Honesty built in |
|---|---|---|
| Customer Segmentation | RFM quintile scores with six published rules; k-means on log-scaled R/F/M (k by silhouette); cohort retention heatmap | Recency measured from the last purchase in the data, not today; cohorts under 100 customers show n/a; clusters are described only by their averages |
| Revenue Forecast | Damped-trend exponential smoothing on full months | Rolling one-month-ahead backtest vs the naive "same as last month"; the page says so when the model does not beat it; no seasonality is claimed |
| Delivery Risk | Logistic regression and gradient boosting on purchase-time features only | Time split (oldest 75% train, newest 25% test), baseline comparison, "not informative" verdict when AUC < 0.60, no leaking columns (tested) |
| Statistical Tests | Mann-Whitney, chi-square, Spearman, Kruskal-Wallis, Wilson/t intervals | Effect sizes lead, with magnitude labels; no causal claims |
| Review Text Analysis | Smoothed log-odds of words in 1–2 vs 4–5 star comments (Portuguese, accents folded) | Explicitly **not** a sentiment model; commenters are not a random sample |

All seeds are fixed (`ML_RANDOM_STATE`) and every threshold is in `config/settings.py`. The tests for these methods use seeded SYNTHETIC data (`tests/synthetic_large.py`) to prove a planted signal is found and pure noise is *not* reported as useful; no result in the app comes from synthetic data.

## Project layout

```
app.py          Streamlit entry point (config, theme, sidebar filters, navigation)
pages/          the 18 pages
components/     theme, formatting, filters, kpi_cards, charts, tables, insights, sidebar, layout, data (cache)
analytics/      base, executive, revenue, sales, products, customers, sellers, logistics, satisfaction, geography,
                system, opportunities, growth, segmentation, cohorts, forecasting, delivery_model, stats_tests, text_analysis
reports/        csv_exporter, excel_generator, report_builder, pdf_generator
ingestion/      validate_data, transform_data, load_data, run_pipeline
database/       create_tables / relationships / indexes / analytical_views / validation_queries (.sql)
config/         settings (paths, thresholds), database, kpi_definitions
sql/            readable reference queries (executed by the test suite)
docs/           ARCHITECTURE, METHODOLOGY, KPI_REFERENCE*, THRESHOLDS*, PROJECT_SUMMARY   (* generated)
scripts/        generate_docs.py, take_screenshots.py
tests/          unit, database, analytics, advanced-method and AppTest page tests (+ docs/deployment checks)
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | layers, data flow, design decisions, testing strategy |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | data limits, definitions, filters, method guard rails |
| [docs/KPI_REFERENCE.md](docs/KPI_REFERENCE.md) | every KPI: formula, denominator, missing-data handling (generated) |
| [docs/THRESHOLDS.md](docs/THRESHOLDS.md) | every rule threshold (generated; a test fails if it drifts) |
| [data/DATA_DICTIONARY.md](data/DATA_DICTIONARY.md) | tables, columns, transformations |
| [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) | portfolio / interview talking points |

After changing a KPI definition or a setting, run `python -m scripts.generate_docs`.
To add screenshots from **your** run on the real data: start the app, then `python -m scripts.take_screenshots`
(needs `pip install playwright && playwright install chromium`); images go to `docs/screenshots/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MissingDataFilesError` | download the CSVs into `data/raw/` or use `--raw-dir` |
| `SchemaMismatchError` | the CSV headers differ from the expected Olist layout; the message lists what is missing |
| `Cannot connect to database` | check `.env`, that PostgreSQL is running, and the port |
| App shows "database is not available" | load the data first: `python -m ingestion.run_pipeline`; check `DB_*` in `.env` |
| DB tests are skipped | PostgreSQL unreachable; set `DB_*` env vars (tests use separate `marketpulse_test*` databases) |
| `docker compose` says DB_PASSWORD is missing | set it in `.env` |
| Charts or numbers look stale after reloading data | sidebar → "Refresh data cache" |

## Limitations

* Historical 2016–2018 data; results do not describe the present.
* No cost data (revenue ≠ profit) and no inventory data.
* Late delivery is date-based (delivered date after estimated date); a timestamp-based variant is not implemented.
* The forecast uses about two years of history without seasonality and states when it fails its backtest.
* Rule thresholds are analyst conventions (listed in docs/THRESHOLDS.md), not statistically derived.
* Review-text analysis measures word association with review scores; it is not a sentiment model.
