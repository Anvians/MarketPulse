-- MarketPulse indexes for the access patterns used by the analytics layer:
-- date-range filters, state/category/seller/payment/status filters and joins.
-- (Primary-key indexes already exist.)

-- fact_orders
CREATE INDEX IF NOT EXISTS idx_orders_purchase_ts      ON fact_orders (purchase_ts);
CREATE INDEX IF NOT EXISTS idx_orders_purchase_date    ON fact_orders (purchase_date_key);
CREATE INDEX IF NOT EXISTS idx_orders_delivered_date   ON fact_orders (delivered_date_key);
CREATE INDEX IF NOT EXISTS idx_orders_customer_unique  ON fact_orders (customer_unique_id);
CREATE INDEX IF NOT EXISTS idx_orders_status           ON fact_orders (order_status);
CREATE INDEX IF NOT EXISTS idx_orders_state            ON fact_orders (customer_state);
CREATE INDEX IF NOT EXISTS idx_orders_payment_type     ON fact_orders (primary_payment_type);
CREATE INDEX IF NOT EXISTS idx_orders_revenue          ON fact_orders (purchase_date_key) WHERE is_revenue_order;
CREATE INDEX IF NOT EXISTS idx_orders_delivery_valid   ON fact_orders (purchase_date_key) WHERE has_valid_delivery_dates;

-- fact_order_items (order_id is covered by the composite PK)
CREATE INDEX IF NOT EXISTS idx_items_product ON fact_order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_items_seller  ON fact_order_items (seller_id);

-- fact_payments (order_id is covered by the composite PK)
CREATE INDEX IF NOT EXISTS idx_payments_type ON fact_payments (payment_type);

-- fact_reviews (order_id is NOT the leading PK column)
CREATE INDEX IF NOT EXISTS idx_reviews_order    ON fact_reviews (order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_score    ON fact_reviews (review_score);
CREATE INDEX IF NOT EXISTS idx_reviews_creation ON fact_reviews (review_creation_ts);

-- dimensions
CREATE INDEX IF NOT EXISTS idx_products_category ON dim_products (category_en);
CREATE INDEX IF NOT EXISTS idx_sellers_state     ON dim_sellers (state);
CREATE INDEX IF NOT EXISTS idx_customers_state   ON dim_customers (state);
CREATE INDEX IF NOT EXISTS idx_date_year_month   ON dim_date (year_month);

ANALYZE;
