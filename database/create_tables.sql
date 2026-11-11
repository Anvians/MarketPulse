-- MarketPulse star schema: tables, primary keys and CHECK constraints.
-- Foreign keys are added AFTER loading (create_relationships.sql) so that the
-- bulk load is fast and every relationship is validated in one pass.
--
-- Running this script DROPS and recreates all warehouse tables (not the etl_* logs).

DROP TABLE IF EXISTS fact_reviews     CASCADE;
DROP TABLE IF EXISTS fact_payments    CASCADE;
DROP TABLE IF EXISTS fact_order_items CASCADE;
DROP TABLE IF EXISTS fact_orders      CASCADE;
DROP TABLE IF EXISTS dim_geolocation  CASCADE;
DROP TABLE IF EXISTS dim_sellers      CASCADE;
DROP TABLE IF EXISTS dim_products     CASCADE;
DROP TABLE IF EXISTS dim_customers    CASCADE;
DROP TABLE IF EXISTS dim_date         CASCADE;

-- ------------------------------------------------------------------ dimensions
CREATE TABLE dim_date (
    date_key         INTEGER      PRIMARY KEY,           -- yyyymmdd
    full_date        DATE         NOT NULL UNIQUE,
    calendar_year    SMALLINT     NOT NULL,
    calendar_quarter SMALLINT     NOT NULL CHECK (calendar_quarter BETWEEN 1 AND 4),
    calendar_month   SMALLINT     NOT NULL CHECK (calendar_month BETWEEN 1 AND 12),
    month_name       VARCHAR(10)  NOT NULL,
    year_month       CHAR(7)      NOT NULL,              -- 'YYYY-MM'
    day_of_month     SMALLINT     NOT NULL,
    iso_weekday      SMALLINT     NOT NULL CHECK (iso_weekday BETWEEN 1 AND 7),  -- 1 = Monday
    weekday_name     VARCHAR(10)  NOT NULL,
    is_weekend       BOOLEAN      NOT NULL
);

-- One row per zip-code PREFIX. The raw geolocation file has many rows per
-- prefix; they are aggregated (mean coordinates, modal city/state) so that
-- joining never multiplies customers or sellers.
CREATE TABLE dim_geolocation (
    zip_prefix       CHAR(5)          PRIMARY KEY,
    latitude         DOUBLE PRECISION NOT NULL,
    longitude        DOUBLE PRECISION NOT NULL,
    city             TEXT,
    state            CHAR(2),
    source_row_count INTEGER          NOT NULL CHECK (source_row_count > 0)
);

-- One row per PERSON (customer_unique_id). In the source data customer_id is
-- generated per order, so it cannot be used to identify repeat buyers.
-- Location = the customer's most recent order.
CREATE TABLE dim_customers (
    customer_unique_id VARCHAR(32) PRIMARY KEY,
    zip_prefix         CHAR(5),
    city               TEXT,
    state              CHAR(2)
);

CREATE TABLE dim_products (
    product_id         VARCHAR(32)      PRIMARY KEY,
    category_pt        TEXT,                    -- original Portuguese name (may be NULL)
    category_en        TEXT NOT NULL,           -- English name; 'unknown' when absent
    name_length        INTEGER,
    description_length INTEGER,
    photos_qty         INTEGER,
    weight_g           DOUBLE PRECISION CHECK (weight_g IS NULL OR weight_g >= 0),
    length_cm          DOUBLE PRECISION CHECK (length_cm IS NULL OR length_cm >= 0),
    height_cm          DOUBLE PRECISION CHECK (height_cm IS NULL OR height_cm >= 0),
    width_cm           DOUBLE PRECISION CHECK (width_cm IS NULL OR width_cm >= 0),
    volume_cm3         DOUBLE PRECISION
);

CREATE TABLE dim_sellers (
    seller_id  VARCHAR(32) PRIMARY KEY,
    zip_prefix CHAR(5),
    city       TEXT,
    state      CHAR(2)
);

-- ----------------------------------------------------------------------- facts
-- Grain: one row per order. Item and payment totals are PRE-AGGREGATED here so
-- order-level KPIs never need to join to a one-to-many table (no double counting).
CREATE TABLE fact_orders (
    order_id                VARCHAR(32)  PRIMARY KEY,
    customer_id             VARCHAR(32)  NOT NULL,
    customer_unique_id      VARCHAR(32)  NOT NULL,
    order_status            VARCHAR(20)  NOT NULL,
    purchase_ts             TIMESTAMP,
    approved_ts             TIMESTAMP,
    carrier_delivery_ts     TIMESTAMP,
    customer_delivery_ts    TIMESTAMP,
    estimated_delivery_date DATE,
    customer_zip_prefix     CHAR(5),
    customer_city           TEXT,
    customer_state          CHAR(2),
    purchase_date_key       INTEGER,
    delivered_date_key      INTEGER,
    -- item-level aggregates (from fact_order_items)
    item_count              INTEGER        NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    seller_count            INTEGER        NOT NULL DEFAULT 0,
    items_value             NUMERIC(14,2)  NOT NULL DEFAULT 0 CHECK (items_value >= 0),  -- sum(price): PRODUCT REVENUE
    freight_value           NUMERIC(14,2)  NOT NULL DEFAULT 0 CHECK (freight_value >= 0),
    order_total_value       NUMERIC(14,2)  NOT NULL DEFAULT 0,                           -- items_value + freight_value
    -- payment aggregates (from fact_payments); NULL when no payment record exists
    payment_value           NUMERIC(14,2),
    payment_count           INTEGER,
    primary_payment_type    VARCHAR(20),
    max_installments        INTEGER,
    -- delivery metrics (NULL unless has_valid_delivery_dates)
    delivery_days           NUMERIC(8,2),      -- delivered - purchase, in days
    estimated_delivery_days NUMERIC(8,2),      -- estimated date - purchase date, in days
    delivery_delay_days     INTEGER,           -- delivered DATE - estimated DATE (>0 = late)
    has_valid_delivery_dates BOOLEAN       NOT NULL DEFAULT FALSE,
    is_late                 BOOLEAN,           -- delivery_delay_days > 0; NULL when not valid
    is_revenue_order        BOOLEAN       NOT NULL DEFAULT FALSE
);

-- Grain: one row per item line. PK is (order_id, order_item_id).
CREATE TABLE fact_order_items (
    order_id          VARCHAR(32)   NOT NULL,
    order_item_id     INTEGER       NOT NULL,
    product_id        VARCHAR(32)   NOT NULL,
    seller_id         VARCHAR(32)   NOT NULL,
    shipping_limit_ts TIMESTAMP,
    price             NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    freight_value     NUMERIC(12,2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

-- Grain: one row per payment instalment record. PK is (order_id, payment_sequential).
CREATE TABLE fact_payments (
    order_id             VARCHAR(32)   NOT NULL,
    payment_sequential   INTEGER       NOT NULL,
    payment_type         VARCHAR(20)   NOT NULL,
    payment_installments INTEGER,
    payment_value        NUMERIC(12,2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

-- Grain: one row per (review_id, order_id). review_id alone is NOT unique in the
-- source, and an order may have several reviews; use vw_order_review for one
-- review per order.
CREATE TABLE fact_reviews (
    review_id              VARCHAR(32) NOT NULL,
    order_id               VARCHAR(32) NOT NULL,
    review_score           SMALLINT    NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title   TEXT,
    review_comment_message TEXT,
    review_creation_ts     TIMESTAMP,
    review_answer_ts       TIMESTAMP,
    PRIMARY KEY (review_id, order_id)
);

-- ------------------------------------------------------------- ETL bookkeeping
-- Not dropped on re-initialisation, so run history survives reloads.
CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id      BIGSERIAL   PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      VARCHAR(20) NOT NULL,
    raw_dir     TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS etl_table_load_log (
    run_id      BIGINT NOT NULL REFERENCES etl_run_log (run_id) ON DELETE CASCADE,
    table_name  TEXT   NOT NULL,
    rows_loaded BIGINT NOT NULL,
    PRIMARY KEY (run_id, table_name)
);

CREATE TABLE IF NOT EXISTS etl_transformation_log (
    log_id      BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES etl_run_log (run_id) ON DELETE CASCADE,
    table_name  TEXT   NOT NULL,
    step        TEXT   NOT NULL,
    rows_before BIGINT,
    rows_after  BIGINT,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS etl_quality_report (
    run_id BIGINT PRIMARY KEY REFERENCES etl_run_log (run_id) ON DELETE CASCADE,
    report JSONB  NOT NULL
);
