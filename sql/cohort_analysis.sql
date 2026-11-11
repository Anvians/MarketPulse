-- Reference SQL: monthly acquisition cohorts and retention (used again in Milestone 5).
-- Cohort = month of a person's first revenue order; period 0 = that month.
WITH purchases AS (
    SELECT customer_unique_id, date_trunc('month', purchase_ts)::date AS order_month
    FROM fact_orders WHERE is_revenue_order),
first_month AS (
    SELECT customer_unique_id, MIN(order_month) AS cohort_month
    FROM purchases GROUP BY customer_unique_id)
SELECT f.cohort_month,
       ((EXTRACT(YEAR FROM p.order_month) - EXTRACT(YEAR FROM f.cohort_month)) * 12
        + EXTRACT(MONTH FROM p.order_month) - EXTRACT(MONTH FROM f.cohort_month))::int AS months_since_first,
       COUNT(DISTINCT p.customer_unique_id) AS active_customers
FROM purchases p
JOIN first_month f ON f.customer_unique_id = p.customer_unique_id
GROUP BY 1, 2
ORDER BY 1, 2;
