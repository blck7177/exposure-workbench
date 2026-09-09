# Program-language gaps found writing slice C (V26 battery), 2026-09-09

Each entry: the turn, what it needs, what was tried, the executor's refusal verbatim, how the
turn was covered. Runs on exposure_gold, latest run run_34042d64f60c (as-of 2026-09-04).

## 1. A balance cannot be subtracted from a scaled flow; no constant operand — W01 t2

Needs: headroom to a 2.0x handle = 2.0 x EBITDA - net debt (dollars).
Tried: `cap2 = scale(ebitda, 2.0)` (settles, MONEY $127.0bn) then `sub(cap2, net_debt)`.
Refusal: `incompatible_bases: calc_… is a flow and calc_… is a balance; a stock and a flow may be
divided, not added`.
Also tried the ratio form (2.0 - net_debt_to_ebitda) x EBITDA: there is no way to write the
constant 2.0 as an operand (`sub`/`add` take bindings or ids only; a literal binding is "not a
figure"). Covered partially: capacity_2x and net_debt delivered, the difference left to prose.
Suggest: a `const` primitive (value + unit) or letting `sub`/`add` accept a number, and a unit-table
row that a MONEY flow scaled by a dimensionless constant may be netted against a MONEY balance
when the answer is a capacity, not a period figure.

## 2. Scenario sizes are literals; `sell` has no target-weight form — W05 t2, NEW04 t1

Needs (W05 t2): sell MSFT down TO half the single-name limit. The fraction is
f = (w - t) / (w (1 - t)); every term except (1 - t) is expressible, and the result cannot be handed
to `sell` anyway: `sales[].fraction` must be a literal number (a `$name` in the trades list reaches
scenario_service as a Node and is not a number). Written as the literal 0.5776273, with `target` and
`w_msft_after` (0.0750) in the program so the literal is checked.
Needs (NEW04 t1): move four points of NVDA into LLY — the same: `nvda_fraction` (0.9428) and the
LLY target weight are computed as nodes but re-typed as literals into `sell`/`buy`.
Suggest: `sell` accepting `weight` (target share after the sale, mirroring `buy`), and scenario
arguments accepting `$name` scalars.

## 3. No two-legged trade; the only swap is sell -> buy chained — NEW04 t1

The criterion asks for both legs on ONE before-book. The language only chains (`buy` on the sale's
calc row), which renormalises twice and books the proceeds as leaving and re-entering. The chain
was written and is refused on gold for a data reason, not a language one:
`no_sector: LLY has no sector on this desk (not prepared, or not an SEC filer), so a
sector-concentration check on the book with it cannot run; prepare the name first`
(gold's companies row for LLY has sector NULL; the run's issuer_exposures carry Healthcare for it).
Covered by weight arithmetic on the before-book (w_lly_after = w_lly + w_nvda x f) and the room to
LLY's breach level. Suggest: a `trade` primitive taking sells and buys together, and `buy` reading
the sector from the run's own position when the name is already held.

## 4. Series arithmetic and series statistics are unreachable — NEW05 t2, t3

Needs: OCF / NI per quarter (two 8-point series), and avg/std of the accruals-ratio series as the
band a trigger is set from.
Refusals: `div(ocf_q, ni_q)` -> `type_mismatch: $ocfs is a series; an arithmetic operand is a
figure or a vector of figures`. `avg(accruals_ratio_q)` and `std(...)` -> the same type_mismatch.
The doc says `std (of: a vector, or a series for its own history)`; in `_p_set` the
`_operand_refs(of)` check runs before the `of.kind == SERIES` branch, so a series never reaches
`_p_series_op` through avg/min/max/std. Covered with the accruals_ratio method series (per-quarter
ratio) and `latest`; the band is read off the points.

## 5. `sub` of two method readings of one issuer is refused; series + `at` is not — B03 t2, W02 t3

`sub(equity_multiplier(JPM), equity_multiplier(JPM, at=2025-03-31))` ->
`mixed_basis_operand: calc_… is a sum across several periods (2026-03-31) and shares an issuer
with calc_…; combine it only with other issuers' quantities, or rebuild the sum from single-period
parts.` The same change through `equity_multiplier(last_n=5)` then `at(2026-03-31)` /
`at(2025-03-31)` / `sub` settles (13.46 - 12.40 = +1.06). Rule 4 ("sub of two readings") holds on
one path and not the other. Related: `at=` on a flow-based method shifts only the balances under
the LATEST flow window (cash_conversion_cycle at=2025-03-29 reads 2025-03-29 balances over
2025-03-30..2026-03-28), so it is not a year-ago reading; and `fundamentals(end=…)` without
`start` is ignored (start+end works). The grid series is the honest year-ago on every turn here.

## 6. `column` on a scenario's limit_checks changed behaviour mid-session — W05 t1-t3

At ~03:10 `column(after, limit_checks, current_value)` settled with 18 entries. After
src/exposure_workbench/services/program_service.py was modified at 03:22 (not by me) the same node
refuses: `unknown_name: $after.limit_checks has no rows with a ledger row and a 'current_value'
figure`. `pick(after, "limit_checks.issuer_concentration:MSFT.current_value")` still settles, so the
W05 programs use the pick form. Flagging for whoever owns the change: the scenario's check rows
are reachable by pick but no longer as a column.

## 7. Position quantity is not a run quantity — W03 t3

`column(run, issuer_exposures, quantity)` -> `unknown_name: … holds no column
issuer_exposures.<label>.quantity` (columns_of_table: contribution, daily_pnl, daily_return,
market_value, weight). A re-mark at a newer close (mv / qty x close) is therefore not expressible.
Moot on gold today (latest session = run as-of, px_chg = 0) but the turn is about exactly that seam.

## 8. Drawdown-episode figures are undated tables; dates are not figures — B05 t2

`pick(book.drawdown_episodes, deepest_depth)` and `pick(book.explain_episode, portfolio.window_return)`
-> `undated_operand: calc_… carries no as-of date, so its figures cannot be placed in time and
cannot be combined`. The per-holding window returns in explain_episode's payload (a list) are not
typed entries at all, and the episode's peak/trough dates are not figures, so they are literals in
the program (2026-01-07 / 2026-03-27, read from the payload). Covered legitimately with
`prices` + `at` + `sub`/`div` for HYG, TLT and SPY over the episode.

## 9. No label-subset primitive on a vector — FQ06 t2

"How much of the book is that between them" over four named tickers is four `pick`s and three
chained `add`s (`sum` needs a vector; nothing builds a vector from scalars). Works; clumsy, and the
derived measure reads `add(add(add(w,w),w),w)`. Suggest `select (of, labels)` -> vector.

## 10. Minor

- `price.window_return` with `benchmark` yields ONE scalar (the relative return); the absolute
  return needs a second call without the benchmark (B06 t2, W04 t3, NEW01 t2 do both).
- `method` over a list settles as a vector with `refused_entries`; the program-level `refused` is
  empty, so a partial vector (B03 t1: 2 of 8 subjects) looks settled unless the note says so.

## Data absences met on gold (not language gaps; recorded for the notes)

- debt_to_ebitda / ebitda: MSFT and GOOGL file no depreciation_amortization with a period; AAPL's
  and LLY's D&A data end 2023-09-30 / 2024-03-31; total_debt not produced for MSFT and NVDA
  (commercial-paper cover). Only AMZN and XOM rank; debt_to_operating_cash_flow covers 5 of 7.
- LLY companies.sector is NULL -> `buy` LLY refused (NEW04).
- NVDA: no 3-month revenue window derivable. GOOGL: `revenue` ends 2025-03-31, the line continues
  as `total_revenues` to 2026-06-30 (NEW02 t3 uses it).
- Latest price session equals the run's as-of (2026-09-04): W03 t3 is a no-difference answer.
