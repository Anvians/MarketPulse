# Data folder

## `raw/` — put the Olist CSV files here

The dataset is **not** bundled (size/licence). Download it from Kaggle:

<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>

Either download the ZIP in the browser, or with the Kaggle CLI:

```bash
pip install kaggle                      # needs ~/.kaggle/kaggle.json (Kaggle > Settings > Create New Token)
kaggle datasets download -d olistbr/brazilian-ecommerce -p data/raw --unzip
```

After extraction `data/raw/` must contain exactly these nine files:

| File | Content |
|---|---|
| `olist_customers_dataset.csv` | customers (`customer_id` is per **order**; `customer_unique_id` identifies the person) |
| `olist_orders_dataset.csv` | one row per order, status and timestamps |
| `olist_order_items_dataset.csv` | one row per item line (price, freight) |
| `olist_order_payments_dataset.csv` | one or more payment records per order |
| `olist_order_reviews_dataset.csv` | reviews (score, optional Portuguese comment) |
| `olist_products_dataset.csv` | product attributes (category, weight, dimensions) |
| `olist_sellers_dataset.csv` | sellers and their location |
| `olist_geolocation_dataset.csv` | many coordinate rows per zip prefix |
| `product_category_name_translation.csv` | Portuguese → English category names |

You can keep the files elsewhere and point to them with `--raw-dir` or the
`MARKETPULSE_RAW_DIR` environment variable.

## `processed/` — generated output

Written by `python -m ingestion.run_pipeline`:

* `data_quality_report.json` — every validation check with PASS / WARN / FAIL
* `transformation_log.csv` — every cleaning/derivation step with row counts
* `<table>.csv` — transformed star-schema tables (only with `--save-processed`)

## Data period

The data is **historical (2016–2018)** Brazilian marketplace activity. Nothing
here describes current Olist performance. The dataset also has very low
activity at the start and end of its range, so first/last-month trends should
be read with care (this is verified against the real data in Milestone 2, not
assumed).

See [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) for column definitions, KPI formulas and modelling decisions.
