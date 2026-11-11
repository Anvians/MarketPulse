"""Seeded SYNTHETIC marketplace (not Olist data) big enough to exercise every page's real code path
(forecast, cohorts, delivery model, tests, text terms). Late delivery is planted to depend on distance
and the promised delivery time; negative reviews use complaint words. Used only by tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import settings

STATES = {"SP": (-23.55, -46.63), "RJ": (-22.90, -43.20), "MG": (-19.92, -43.94), "BA": (-12.97, -38.50),
          "RS": (-30.03, -51.22), "PE": (-8.05, -34.88), "PR": (-25.43, -49.27)}
CATS = [("cama_mesa_banho", "bed_bath_table"), ("esporte_lazer", "sports_leisure"), ("beleza_saude", "health_beauty"),
        ("informatica_acessorios", "computers_accessories"), ("brinquedos", "toys")]


def write_large_fixture(d: Path, n_orders: int = 6000, seed: int = 7) -> Path:
    rng = np.random.default_rng(seed)
    f = settings.RAW_FILES
    n_cust = int(n_orders * 0.8)
    st = list(STATES)
    zips = {s: f"{10000 + 7000 * i:05d}" for i, s in enumerate(st)}
    pd.DataFrame({"customer_zip_prefix": [zips[s] for s in st]})  # (zip per state)
    cust_state = rng.choice(st, n_cust, p=[.4, .15, .12, .1, .08, .08, .07])
    cust_ids = [f"u{i}" for i in range(n_cust)]
    # orders: each order picks a person; ~8% of orders are repeat purchases
    person = np.concatenate([np.arange(n_cust), rng.integers(0, n_cust, n_orders - n_cust)])
    rng.shuffle(person)
    # purchase time grows over 24 months (2017-01 .. 2018-12) with a bit of seasonality
    month_w = np.linspace(1, 4, 24) * (1 + 0.15 * np.sin(np.arange(24) / 2))
    month = rng.choice(24, n_orders, p=month_w / month_w.sum())
    purchase = pd.to_datetime("2017-01-01") + pd.to_timedelta(month * 30 + rng.integers(0, 28, n_orders), unit="D") + pd.to_timedelta(rng.integers(0, 86400, n_orders), unit="s")
    # first order of a person must be earliest: sort so repeated persons are in time order (customer_id per order)
    sellers = [f"s{i}" for i in range(40)]
    sel_state = rng.choice(st, 40)
    sel_of_order = rng.integers(0, 40, n_orders)
    oc = np.array([cust_state[p] for p in person]); os_ = sel_state[sel_of_order]
    def dist(a, b):
        la1, lo1, la2, lo2 = *STATES[a], *STATES[b]
        return float(np.hypot(la1 - la2, lo1 - lo2) * 111)
    dkm = np.array([dist(a, b) for a, b in zip(oc, os_)])
    est_days = np.clip((8 + dkm / 120 + rng.normal(0, 2, n_orders)).round(), 5, 60)
    logit = -3.4 + 0.0016 * dkm - 0.06 * (est_days - 15)
    late = rng.random(n_orders) < 1 / (1 + np.exp(-logit))
    actual = np.where(late, est_days + rng.integers(1, 12, n_orders), est_days - rng.integers(1, 8, n_orders)).clip(2)
    status = np.where(rng.random(n_orders) < 0.02, "canceled", "delivered")
    oid = [f"o{i}" for i in range(n_orders)]
    orders = pd.DataFrame({
        "order_id": oid, "customer_id": [f"c{i}" for i in range(n_orders)], "order_status": status,
        "order_purchase_timestamp": purchase.strftime("%Y-%m-%d %H:%M:%S"),
        "order_approved_at": (purchase + pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "order_delivered_carrier_date": (purchase + pd.Timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "order_delivered_customer_date": (purchase + pd.to_timedelta(actual, unit="D") + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "order_estimated_delivery_date": (purchase.normalize() + pd.to_timedelta(est_days, unit="D")).strftime("%Y-%m-%d %H:%M:%S")})
    orders.loc[orders["order_status"] == "canceled", ["order_delivered_carrier_date", "order_delivered_customer_date"]] = ""
    customers = pd.DataFrame({"customer_id": orders["customer_id"], "customer_unique_id": [cust_ids[p] for p in person],
                              "customer_zip_code_prefix": [zips[s] for s in oc], "customer_city": [f"city_{s}" for s in oc], "customer_state": oc})
    n_items = rng.choice([1, 2, 3], n_orders, p=[.85, .12, .03])
    rows = []
    for i, k in enumerate(n_items):
        for j in range(k):
            rows.append([oid[i], j + 1, f"p{rng.integers(0, 60)}", sellers[sel_of_order[i]], "2017-01-15 00:00:00",
                         round(float(rng.gamma(2.5, 35)) + 8, 2), round(float(5 + dkm[i] / 90 + rng.random() * 6), 2)])
    items = pd.DataFrame(rows, columns=["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"])
    tot = items.assign(t=items["price"] + items["freight_value"]).groupby("order_id")["t"].sum()
    ptype = rng.choice(["credit_card", "boleto", "voucher", "debit_card"], n_orders, p=[.74, .19, .04, .03])
    payments = pd.DataFrame({"order_id": oid, "payment_sequential": 1, "payment_type": ptype, "payment_installments": rng.integers(1, 8, n_orders),
                             "payment_value": [round(float(tot.get(o, 50.0)), 2) for o in oid]})
    score = np.where(late, rng.choice([1, 2, 3, 4, 5], n_orders, p=[.35, .2, .2, .15, .1]), rng.choice([1, 2, 3, 4, 5], n_orders, p=[.04, .04, .1, .3, .52]))
    neg_c = ["produto atrasou muito não chegou", "demorou demais péssimo atendimento", "entrega atrasada, não recomendo", "produto veio com defeito e atrasou"]
    pos_c = ["ótimo produto chegou rápido", "recomendo, ótima qualidade", "chegou antes do prazo, perfeito", "muito bom, entrega rápida"]
    comment = [(rng.choice(neg_c) if s <= 2 else rng.choice(pos_c) if s >= 4 else "") if rng.random() < 0.4 else "" for s in score]
    reviews = pd.DataFrame({"review_id": [f"r{i}" for i in range(n_orders)], "order_id": oid, "review_score": score, "review_comment_title": "",
                            "review_comment_message": comment, "review_creation_date": (purchase + pd.Timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"),
                            "review_answer_timestamp": (purchase + pd.Timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")})
    pc = [CATS[i % len(CATS)] for i in range(60)]
    products = pd.DataFrame({"product_id": [f"p{i}" for i in range(60)], "product_category_name": [c[0] for c in pc], "product_name_lenght": 40,
                             "product_description_lenght": 300, "product_photos_qty": 2, "product_weight_g": rng.integers(100, 8000, 60),
                             "product_length_cm": 20, "product_height_cm": 10, "product_width_cm": 15})
    sdf = pd.DataFrame({"seller_id": sellers, "seller_zip_code_prefix": [zips[s] for s in sel_state], "seller_city": [f"city_{s}" for s in sel_state], "seller_state": sel_state})
    geo = pd.DataFrame({"geolocation_zip_code_prefix": [zips[s] for s in st], "geolocation_lat": [STATES[s][0] for s in st],
                        "geolocation_lng": [STATES[s][1] for s in st], "geolocation_city": [f"city_{s}" for s in st], "geolocation_state": st})
    trans = pd.DataFrame(CATS, columns=["product_category_name", "product_category_name_english"])
    for key, df in [("customers", customers), ("orders", orders), ("order_items", items), ("payments", payments), ("reviews", reviews),
                    ("products", products), ("sellers", sdf), ("geolocation", geo), ("category_translation", trans)]:
        df.to_csv(d / f[key], index=False)
    return d
