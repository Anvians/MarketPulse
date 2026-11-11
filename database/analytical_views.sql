-- MarketPulse analytical views.
--
-- Every view is designed so that consuming it cannot double-count:
--   * order-level views read fact_orders (one row per order);
--   * review data is reduced to ONE review per order (vw_order_review);
--   * item-level views state their grain in a comment.
--
-- Revenue definition: PRODUCT REVENUE = sum(order item price) over "revenue
-- orders" (status not canceled/unavailable AND at least one item). Freight is
-- reported separately. This is not profit: the dataset has no cost data.

-- ONE row per order: the most recent review (by creation, then answer time).
CREATE OR REPLACE VIEW vw_order_review AS
SELECT DISTINCT ON (order_id)
       order_id, review_id, review_score, review_creation_ts, review_answer_ts
FROM fact_reviews
ORDER BY order_id,
         review_creation_ts DESC NULLS LAST,
         review_answer_ts   DESC NULLS LAST,
         review_id;

-- Grain: one row per revenue order.
CREATE OR REPLACE VIEW vw_revenue_orders AS
SELECT o.*, d.year_month, d.calendar_year, d.calendar_quarter, d.iso_weekday, d.weekday_name
FROM fact_orders o
JOIN dim_date d ON d.date_key = o.purchase_date_key
WHERE o.is_revenue_order;

-- Grain: one row per order ITEM (an order with 3 items appears 3 times).
-- Use only for item/product/seller/category analysis; never COUNT(*) as orders.
CREATE OR REPLACE VIEW vw_item_details AS
SELECT i.order_id, i.order_item_id, i.product_id, i.seller_id,
       i.price, i.freight_value,
       o.order_status, o.is_revenue_order, o.purchase_ts, o.purchase_date_key,
       d.year_month, o.customer_unique_id, o.customer_state, o.primary_payment_type,
       p.category_en, p.category_pt, p.weight_g, p.volume_cm3,
       s.state AS seller_state, s.city AS seller_city
FROM fact_order_items i
JOIN fact_orders o          ON o.order_id = i.order_id
LEFT JOIN dim_products p    ON p.product_id = i.product_id
LEFT JOIN dim_sellers s     ON s.seller_id = i.seller_id
LEFT JOIN dim_date d        ON d.date_key = o.purchase_date_key;

-- Grain: one row per purchase month (revenue orders only).
CREATE OR REPLACE VIEW vw_monthly_kpis AS
SELECT d.year_month,
       COUNT(*)                                        AS orders,
       COUNT(DISTINCT o.customer_unique_id)            AS customers,
       SUM(o.items_value)                              AS product_revenue,
       SUM(o.freight_value)                            AS freight_charges,
       SUM(o.order_total_value)                        AS order_total_value,
       ROUND(SUM(o.items_value) / NULLIF(COUNT(*), 0), 2) AS avg_order_value,
       ROUND(AVG(r.review_score), 3)                   AS avg_review_score
FROM fact_orders o
JOIN dim_date d              ON d.date_key = o.purchase_date_key
LEFT JOIN vw_order_review r  ON r.order_id = o.order_id
WHERE o.is_revenue_order
GROUP BY d.year_month;

-- Grain: one row per DELIVERED order with consistent dates.
CREATE OR REPLACE VIEW vw_delivery_performance AS
SELECT o.order_id, o.customer_state, d.year_month AS purchase_month,
       o.delivery_days, o.estimated_delivery_days, o.delivery_delay_days,
       o.is_late, o.freight_value, r.review_score
FROM fact_orders o
JOIN dim_date d              ON d.date_key = o.purchase_date_key
LEFT JOIN vw_order_review r  ON r.order_id = o.order_id
WHERE o.has_valid_delivery_dates;

-- Grain: one row per customer (person) with at least one revenue order.
CREATE OR REPLACE VIEW vw_customer_summary AS
SELECT c.customer_unique_id, c.state, c.city,
       COUNT(o.order_id)          AS orders,
       SUM(o.items_value)         AS product_revenue,
       SUM(o.freight_value)       AS freight_charges,
       MIN(o.purchase_ts)         AS first_purchase_ts,
       MAX(o.purchase_ts)         AS last_purchase_ts,
       (COUNT(o.order_id) > 1)    AS is_repeat_customer
FROM dim_customers c
JOIN fact_orders o
  ON o.customer_unique_id = c.customer_unique_id AND o.is_revenue_order
GROUP BY c.customer_unique_id, c.state, c.city;

-- Grain: one row per seller with at least one revenue order.
-- avg_review_score uses the ORDER-level review, so for multi-seller orders the
-- same review is attributed to each seller on the order.
CREATE OR REPLACE VIEW vw_seller_summary AS
WITH seller_orders AS (
    SELECT i.seller_id, i.order_id,
           SUM(i.price) AS revenue, SUM(i.freight_value) AS freight, COUNT(*) AS items
    FROM fact_order_items i
    JOIN fact_orders o ON o.order_id = i.order_id
    WHERE o.is_revenue_order
    GROUP BY i.seller_id, i.order_id
)
SELECT s.seller_id, s.state, s.city,
       COUNT(so.order_id)                                  AS orders,
       SUM(so.items)                                       AS items_sold,
       SUM(so.revenue)                                     AS product_revenue,
       SUM(so.freight)                                     AS freight_charges,
       ROUND(AVG(r.review_score), 3)                       AS avg_review_score,
       COUNT(*) FILTER (WHERE o.has_valid_delivery_dates)  AS delivered_orders,
       COUNT(*) FILTER (WHERE o.is_late)                   AS late_orders
FROM dim_sellers s
JOIN seller_orders so        ON so.seller_id = s.seller_id
JOIN fact_orders o           ON o.order_id = so.order_id
LEFT JOIN vw_order_review r  ON r.order_id = so.order_id
GROUP BY s.seller_id, s.state, s.city;

-- Grain: one row per product category (revenue orders only).
-- orders = distinct orders containing the category; an order spanning two
-- categories counts once in each.
CREATE OR REPLACE VIEW vw_category_summary AS
WITH category_orders AS (
    SELECT p.category_en, i.order_id,
           SUM(i.price) AS revenue, SUM(i.freight_value) AS freight, COUNT(*) AS items
    FROM fact_order_items i
    JOIN fact_orders o   ON o.order_id = i.order_id
    JOIN dim_products p  ON p.product_id = i.product_id
    WHERE o.is_revenue_order
    GROUP BY p.category_en, i.order_id
)
SELECT co.category_en,
       COUNT(*)                                          AS orders,
       SUM(co.items)                                     AS items_sold,
       SUM(co.revenue)                                   AS product_revenue,
       SUM(co.freight)                                   AS freight_charges,
       ROUND(SUM(co.revenue) / NULLIF(SUM(co.items), 0), 2) AS avg_item_price,
       ROUND(AVG(r.review_score), 3)                     AS avg_review_score
FROM category_orders co
LEFT JOIN vw_order_review r ON r.order_id = co.order_id
GROUP BY co.category_en;
