"""Single source of truth for every KPI shown in the app.

Each KPI documents its formula, denominator and null handling; the UI shows
them as the card tooltip and on the Data Quality page, and a test checks that
every KPI used by a page is defined here. Rates are shown as percentages in the
UI but computed as fractions. Revenue is *product revenue* (not profit).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KPIDefinition:
    label: str
    formula: str
    denominator: str
    null_handling: str

    def tooltip(self) -> str:
        return f"{self.formula}\n\nDenominator: {self.denominator}\nMissing data: {self.null_handling}"


_REV = "Only revenue orders count: status not canceled/unavailable and at least one item."
_DELIV = "Only delivered orders with consistent purchase, delivery and estimated dates count."
_NA = "Shown as n/a when the denominator is zero (never as 0)."

KPI_DEFINITIONS: dict[str, KPIDefinition] = {
    # ---- executive / revenue / sales
    "total_revenue": KPIDefinition("Total revenue", "Sum of item price over revenue orders. Excludes freight. Revenue is not profit: the data has no costs.", "n/a", _REV),
    "total_orders": KPIDefinition("Total orders", "Count of distinct revenue orders.", "n/a", _REV),
    "total_customers": KPIDefinition("Total customers", "Distinct people (customer_unique_id) with at least one revenue order.", "n/a", _REV),
    "avg_order_value": KPIDefinition("Average order value", "Total revenue ÷ total orders (product revenue, freight excluded).", "Distinct revenue orders", _NA),
    "avg_customer_revenue": KPIDefinition("Average customer revenue", "Total revenue ÷ total customers (observed in the data period).", "Distinct customers", _NA),
    "avg_review_score": KPIDefinition("Average review score", "Mean of the latest review score (1-5) of each revenue order.", "Revenue orders that have a review", "Orders without a review are excluded."),
    "repeat_purchase_rate": KPIDefinition("Repeat purchase rate", "Customers with more than one revenue order ÷ customers with at least one revenue order.", "Customers with ≥ 1 revenue order", _NA),
    "on_time_delivery_rate": KPIDefinition("On-time delivery rate", "Delivered orders arriving on or before the estimated delivery date ÷ delivered orders with valid dates. Dates are compared, not clock times.", "Delivered orders with valid dates", _DELIV),
    "late_delivery_rate": KPIDefinition("Late delivery rate", "Delivered orders arriving after the estimated delivery date ÷ delivered orders with valid dates.", "Delivered orders with valid dates", _DELIV),
    "revenue_growth": KPIDefinition("Revenue growth", "Latest month's revenue ÷ previous month's revenue − 1, using the two most recent months that are not near-empty. Observed history, not a forecast.", "Previous month's revenue", "Near-empty edge months (< 10% of the median month's orders) are skipped; n/a with fewer than two usable months."),
    "revenue_per_customer": KPIDefinition("Revenue per customer", "Total revenue ÷ distinct customers.", "Distinct customers", _NA),
    "freight_charges": KPIDefinition("Freight charges", "Sum of item freight value over revenue orders. Reported separately; never added to revenue.", "n/a", _REV),
    "top_category_share": KPIDefinition("Top category share", "Revenue of the largest category ÷ total revenue.", "Total revenue", _NA),
    "avg_items_per_order": KPIDefinition("Average items per order", "Items sold ÷ distinct revenue orders.", "Distinct revenue orders", _NA),
    "avg_freight_value": KPIDefinition("Average freight per order", "Total freight ÷ distinct revenue orders.", "Distinct revenue orders", _NA),
    "monthly_growth": KPIDefinition("Latest monthly growth", "Revenue change of the latest month vs the month before (month-over-month).", "Previous month's revenue", "n/a when either month is near-empty."),
    "daily_avg_orders": KPIDefinition("Daily average orders", "Revenue orders ÷ calendar days from the first to the last purchase in scope (days without sales count).", "Calendar days in range", _NA),
    # ---- products
    "products_sold": KPIDefinition("Products sold", "Distinct products with at least one item on a revenue order.", "n/a", _REV),
    "product_categories": KPIDefinition("Product categories", "Distinct English category names among items sold.", "n/a", _REV),
    "avg_product_price": KPIDefinition("Average product price", "Mean item price over items sold (item-weighted).", "Items sold", _NA),
    "top_revenue_category": KPIDefinition("Highest revenue category", "Category with the largest product revenue.", "n/a", _REV),
    "best_selling_category": KPIDefinition("Best-selling category", "Category with the most units sold.", "n/a", _REV),
    "avg_product_review_score": KPIDefinition("Average product review score", "Mean latest review score of revenue orders in scope.", "Revenue orders with a review", "Orders without a review are excluded."),
    # ---- customers
    "new_customers": KPIDefinition("New customers", "People whose first-ever revenue order falls inside the filters.", "n/a", "First purchase uses all data, so a returning buyer is never counted as new."),
    "repeat_customers": KPIDefinition("Repeat customers", "People with more than one revenue order inside the filters.", "n/a", _REV),
    "avg_orders_per_customer": KPIDefinition("Average orders per customer", "Revenue orders ÷ distinct customers.", "Distinct customers", _NA),
    "observed_lifetime_revenue": KPIDefinition("Customer lifetime revenue (median)", "Median revenue per customer over the data period. Observed, not predicted.", "Distinct customers", _NA),
    # ---- satisfaction
    "total_reviews": KPIDefinition("Total reviews", "Revenue orders with a review (one - the latest - per order).", "n/a", "Orders without a review are not counted."),
    "one_star_reviews": KPIDefinition("One-star reviews", "Orders whose review score is 1.", "n/a", "n/a"),
    "two_star_reviews": KPIDefinition("Two-star reviews", "Orders whose review score is 2.", "n/a", "n/a"),
    "five_star_reviews": KPIDefinition("Five-star reviews", "Orders whose review score is 5.", "n/a", "n/a"),
    "negative_review_rate": KPIDefinition("Negative review rate", "Reviews scored 1 or 2 ÷ scored reviews.", "Scored reviews", _NA),
    # ---- sellers
    "total_sellers": KPIDefinition("Total sellers", "All registered sellers, including those with no orders.", "n/a", "n/a"),
    "sellers_with_orders": KPIDefinition("Sellers with orders", "Sellers with at least one revenue order inside the filters.", "n/a", _REV),
    "avg_orders_per_seller": KPIDefinition("Average orders per seller", "Seller-orders ÷ sellers with orders. An order with several sellers counts for each.", "Sellers with orders", _NA),
    "avg_seller_revenue": KPIDefinition("Average seller revenue", "Total product revenue ÷ sellers with orders.", "Sellers with orders", _NA),
    "avg_seller_review_score": KPIDefinition("Average seller review score", "Mean of each seller's average review score (every seller counts once).", "Sellers with at least one review", "Sellers without reviews are excluded."),
    "seller_late_rate": KPIDefinition("Seller late delivery rate", "Late seller-orders ÷ seller-orders with valid delivery dates (pooled over sellers).", "Seller-orders with valid dates", _DELIV),
    # ---- logistics
    "delivered_orders": KPIDefinition("Delivered orders", "Orders with status 'delivered'.", "n/a", "Includes delivered orders whose dates are inconsistent; rates use only valid ones."),
    "on_time_deliveries": KPIDefinition("On-time deliveries", "Delivered orders arriving on or before the estimated date.", "n/a", _DELIV),
    "late_deliveries": KPIDefinition("Late deliveries", "Delivered orders arriving after the estimated date.", "n/a", _DELIV),
    "avg_delivery_time": KPIDefinition("Average delivery time", "Mean days from purchase to delivery.", "Delivered orders with valid dates", _DELIV),
    "avg_delivery_delay": KPIDefinition("Average delivery delay", "Mean (delivered date − estimated date) in days. Negative = earlier than estimated.", "Delivered orders with valid dates", _DELIV),
    "avg_freight_cost": KPIDefinition("Average freight cost", "Mean order-level freight on validly delivered orders.", "Delivered orders with valid dates", _DELIV),
    # ---- geography
    "total_states": KPIDefinition("States", "Distinct customer states with revenue orders.", "n/a", _REV),
    "customer_cities": KPIDefinition("Customer cities", "Distinct (city, state) pairs of customers with revenue orders.", "n/a", _REV),
    "seller_cities": KPIDefinition("Seller cities", "Distinct (city, state) pairs of sellers with revenue orders.", "n/a", _REV),
    "top_revenue_state": KPIDefinition("Highest revenue state", "Customer state with the largest product revenue.", "n/a", _REV),
    "top_customer_state": KPIDefinition("Highest customer concentration", "Customer state holding the largest share of customers.", "Customers across all states", _REV),
}


def get_definition(key: str) -> KPIDefinition:
    """Definition for ``key``; raises KeyError with a helpful message when missing."""
    try:
        return KPI_DEFINITIONS[key]
    except KeyError as exc:
        raise KeyError(f"KPI {key!r} has no entry in config/kpi_definitions.py") from exc
