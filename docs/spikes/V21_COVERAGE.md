# V21 coverage — the five residuals, what closed and what was measured

Companion to docs/IMPLEMENTATION_PLAN_V21.md. 2026-09-04.

## §1 What was measured before

From V19_COVERAGE §3 and V20_COVERAGE §3, the registered residuals:

| residual | feature | what it did |
|---|---|---|
| paragraph prose unjudged | `respond` paragraph blocks | "market cap at $919.77" passed the gate with slot `LLY.close`; 3 of 20 R20 answers carried such a slot |
| "decline" not subtracted | single-name price questions | the peak slotted where the fall belonged; V19 made the label honest, not the number |
| 15 calls/turn vs ten holdings | turn budget × parallel calls | ten wrong calls, ten refusals read afterwards, five units left (R1); success depended on the first guess |
| `positions.quantity` not split-adjusted | market value, weights, concentration, limits | a split between the upload date and the run date valued the position at 1/n |
| 8-factor history after `^VIX` left | `factor_attributions`, the fit's record | runs before V20 not comparable with runs after; an old run's VIX row readable |

## §2 What was built, and what the live turns showed

Offline suite 1987 → **2043**. Deployed (api, mcp, worker rebuilt; web
unchanged) and three questions run through the live face from the host
(`scripts/agent_battery.py`, dev owner):

| turn | calls | what happened |
|---|---|---|
| "How far did NVDA fall from its high over the past year, and has it recovered?" | 1 read + `respond` (one shape refusal, then accepted), 8.9 s | `get_drawdown(NVDA, 1y)` → fall **$41.80**, depth **20.2%**, peak and trough dated, recovery date present; all four slotted from the tool's rows. The prose put the depth where the recovery DATE belonged ("recovered by the recovery date 20.2%") — the critic, run on this answer, flagged exactly that slot (§2 S5). |
| "Rank all the holdings in the book by their latest net income." | 15 units spent, 7 held, 18.6 s | snapshot → 10 × `get_fundamental_panel` (all succeeded; panels do not hold net income) → `rank` (`unknown_operand`) → `evaluate_formula("net_income")` (refused, names `get_flow`) → 10 × `get_flow`: two ran, the fifteenth was refused by the pool, **the remaining seven were held** (`not attempted: held behind budget_exceeded`, no round trip). Honest answer: two names ranked, eight named as unread. See §3. |
| "Start a fresh exposure run for the book." | 1 read + 1 delegation, 2.7 s; run completed in 17 s | The worker on the new image: `sync_prices` refreshed 10 holdings and 7 factors and **wrote `stock_splits`: NVDA 2024-06-10 ×10** from the same history call. Positions are stated 2026-07-23, after the split, so nothing was carried (`split_factor` 1); NVDA's market value and weight are identical to the previous run's ($448,820 / 4.13%). Attribution on 7 factors, R² 0.807, max VIF 16.7, `collinear`. |

**S4, dry run only.** `scripts/reattribute_runs.py` against the live database:
30 completed runs; 28 would be re-fitted (8 → 7 factors; R² 0.809–0.812 →
0.807–0.813; max VIF 17.8–18.0 → 16.8–17.5; every run stays `collinear`; one
250-observation run R² 0.396), 2 already current, 2 never had a fit and are
left alone. `--apply` rewrites production rows and was not run: it waits for
the boss (backup first).

**S5, measured.** The critic over the 53 stored answers of 9/2–9/3 (30
paragraphs with slots, 73 slots in prose, 30 completions):

| grammar | agrees | disagrees | unclear | of the disagreements |
|---|---|---|---|---|
| first pass | 61 | 6 | 6 | LLY "market cap" (true); `exposure_metrics.daily_return` called a position's contribution (true); `stress_loss` called "a broad market drop" (arguable); `shares_outstanding.abs@…` called "the change" ×2 (**false** — `.abs` IS a change; the grammar had not said so); `adj_close.latest` called "current share price" (strict) |
| with series operators and alert/return names in the grammar | 59 | 4 | 10 | LLY market cap (true); daily_return as contribution (true); GOOGL `daily_pnl` as "the day's move in dollars" (strict — it is); `adj_close.latest` as "current share price" (strict) |

Two true findings out of 73 slots, both label-of-the-wrong-quantity; the
critic's own precision is 2/4 strict, 4/4 lenient, and it found the one V19
had named by hand. On the live drawdown answer it found the depth-for-date
slot (1 of 5) that a reader would have had to notice.

## §3 Residuals (registered, not patched)

- **The budget's unit still binds ten-name questions.** S1 removes the waste
  of a wrong batch; a CORRECT batch that turns out not to hold what the
  question needs (ten panels without net income) is not a refusal and is not
  held. Six decisions cost 24 calls. Two closings, each changing what "15"
  means, neither made here: charge per assistant message, or give filed-line
  reads a multi-issuer form. Boss's call.
- **Prose still puts a figure where a date belongs** ("recovered by the
  recovery date 20.2%"): dates are text the model may write and did not; the
  critic reads it, the gate cannot. Inline critic = product decision (plan S5).
- **Splits before the stated date** are not carried (there is no holding
  history); old runs computed before `stock_splits` was filled carried nothing.
- **Re-attribution** is dry-run only; the seam in the history stays until
  `--apply` runs. Daily reports written under eight factors keep their text
  either way.
- **`^VIX` out did not end the collinearity** (max VIF 16.7 on the fresh run;
  SPY/QQQ/IWM). Individual betas stay nulled under `collinear`.
- The critic's grammar is a hand-written list; a new quantity family the list
  does not describe reads as `unclear` or a strict `disagrees` until it is
  added. That is the intended failure direction (nothing false reads as
  agreement), and it is a list.

## §4 Suite and deploy

- Offline: 2043 passed (`test_v21_batch` 14, `test_v21_drawdown` 12,
  `test_v21_splits` 16, `test_v21_critic` 9; `test_v2_audit` learned
  `stock_splits` is shared).
- Migration `v21_stock_splits.sql` applied to the live database before the
  rebuild (additive, idempotent); named in docs/PRODUCTION.md before
  `docker compose up -d`.
- Images: api, mcp, worker rebuilt and recreated; `exposure-mcp` healthy;
  the meta face serves 43 tools (`get_drawdown` present); web untouched.
- Backup: not taken by this batch (the one write to production, `--apply`, was
  not run).
