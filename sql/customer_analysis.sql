-- Reference SQL: customer analysis. A customer is a person (customer_unique_id).

-- Repeat purchase rate
WITH c AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM fact_orders WHERE is_revenue_order
    GROUP BY customer_unique_id)
SELECT COUNT(*) FILTER (WHERE orders > 1)                       AS repeat_customers,
       COUNT(*)                                                 AS customers,
       ROUND(1.0 * COUNT(*) FILTER (WHERE orders > 1) / COUNT(*), 4) AS repeat_purchase_rate
FROM c;

-- New customers per month (month of first-ever revenue order)
SELECT to_char(first_ts, 'YYYY-MM') AS first_month, COUNT(*) AS new_customers
FROM (SELECT customer_unique_id, MIN(purchase_ts) AS first_ts
      FROM fact_orders WHERE is_revenue_order GROUP BY customer_unique_id) f
GROUP BY 1 ORDER BY 1;

-- Orders-per-customer distribution
SELECT orders, COUNT(*) AS customers
FROM (SELECT customer_unique_id, COUNT(*) AS orders
      FROM fact_orders WHERE is_revenue_order GROUP BY customer_unique_id) c
GROUP BY orders ORDER BY orders;
