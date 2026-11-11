-- Reference SQL: sales analysis. Product revenue = sum(price) on revenue orders; freight separate.
-- (The Python analytics layer builds equivalent parameterised queries; these are the readable
--  originals used to design and cross-check them. Each file is executed by the test suite.)

-- Monthly revenue, orders, average order value
SELECT d.year_month,
       SUM(i.price)                              AS revenue,
       COUNT(DISTINCT i.order_id)                AS orders,
       ROUND(SUM(i.price) / COUNT(DISTINCT i.order_id), 2) AS avg_order_value
FROM fact_order_items i
JOIN fact_orders o ON o.order_id = i.order_id AND o.is_revenue_order
JOIN dim_date d    ON d.date_key = o.purchase_date_key
GROUP BY d.year_month
ORDER BY d.year_month;

-- Month-over-month growth (use only between months that both have normal volume)
WITH m AS (
    SELECT d.year_month, SUM(i.price) AS revenue
    FROM fact_order_items i
    JOIN fact_orders o ON o.order_id = i.order_id AND o.is_revenue_order
    JOIN dim_date d    ON d.date_key = o.purchase_date_key
    GROUP BY d.year_month)
SELECT year_month, revenue,
       ROUND(100.0 * (revenue / NULLIF(LAG(revenue) OVER (ORDER BY year_month), 0) - 1), 2) AS mom_growth_pct
FROM m ORDER BY year_month;

-- Sales by weekday
SELECT d.iso_weekday, d.weekday_name, SUM(i.price) AS revenue, COUNT(DISTINCT i.order_id) AS orders
FROM fact_order_items i
JOIN fact_orders o ON o.order_id = i.order_id AND o.is_revenue_order
JOIN dim_date d    ON d.date_key = o.purchase_date_key
GROUP BY d.iso_weekday, d.weekday_name
ORDER BY d.iso_weekday;
