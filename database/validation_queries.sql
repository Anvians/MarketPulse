-- MarketPulse database validation queries.
-- Each query returns one row; `violations` must be 0 (or the two compared
-- values must match) for the warehouse to be considered consistent.

-- 1. Product revenue reconciles between item grain and order grain
SELECT 'items_vs_orders_product_revenue' AS check_name,
       (SELECT COALESCE(SUM(price), 0)       FROM fact_order_items) AS item_level,
       (SELECT COALESCE(SUM(items_value), 0) FROM fact_orders)      AS order_level;

-- 2. Freight reconciles between item grain and order grain
SELECT 'items_vs_orders_freight' AS check_name,
       (SELECT COALESCE(SUM(freight_value), 0) FROM fact_order_items) AS item_level,
       (SELECT COALESCE(SUM(freight_value), 0) FROM fact_orders)      AS order_level;

-- 3. Payments reconcile between payment grain and order grain
SELECT 'payments_vs_orders' AS check_name,
       (SELECT COALESCE(SUM(payment_value), 0) FROM fact_payments) AS payment_level,
       (SELECT COALESCE(SUM(payment_value), 0) FROM fact_orders)   AS order_level;

-- 4. vw_revenue_orders has exactly one row per revenue order
SELECT 'revenue_orders_unique' AS check_name,
       COUNT(*) - COUNT(DISTINCT order_id) AS violations
FROM vw_revenue_orders;

-- 5. vw_order_review has exactly one row per order
SELECT 'order_review_unique' AS check_name,
       COUNT(*) - COUNT(DISTINCT order_id) AS violations
FROM vw_order_review;

-- 6. order_total_value = items_value + freight_value
SELECT 'order_total_definition' AS check_name, COUNT(*) AS violations
FROM fact_orders
WHERE ABS(order_total_value - (items_value + freight_value)) > 0.01;

-- 7. item_count matches the number of item rows
SELECT 'item_count_matches' AS check_name, COUNT(*) AS violations
FROM fact_orders o
WHERE o.item_count <> (SELECT COUNT(*) FROM fact_order_items i WHERE i.order_id = o.order_id);

-- 8. Delivery flags are internally consistent
SELECT 'delivery_flag_consistency' AS check_name, COUNT(*) AS violations
FROM fact_orders
WHERE (is_late IS NOT NULL AND NOT has_valid_delivery_dates)
   OR (has_valid_delivery_dates AND (is_late IS NULL OR delivery_delay_days IS NULL))
   OR (is_late IS NOT NULL AND is_late <> (delivery_delay_days > 0));

-- 9. A customer_unique_id never maps to a different state within dim_customers
SELECT 'customer_unique_one_row' AS check_name,
       COUNT(*) - COUNT(DISTINCT customer_unique_id) AS violations
FROM dim_customers;
