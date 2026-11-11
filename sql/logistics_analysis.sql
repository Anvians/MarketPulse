-- Reference SQL: logistics analysis. Only orders with valid delivery dates are used.

-- Delivery KPIs
SELECT COUNT(*)                                             AS delivered_orders,
       COUNT(*) FILTER (WHERE NOT is_late)                  AS on_time,
       COUNT(*) FILTER (WHERE is_late)                      AS late,
       ROUND(1.0 * COUNT(*) FILTER (WHERE is_late) / COUNT(*), 4) AS late_rate,
       ROUND(AVG(delivery_days), 2)                         AS avg_delivery_days,
       ROUND(AVG(delivery_delay_days), 2)                   AS avg_delay_days
FROM fact_orders WHERE has_valid_delivery_dates;

-- Late rate by customer state
SELECT customer_state,
       COUNT(*) AS orders,
       ROUND(AVG(CASE WHEN is_late THEN 1.0 ELSE 0.0 END), 4) AS late_rate,
       ROUND(AVG(delivery_days), 2) AS avg_delivery_days
FROM fact_orders WHERE has_valid_delivery_dates
GROUP BY customer_state
ORDER BY late_rate DESC;
