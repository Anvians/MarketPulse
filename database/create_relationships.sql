-- MarketPulse foreign keys. Run AFTER data is loaded; a failure here means the
-- data violates a relationship (see ingestion/validate_data.py for diagnostics).
--
-- Deliberately NOT enforced: zip_prefix -> dim_geolocation. Some customer and
-- seller zip prefixes do not exist in the geolocation file, so this is a soft
-- relationship; coverage is reported by validate_foreign_keys().

ALTER TABLE fact_orders
    ADD CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_unique_id) REFERENCES dim_customers (customer_unique_id),
    ADD CONSTRAINT fk_orders_purchase_date
        FOREIGN KEY (purchase_date_key)  REFERENCES dim_date (date_key),
    ADD CONSTRAINT fk_orders_delivered_date
        FOREIGN KEY (delivered_date_key) REFERENCES dim_date (date_key);

ALTER TABLE fact_order_items
    ADD CONSTRAINT fk_items_order
        FOREIGN KEY (order_id)   REFERENCES fact_orders (order_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_items_product
        FOREIGN KEY (product_id) REFERENCES dim_products (product_id),
    ADD CONSTRAINT fk_items_seller
        FOREIGN KEY (seller_id)  REFERENCES dim_sellers (seller_id);

ALTER TABLE fact_payments
    ADD CONSTRAINT fk_payments_order
        FOREIGN KEY (order_id) REFERENCES fact_orders (order_id) ON DELETE CASCADE;

ALTER TABLE fact_reviews
    ADD CONSTRAINT fk_reviews_order
        FOREIGN KEY (order_id) REFERENCES fact_orders (order_id) ON DELETE CASCADE;
