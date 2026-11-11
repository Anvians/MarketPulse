# MarketPulse: project summary (for portfolio and interviews)

**One line:** an end-to-end business-intelligence platform on 100k real marketplace orders: validated ingestion → PostgreSQL star
schema → tested analytics engine → 18-page Streamlit app with filters, exports, rule-based findings and honestly evaluated ML.

## What to say about it
1. **Correctness over decoration.** The first milestone is reconciliation: item, payment and order totals are checked so a join can never
   silently double count. Lateness, revenue and "customer" are defined once, documented, and tested against hand-computed fixtures.
2. **Things it refuses to claim.** Revenue is never "profit"; no inventory claims; the 2016–2018 limitation is on every page; the
   forecast page tells you when the model loses to "same as last month"; the delivery model says "not informative" when it is.
3. **Transparent rules.** Opportunities and insights are threshold rules with the evidence attached, not canned advice.
4. **Engineering habits.** UI-free analytics layer, parameterised SQL, env-based secrets, an automated test suite (284 tests at release) (including headless tests of
   every page), CI workflow, Docker Compose setup, generated reference docs that fail the build if they drift.

## Numbers you can quote (from your own run on the full dataset)
* Orders loaded: 99,441; revenue reconciliation passed.
* Product revenue R$ 13,494,400.74 over 98,199 revenue orders; 94,983 customers; average order value R$ 137.42.
* Repeat-purchase rate 3.04%; on-time delivery 93.23%, late 6.77% (date-based definition); average review 4.12.

Re-read these from the app (Executive Dashboard) after any reload; quote only what you see on your machine.

## Good talking points / likely questions
* *Why is repeat purchase so low?* It is a marketplace with mostly one-off buyers; the app shows it rather than inflating retention.
* *Why 6.8% late when others quote ~8%?* Date-based vs timestamp-based comparison; the definition is documented. A timestamp-based variant is not implemented.
* *How do you avoid double counting?* Order-grain fact table plus item/order scopes and reconciliation checks (see ARCHITECTURE.md).
* *How do you know the model is not leaking?* Purchase-time-only feature list, enforced by a test; time-ordered split.
* *What would you do next?* Add a configurable late-delivery definition, add seller-level seasonality, richer logistics features
  (carrier lead time), and a scheduled refresh; none of these is claimed as built.
