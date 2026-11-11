# MarketPulse data dictionary

Warehouse = star schema in PostgreSQL. Raw column names follow the published Olist
layout; the pipeline verifies them against the real CSV headers on every run.

## Modelling decisions (read first)

| Topic | Decision | Why |
|---|---|---|
| Person vs order | `dim_customers` is keyed on `customer_unique_id`. `customer_id` exists only on `fact_orders`. | `customer_id` is generated **per order** in Olist; using it would make every customer appear to buy once. |
| Order grain | `fact_orders` = 1 row/order with item and payment totals pre-aggregated. | Prevents revenue fan-out when joining one-to-many tables. |
| Revenue | `sum(item price)` over **revenue orders**. Freight is separate. `order_total_value = items_value + freight_value`. | Item price is the product value; payments can include vouchers/interest. **Revenue is not profit** — there is no cost data. |
| Revenue order | `order_status` not in (`canceled`, `unavailable`) **and** ≥ 1 item. | Canceled/unavailable orders are not realised sales. |
| Delivery lateness | Compare **dates**: delivered date ≤ estimated date ⇒ on time. | Matches "arriving on or before the estimated delivery date". Estimated dates carry no time of day. |
| Delivery metrics scope | Only `delivered` orders with purchase, delivery and estimated dates and delivery ≥ purchase (`has_valid_delivery_dates`). | Avoids mixing in unfinished or inconsistent records. |
| Reviews | Key is `(review_id, order_id)`; `review_id` alone is not unique. `vw_order_review` returns the latest review per order. | An order can have several reviews; averaging raw rows would over-weight those orders. |
| Geolocation | One row per zip **prefix** (mean lat/lng, modal city/state); coordinates outside Brazil dropped. | Raw file has many rows per prefix; joining it directly duplicates customers/sellers. |
| Geo relationship | `zip_prefix → dim_geolocation` is **soft** (not a foreign key). | Some customer/seller prefixes have no geolocation record; coverage is reported. |
| Categories | English name via translation table; untranslated keep the Portuguese name; missing → `unknown`. | Nothing is dropped. |
| Orphans | Items/payments/reviews without an order are dropped (logged). Products/sellers referenced by items but missing from their dimension are added as id-only members (logged). | Keeps referential integrity without losing revenue. |

## Dimensions

**dim_date** — `date_key` (yyyymmdd, PK), `full_date`, `calendar_year`, `calendar_quarter`, `calendar_month`, `month_name`, `year_month` (`YYYY-MM`), `day_of_month`, `iso_weekday` (1 = Monday), `weekday_name`, `is_weekend`.

**dim_geolocation** — `zip_prefix` (PK, char 5), `latitude`, `longitude` (means), `city`, `state` (modal), `source_row_count`.

**dim_customers** — `customer_unique_id` (PK), `zip_prefix`, `city`, `state` (from the person's most recent order).

**dim_products** — `product_id` (PK), `category_pt`, `category_en`, `name_length`, `description_length`, `photos_qty`, `weight_g`, `length_cm`, `height_cm`, `width_cm`, `volume_cm3` (= L×H×W). Source columns are spelled `…_lenght` in the raw file.

**dim_sellers** — `seller_id` (PK), `zip_prefix`, `city`, `state`.

## Facts

**fact_orders** (PK `order_id`)

| Column | Meaning |
|---|---|
| `customer_id`, `customer_unique_id` | order-level id and person id |
| `order_status` | lower-cased source status |
| `purchase_ts`, `approved_ts`, `carrier_delivery_ts`, `customer_delivery_ts` | source timestamps (invalid → NULL, logged) |
| `estimated_delivery_date` | date only |
| `customer_zip_prefix/city/state` | customer location **at the time of the order** (use this for geography of sales) |
| `purchase_date_key`, `delivered_date_key` | FKs to `dim_date` |
| `item_count`, `seller_count` | counts from item rows |
| `items_value` | Σ item price = **product revenue** |
| `freight_value` | Σ item freight |
| `order_total_value` | `items_value + freight_value` |
| `payment_value`, `payment_count`, `max_installments` | from `fact_payments`; NULL if no payment record |
| `primary_payment_type` | payment type with the largest value on the order |
| `delivery_days` | delivered − purchase, in days (valid deliveries only) |
| `estimated_delivery_days` | estimated date − purchase date |
| `delivery_delay_days` | delivered **date** − estimated **date**; > 0 = late |
| `has_valid_delivery_dates` | see decisions above |
| `is_late` | `delivery_delay_days > 0`; NULL when not valid |
| `is_revenue_order` | see decisions above |

**fact_order_items** (PK `order_id, order_item_id`) — `product_id`, `seller_id`, `shipping_limit_ts`, `price`, `freight_value`.

**fact_payments** (PK `order_id, payment_sequential`) — `payment_type`, `payment_installments`, `payment_value`.

**fact_reviews** (PK `review_id, order_id`) — `review_score` (1–5), `review_comment_title`, `review_comment_message` (Portuguese free text, used for sentiment in Milestone 5), `review_creation_ts`, `review_answer_ts`.

## ETL bookkeeping tables (kept across reloads)

`etl_run_log` (run time/status), `etl_table_load_log` (rows per table), `etl_transformation_log` (every cleaning step), `etl_quality_report` (full JSON report). The Data Quality page reads these.

## Analytical views

| View | Grain | Notes |
|---|---|---|
| `vw_order_review` | 1 row / order | latest review per order |
| `vw_revenue_orders` | 1 row / revenue order | with calendar columns |
| `vw_item_details` | 1 row / order **item** | for product/seller/category work; never `COUNT(*)` for orders |
| `vw_monthly_kpis` | 1 row / month | orders, customers, revenue, freight, AOV, avg review |
| `vw_delivery_performance` | 1 row / validly delivered order | delay, late flag, review |
| `vw_customer_summary` | 1 row / person with ≥ 1 revenue order | orders, revenue, `is_repeat_customer` |
| `vw_seller_summary` | 1 row / seller with ≥ 1 revenue order | review is order-level, shared across sellers on one order |
| `vw_category_summary` | 1 row / category | `orders` = distinct orders containing the category |

## KPI definitions (implemented from Milestone 2)

| KPI | Formula | Denominator / null handling |
|---|---|---|
| Total revenue | Σ `items_value` over revenue orders | excludes freight |
| Average order value | revenue ÷ distinct revenue orders | order grain, not item rows |
| Repeat purchase rate | people with > 1 revenue order ÷ people with ≥ 1 revenue order | keyed on `customer_unique_id` |
| On-time delivery rate | on-time ÷ orders with `has_valid_delivery_dates` | undelivered/invalid excluded |
| Late delivery rate | late ÷ orders with `has_valid_delivery_dates` | 1 − on-time rate |
| Average review score | mean of `vw_order_review.review_score` | one review per order |
| Negative review rate | reviews scored 1–2 ÷ scored reviews | |

## Known limitations

* 2016–2018 historical data only.
* No product costs or operating expenses ⇒ no profit or margin analysis.
* No inventory levels ⇒ no stock-out or inventory-optimisation claims.
* Repeat purchasing in this marketplace is low; retention figures are reported as observed, never inflated.
* RFM segments are analytical classifications, not verified customer intent.
