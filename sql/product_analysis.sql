-- Reference SQL: product / category analysis.

-- Category revenue, units and average order-level review
WITH co AS (
    SELECT p.category_en, i.order_id, SUM(i.price) AS revenue, COUNT(*) AS units
    FROM fact_order_items i
    JOIN fact_orders o   ON o.order_id = i.order_id AND o.is_revenue_order
    JOIN dim_products p  ON p.product_id = i.product_id
    GROUP BY p.category_en, i.order_id)
SELECT co.category_en, SUM(co.revenue) AS revenue, SUM(co.units) AS units,
       COUNT(*) AS orders, ROUND(AVG(r.review_score), 3) AS avg_review_score
FROM co LEFT JOIN vw_order_review r ON r.order_id = co.order_id
GROUP BY co.category_en
ORDER BY revenue DESC;

-- Products with high freight relative to price
SELECT i.product_id, COUNT(*) AS units, SUM(i.price) AS revenue,
       ROUND(SUM(i.freight_value) / NULLIF(SUM(i.price), 0), 3) AS freight_ratio
FROM fact_order_items i
JOIN fact_orders o ON o.order_id = i.order_id AND o.is_revenue_order
GROUP BY i.product_id
HAVING SUM(i.freight_value) / NULLIF(SUM(i.price), 0) >= 0.3
ORDER BY freight_ratio DESC;
