"""Expected structure of the raw Olist files and of the warehouse tables.

NOTE: the raw column lists below follow the published Olist dataset layout.
The pipeline verifies them against the real CSV headers on every run
(see ``load_data.validate_expected_columns``) and fails loudly on a mismatch.
"""
from __future__ import annotations

RAW_EXPECTED_COLUMNS: dict[str, list[str]] = {
    "customers": [
        "customer_id", "customer_unique_id", "customer_zip_code_prefix",
        "customer_city", "customer_state",
    ],
    "orders": [
        "order_id", "customer_id", "order_status", "order_purchase_timestamp",
        "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date",
    ],
    "order_items": [
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value",
    ],
    "payments": [
        "order_id", "payment_sequential", "payment_type",
        "payment_installments", "payment_value",
    ],
    "reviews": [
        "review_id", "order_id", "review_score", "review_comment_title",
        "review_comment_message", "review_creation_date", "review_answer_timestamp",
    ],
    "products": [
        "product_id", "product_category_name", "product_name_lenght",
        "product_description_lenght", "product_photos_qty", "product_weight_g",
        "product_length_cm", "product_height_cm", "product_width_cm",
    ],
    "sellers": ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    "geolocation": [
        "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
        "geolocation_city", "geolocation_state",
    ],
    "category_translation": ["product_category_name", "product_category_name_english"],
}

# Natural key of each RAW table (used to report duplicates before cleaning).
RAW_PRIMARY_KEYS: dict[str, list[str]] = {
    "customers": ["customer_id"],
    "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "payments": ["order_id", "payment_sequential"],
    "reviews": ["review_id", "order_id"],
    "products": ["product_id"],
    "sellers": ["seller_id"],
    "category_translation": ["product_category_name"],
}

# Warehouse tables in dependency (load) order.
WAREHOUSE_LOAD_ORDER: list[str] = [
    "dim_date", "dim_geolocation", "dim_customers", "dim_products", "dim_sellers",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
]

WAREHOUSE_PRIMARY_KEYS: dict[str, list[str]] = {
    "dim_date": ["date_key"],
    "dim_geolocation": ["zip_prefix"],
    "dim_customers": ["customer_unique_id"],
    "dim_products": ["product_id"],
    "dim_sellers": ["seller_id"],
    "fact_orders": ["order_id"],
    "fact_order_items": ["order_id", "order_item_id"],
    "fact_payments": ["order_id", "payment_sequential"],
    "fact_reviews": ["review_id", "order_id"],
}

# (child_table, child_column, parent_table, parent_column) - enforced in SQL.
WAREHOUSE_FOREIGN_KEYS: list[tuple[str, str, str, str]] = [
    ("fact_orders", "customer_unique_id", "dim_customers", "customer_unique_id"),
    ("fact_orders", "purchase_date_key", "dim_date", "date_key"),
    ("fact_orders", "delivered_date_key", "dim_date", "date_key"),
    ("fact_order_items", "order_id", "fact_orders", "order_id"),
    ("fact_order_items", "product_id", "dim_products", "product_id"),
    ("fact_order_items", "seller_id", "dim_sellers", "seller_id"),
    ("fact_payments", "order_id", "fact_orders", "order_id"),
    ("fact_reviews", "order_id", "fact_orders", "order_id"),
]

# Soft relationships (reported, not enforced): zip prefix coverage in geolocation.
WAREHOUSE_SOFT_KEYS: list[tuple[str, str, str, str]] = [
    ("dim_customers", "zip_prefix", "dim_geolocation", "zip_prefix"),
    ("dim_sellers", "zip_prefix", "dim_geolocation", "zip_prefix"),
]

# Expected value "kind" per column, checked by validate_data.check_data_types.
# kinds: string | integer | float | datetime | boolean
WAREHOUSE_COLUMN_KINDS: dict[str, dict[str, str]] = {
    "fact_orders": {
        "order_id": "string", "customer_unique_id": "string", "order_status": "string",
        "purchase_ts": "datetime", "customer_delivery_ts": "datetime",
        "estimated_delivery_date": "datetime",
        "item_count": "integer", "items_value": "float", "freight_value": "float",
        "order_total_value": "float", "delivery_days": "float",
        "delivery_delay_days": "integer", "is_late": "boolean",
        "is_revenue_order": "boolean", "has_valid_delivery_dates": "boolean",
    },
    "fact_order_items": {
        "order_id": "string", "order_item_id": "integer", "product_id": "string",
        "seller_id": "string", "price": "float", "freight_value": "float",
        "shipping_limit_ts": "datetime",
    },
    "fact_payments": {
        "order_id": "string", "payment_sequential": "integer",
        "payment_type": "string", "payment_value": "float",
    },
    "fact_reviews": {
        "review_id": "string", "order_id": "string", "review_score": "integer",
        "review_creation_ts": "datetime", "review_answer_ts": "datetime",
    },
    "dim_products": {
        "product_id": "string", "category_en": "string", "weight_g": "float",
        "volume_cm3": "float",
    },
}
