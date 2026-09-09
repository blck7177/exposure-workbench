# Gaps met writing slice B programs (V26 battery, program language V30)

Each entry: what the turn needs, what was tried, what came back, how the program covers it meanwhile.

## G1. No vector can be built from per-issuer scalars, so no `rank` across issuers for a figure without a method
- Needs it: W04-growth-vs-margin-screen#t1 (order the hits worst-first by margin change), W02-buyback-vs-dilution#t2 ("who's worst" by share-count yoy / SBC-to-buybacks), W04-book-capex-hogs#t1 (capex ÷ OCF per issuer, heaviest first), W01-useful-life-policy#t1 (whose profit leans hardest on depreciation), W05-leases-in-leverage#t2 (does the order change with leases in).
- Tried: `method` over a list gives a vector only for a registered method; arithmetic over scalars from different tickers yields scalars with no label; `rank` on a scalar refuses (`type_mismatch`). There is no primitive that gathers named scalars into a vector.
- Now: each program returns the per-issuer scalars and the note says the order is read off them, not off a rank node. Rule 3 ("a superlative rests on a rank node") cannot be met for these turns.
- Fix that would close it: a `vector` primitive `{"fn": "vector", "entries": {"MSFT": "$a", "AMZN": "$b", ...}}` (same unit required), so `rank`/`top`/`avg` apply.

## G2. No series arithmetic (series ∘ series, series ∘ scalar)
- Needs it: gross margin as a series for issuers that file cost_of_revenue but not gross_profit (GOOGL/AMZN/LLY, W04-growth#t1), capex ÷ OCF over quarters (W04-capex#t1/t2), dividends ÷ FCF quarter by quarter (W01-xom-payout-plug#t2/t3), effective tax rate = tax ÷ pretax as a series (W06-tax-rate-growth#t1), depreciation ÷ revenue over years (W01-useful-life#t1/t3).
- Tried: `div` with two series → `type_mismatch: $x is a series; an arithmetic operand is a figure or a vector of figures`.
- Now: two windows per issuer via `start`/`end` (or `at` on a method series) and scalar arithmetic; the trend is shown as two points, not a line. For the tax rate, the registered `tax_burden` series (net ÷ pretax) stands in as 1 − rate.

## G3. A `latest`/`min` of a series cannot be combined with the same issuer's other figures
- Needs it: W01-xom-payout-plug#t1 (latest quarter's FCF minus that quarter's buybacks + dividends).
- Tried: `sub(latest(fcf_q), add(latest(bb_q), latest(div_q)))` → `mixed_basis_operand: calc_… is a sum across several periods () and shares an issuer with calc_…; combine it only with other issuers' quantities, or rebuild the sum from single-period parts`. The `latest` node is typed as an aggregate over periods although it is one period's figure.
- Now: the latest quarter is read directly (`months: 3`) and the series is returned beside it for the trend. Note that `div(nd, min(ebitda_s))` in W03-xom-trough-relever#t1 does settle, so the refusal is specific to combining a series-op result with an `add` on the same issuer.

## G4. No per-position contribution on a run; `book.explain_episode` refuses a one-day window
- Needs it: W05-explain-the-day#t1 ("what did that" — which names made the day).
- Tried: `column(run, "position_contributions", …)` → run holds no such table (tables: count, exposure_metrics, factor_attributions, issuer_exposures, limit_checks, risk_alerts, sector_exposures); `factor_attributions.<f>.contribution` rows are `not_alone` (collinear) so `column` skips them; `book.explain_episode` with peak=2026-09-03, trough=2026-09-04 → `insufficient_history`; `book.reconcile` yields only the sums (position, factor, alpha+residual) and the two shares.
- Now: day return per name from two `price` closes times the run weight, for the five largest weights (the 60-binding budget does not stretch to ten). A `holdings` table on `book.reconcile` (per-name contribution) or a two-date `price.window_return` would close it.

## G5. Method-registry alternatives that turn asked-for figures into refusals (not language gaps, recorded because the turn's headline figure refuses)
- `ebit`/`ebitda` accept only `interest_expense`, while `ebit_interest_coverage` also accepts `interest_expense_nonoperating`. LLY, AAPL and AMZN/MSFT stop filing `interest_expense` in 2023–24 (only the nonoperating concept continues), so `net_debt_to_ebitda`/`debt_to_ebitda` refuse (`input_unavailable: no reported period boundary near …`) while `ebit_interest_coverage` settles on the same window. Hits W02-lly-coverage-trend#t1 (the asked figure), W05-leases-in-leverage#t2 (AAPL), W03 would be hit for LLY.
- `ebitda` needs `depreciation_amortization`; MSFT files `depreciation` + `amortization_of_intangibles` instead → `input_unavailable`. Hits W05-leases-in-leverage#t2.
- `gross_margin` needs `gross_profit`; GOOGL/AMZN/LLY file `cost_of_revenue` (concept_mapping's own docstring says M3 should derive gross profit from it) → `input_unavailable`. Hits W04-growth-vs-margin-screen#t1 and FQ03.
- Now: the programs carry the desk's method (refused, part of the answer) and rebuild the nearest thing from filed lines at one window (pretax + interest + D&A; operating income + depreciation + amortization; revenue − cost of revenue), naming the substitution in the note.

## G6. `price.window_return` takes only named windows ending at the latest session; no return between two dates, no average price over a window
- Needs it: W06-nvda-buyback-timing#t1/t2 (each fiscal quarter's return and price level beside that quarter's repurchases).
- Tried: nothing in the language reaches a dated window; `prices` is a series but set ops give one number over the whole named window, not per quarter.
- Now: `price` at each fiscal quarter-end (seven closes), `sub`/`div` for six quarterly returns; the in-quarter average price (what a buyback actually paid) is stated absent.

## Minor
- A constant cannot enter `sub`/`add` (`ratio − 1` is not expressible); `scale` covers multiplication only. Worked around by `div(sub(p1, p0), p0)`.
- The `min`/`latest`/`cagr` nodes of a series carry no `as_of`/period, so the trough year has to be named by a second `at` node (W03-xom-trough-relever#t1).
