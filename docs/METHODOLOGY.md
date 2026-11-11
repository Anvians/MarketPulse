# Methodology and limitations

## What the data is
The Olist Brazilian E-Commerce Public Dataset: ~100k orders placed on a Brazilian marketplace between
2016 and 2018 (almost all in 2017–2018). **Everything in MarketPulse describes that historical period.**
It is not current business performance, and every page says so.

## What the data cannot tell you
* **No costs, so no profit or margin.** "Revenue" is product revenue (item prices). Freight is reported separately.
* **No inventory or stock data.** Nothing here speaks to availability or replenishment.
* **No marketing, traffic or price-history data.** Causes of change cannot be identified; findings are prompts to investigate.
* **Anonymised ids.** Sellers, customers and orders are hashes; geography is zip prefix, city and state.
* **Only a minority of reviews carry a written comment**, and commenters are not a random sample of customers.
* **Sparse edge months.** The first and last months hold very few orders. They are flagged and excluded from growth rates
  (a month under 10% of the median monthly orders).

## Definitions in one place
| Term | Definition |
|---|---|
| Revenue order | status not `canceled`/`unavailable` and at least one item |
| Product revenue | sum of item `price` over revenue orders (freight excluded) |
| Customer | a person, `customer_unique_id` |
| Repeat purchase rate | customers with ≥ 2 revenue orders / customers with ≥ 1 (within the active filters) |
| Late delivery | delivered date later than estimated date; only delivered orders with valid dates |
| Negative review | score 1 or 2; one review per order (the latest) |
| Order value | sum of item prices of the order (freight excluded) |

Full KPI formulas, denominators and missing-data handling: [KPI_REFERENCE.md](KPI_REFERENCE.md).
Column-level data dictionary and transformations: [../data/DATA_DICTIONARY.md](../data/DATA_DICTIONARY.md).
Rule thresholds: [THRESHOLDS.md](THRESHOLDS.md).

## Filters
Date (purchase date, inclusive), customer state, product category, seller, primary payment type and order status.
Revenue metrics always exclude non-revenue orders, so filtering to `canceled` shows zero revenue by definition.
With a date filter, "repeat" means more than one purchase *inside the window*; "new customer" uses each person's
first-ever purchase, so a returning buyer is never mislabelled new.

## Rule-based findings
Opportunity, growth and insight rules are explicit comparisons against thresholds (e.g. late rate ≥ 1.5× the overall rate
with enough orders). Each finding states its rule and evidence. Opportunities are ranked by the **observed revenue of the entity
involved**, which sizes what to look at; it is not an estimate of gain.

## Advanced methods and their guard rails
| Method | Guard rails |
|---|---|
| RFM segments | Recency from the last purchase in scope (not today); frequency scored 1/2/3 because ~97% buy once; fixed published rules |
| K-means | Seeded; log-scaled, standardised R/F/M; k chosen by silhouette in 2–6; clusters described by averages only |
| Cohort retention | Cohorts under 100 customers show n/a; same-month repeat is not retention; months beyond the data are excluded |
| Revenue forecast | Damped-trend smoothing; no seasonality (about two years of history); rolling one-month-ahead backtest against the naive rule; page states when the model loses |
| Delivery risk | Purchase-time features only (a test forbids leaking columns); time split; baseline; "not informative" below AUC 0.60 |
| Statistical tests | Effect size first; no causal wording; no multiple-comparison correction (stated) |
| Review text | Term association, **not** sentiment; Portuguese stopwords; accents folded; minimum term count |

## Reproducibility
Fixed seed (`ML_RANDOM_STATE = 42`) for every stochastic step. Results depend only on the loaded data and the filters.
