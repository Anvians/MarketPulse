"""Global filters (sidebar). Widget state lives in ``st.session_state`` under the
``flt_*`` keys, and the sidebar is rendered on every run (``app.py``), so the
selection persists while the user moves between pages."""
from __future__ import annotations

import streamlit as st

from analytics.base import Filters
from components import data

KEYS = ("flt_dates", "flt_states", "flt_cats", "flt_sellers", "flt_pay", "flt_status")


def _reset() -> None:
    for k in KEYS:
        st.session_state.pop(k, None)


def render_filters() -> Filters:
    """Draw the filter widgets in the current container and return the active ``Filters``."""
    opts = data.filter_options()
    lo, hi = opts["min_date"], opts["max_date"]
    st.markdown("**Filters**")
    dates = None
    if lo and hi:
        dates = st.date_input("Purchase date", value=(lo, hi), min_value=lo, max_value=hi, key="flt_dates",
                              help="Inclusive range on the order purchase date.")
    states = st.multiselect("Customer state", opts["states"], key="flt_states", placeholder="All states")
    cats = st.multiselect("Product category", opts["categories"], key="flt_cats", placeholder="All categories")
    sellers = st.multiselect("Seller", opts["sellers"], key="flt_sellers", placeholder="All sellers",
                             help="Seller ids (hashed in the source data).")
    pay = st.multiselect("Payment type", opts["payment_types"], key="flt_pay", placeholder="All payment types",
                         help="The order's primary payment type (largest payment value).")
    status = st.multiselect("Order status", opts["order_statuses"], key="flt_status", placeholder="All statuses",
                            help="Revenue metrics only ever count non-canceled orders with items, so selecting "
                                 "'canceled' shows zero revenue by definition.")
    st.button("Reset filters", on_click=_reset, width="stretch")

    d_from = d_to = None
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        d_from, d_to = dates
        if d_from == lo:
            d_from = None
        if d_to == hi:
            d_to = None
    f = Filters(date_from=d_from, date_to=d_to, states=tuple(states), categories=tuple(cats),
                sellers=tuple(sellers), payment_types=tuple(pay), order_statuses=tuple(status))
    st.session_state["filters"] = f
    return f


def current() -> Filters:
    """The filters chosen in the sidebar (empty set before the sidebar has rendered)."""
    return st.session_state.get("filters", Filters())
