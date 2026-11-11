-- Reference SQL: seller analysis. Delivery and review belong to the whole order, so for
-- multi-seller orders the same outcome is attributed to each seller.

WITH so AS (
    SELECT i.seller_id, i.order_id, SUM(i.price) AS revenue
    FROM fact_order_items i
    JOIN fact_orders o ON o.order_id = i.order_id AND o.is_revenue_order
    GROUP BY i.seller_id, i.order_id)
SELECT so.seller_id,
       COUNT(*)                                          AS orders,
       SUM(so.revenue)                                   AS revenue,
       ROUND(AVG(r.review_score), 3)                     AS avg_review_score,
       COUNT(*) FILTER (WHERE o.has_valid_delivery_dates) AS delivered_orders,
       COUNT(*) FILTER (WHERE o.is_late)                 AS late_orders
FROM so
JOIN fact_orders o          ON o.order_id = so.order_id
LEFT JOIN vw_order_review r ON r.order_id = so.order_id
GROUP BY so.seller_id
ORDER BY revenue DESC;
