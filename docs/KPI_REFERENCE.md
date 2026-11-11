# KPI reference

Generated from `config/kpi_definitions.py` by `python -m scripts.generate_docs` (do not edit by hand). The same text is the tooltip on every KPI card. Revenue means product revenue (item prices on non-canceled orders with at least one item); it is not profit.

| KPI | Formula | Denominator | Missing / empty data |
|---|---|---|---|
| Total revenue | Sum of item price over revenue orders. Excludes freight. Revenue is not profit: the data has no costs. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Total orders | Count of distinct revenue orders. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Total customers | Distinct people (customer_unique_id) with at least one revenue order. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Average order value | Total revenue ÷ total orders (product revenue, freight excluded). | Distinct revenue orders | Shown as n/a when the denominator is zero (never as 0). |
| Average customer revenue | Total revenue ÷ total customers (observed in the data period). | Distinct customers | Shown as n/a when the denominator is zero (never as 0). |
| Average review score | Mean of the latest review score (1-5) of each revenue order. | Revenue orders that have a review | Orders without a review are excluded. |
| Repeat purchase rate | Customers with more than one revenue order ÷ customers with at least one revenue order. | Customers with ≥ 1 revenue order | Shown as n/a when the denominator is zero (never as 0). |
| On-time delivery rate | Delivered orders arriving on or before the estimated delivery date ÷ delivered orders with valid dates. Dates are compared, not clock times. | Delivered orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Late delivery rate | Delivered orders arriving after the estimated delivery date ÷ delivered orders with valid dates. | Delivered orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Revenue growth | Latest month's revenue ÷ previous month's revenue − 1, using the two most recent months that are not near-empty. Observed history, not a forecast. | Previous month's revenue | Near-empty edge months (< 10% of the median month's orders) are skipped; n/a with fewer than two usable months. |
| Revenue per customer | Total revenue ÷ distinct customers. | Distinct customers | Shown as n/a when the denominator is zero (never as 0). |
| Freight charges | Sum of item freight value over revenue orders. Reported separately; never added to revenue. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Top category share | Revenue of the largest category ÷ total revenue. | Total revenue | Shown as n/a when the denominator is zero (never as 0). |
| Average items per order | Items sold ÷ distinct revenue orders. | Distinct revenue orders | Shown as n/a when the denominator is zero (never as 0). |
| Average freight per order | Total freight ÷ distinct revenue orders. | Distinct revenue orders | Shown as n/a when the denominator is zero (never as 0). |
| Latest monthly growth | Revenue change of the latest month vs the month before (month-over-month). | Previous month's revenue | n/a when either month is near-empty. |
| Daily average orders | Revenue orders ÷ calendar days from the first to the last purchase in scope (days without sales count). | Calendar days in range | Shown as n/a when the denominator is zero (never as 0). |
| Products sold | Distinct products with at least one item on a revenue order. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Product categories | Distinct English category names among items sold. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Average product price | Mean item price over items sold (item-weighted). | Items sold | Shown as n/a when the denominator is zero (never as 0). |
| Highest revenue category | Category with the largest product revenue. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Best-selling category | Category with the most units sold. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Average product review score | Mean latest review score of revenue orders in scope. | Revenue orders with a review | Orders without a review are excluded. |
| New customers | People whose first-ever revenue order falls inside the filters. | n/a | First purchase uses all data, so a returning buyer is never counted as new. |
| Repeat customers | People with more than one revenue order inside the filters. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Average orders per customer | Revenue orders ÷ distinct customers. | Distinct customers | Shown as n/a when the denominator is zero (never as 0). |
| Customer lifetime revenue (median) | Median revenue per customer over the data period. Observed, not predicted. | Distinct customers | Shown as n/a when the denominator is zero (never as 0). |
| Total reviews | Revenue orders with a review (one - the latest - per order). | n/a | Orders without a review are not counted. |
| One-star reviews | Orders whose review score is 1. | n/a | n/a |
| Two-star reviews | Orders whose review score is 2. | n/a | n/a |
| Five-star reviews | Orders whose review score is 5. | n/a | n/a |
| Negative review rate | Reviews scored 1 or 2 ÷ scored reviews. | Scored reviews | Shown as n/a when the denominator is zero (never as 0). |
| Total sellers | All registered sellers, including those with no orders. | n/a | n/a |
| Sellers with orders | Sellers with at least one revenue order inside the filters. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Average orders per seller | Seller-orders ÷ sellers with orders. An order with several sellers counts for each. | Sellers with orders | Shown as n/a when the denominator is zero (never as 0). |
| Average seller revenue | Total product revenue ÷ sellers with orders. | Sellers with orders | Shown as n/a when the denominator is zero (never as 0). |
| Average seller review score | Mean of each seller's average review score (every seller counts once). | Sellers with at least one review | Sellers without reviews are excluded. |
| Seller late delivery rate | Late seller-orders ÷ seller-orders with valid delivery dates (pooled over sellers). | Seller-orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Delivered orders | Orders with status 'delivered'. | n/a | Includes delivered orders whose dates are inconsistent; rates use only valid ones. |
| On-time deliveries | Delivered orders arriving on or before the estimated date. | n/a | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Late deliveries | Delivered orders arriving after the estimated date. | n/a | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Average delivery time | Mean days from purchase to delivery. | Delivered orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Average delivery delay | Mean (delivered date − estimated date) in days. Negative = earlier than estimated. | Delivered orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| Average freight cost | Mean order-level freight on validly delivered orders. | Delivered orders with valid dates | Only delivered orders with consistent purchase, delivery and estimated dates count. |
| States | Distinct customer states with revenue orders. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Customer cities | Distinct (city, state) pairs of customers with revenue orders. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Seller cities | Distinct (city, state) pairs of sellers with revenue orders. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Highest revenue state | Customer state with the largest product revenue. | n/a | Only revenue orders count: status not canceled/unavailable and at least one item. |
| Highest customer concentration | Customer state holding the largest share of customers. | Customers across all states | Only revenue orders count: status not canceled/unavailable and at least one item. |
