# V21 — the five residuals V19 and V20 registered, closed

Status: **as built** (2026-09-04). The batch is the residual lists of
docs/spikes/V19_COVERAGE.md §3 and V20_COVERAGE.md §3, taken one by one; the
boss's instruction was "execute the fixes". Each item below says what the
feature was, what the residual did to it, and what closing it changed —
because the order of these was decided by impact (S1 touched every
multi-issuer question) and by shape (nothing here is a prompt rule or a
fallback; each is a module that makes the error class unwritable, or a
measurement outside the gate where a rule cannot go).

## S1 — a batch of tool calls stops at its first refusal per tool

**Feature.** The meta-agent's 15-call turn budget, and the model's habit of
answering a ten-holding question with ten parallel calls in one message.

**Residual.** The loop dispatched a batch whole: ten round trips, ten units,
and only then ten copies of the same refusal (`evaluate_formula("net_income")`
→ `unknown_formula`, V19 round 1). Whether "rank the holdings by X" completed
depended on the first guess being right — round 4 spent ten on a call that
was right and reached `rank` with five to spare.

**Built.** `agents/batch.py`, one dispatcher for both loops. Within one
assistant message: a result with an `error` and nothing on the table is a
call-shaped refusal, and the remaining calls TO THAT TOOL are not sent — they
return `not_attempted`, naming the refusal they were held behind, with no
round trip, no budget and no table. A refusal that minted an absence row
(`get_flow` for a metric never filed, `get_beta` on too few observations)
arrives with a table and holds nothing: it is a finding, and the model may
want the same read for the other nine names. Once the evidence pool is empty
(`budget_exceeded` on the turn or session pool) every later read in the
message is held; the pause and the exits are never held and never hold. Held
calls are traced as `rejected` steps by the loop, so a turn's steps still
account for every call the model made. The meta loop's V3 narrowing now keys
on the same predicate.

**Effect.** A batch of ten wrong calls costs one unit and one round trip; the
model reads the refusal in the same turn and re-issues what still applies. The
mixed case (a refused ETF among ten names) costs one extra round trip and
saves the units it would have spent after the refusal.

**Measured live (2026-09-04, "rank all the holdings by their latest net
income").** The hold worked where it applies: when the pool emptied at the
fifteenth call, the remaining seven `get_flow` calls of that message were held
(seven round trips not made, seven `rejected` steps saying why). The question
still did not complete, for the residual's OTHER shape: the model's first
batch was ten `get_fundamental_panel` calls that all SUCCEEDED and did not
hold net income (a filed line, not a formula), then one `rank` on those, one
`evaluate_formula` (refused, pointing at `get_flow`), and the ten `get_flow`
it then needed had two units left. A correct-but-useless batch of ten is not
a refusal and nothing here holds it; it is the budget's unit that binds —
1 + 10 + 1 + 1 + 10 + 1 = 24 calls for six decisions. Two closings are
possible and both change what "15" means, so neither is made here: charge the
turn budget per assistant message (a decision) rather than per call, with the
context ceiling bounding payload; or give the filed-line reads a multi-issuer
form (`get_flow(metric, tickers=[…])`), so ten names are one call. See
V21_COVERAGE §3.

## S2 — the fall is computed where every estimate is

**Feature.** Single-name price questions — "how far did NVDA fall from its
high".

**Residual.** V19 made table labels derived, so `Peak-to-trough decline |
$205.10` became an honest `NVDA adj close 2026-05-14 | $235.47`; the
subtraction was still the model's initiative and it did not take it (V19 §3).

**Built.** `get_drawdown(ticker, window)` on both faces, from the price
service's own `_TOOL_SPECS`: the deepest peak-to-trough episode of the
adjusted close over a named window, as FOUR typed rows — `{T}.drawdown.peak`,
`.trough` (dated levels, money per share), `.fall` (peak − trough, money per
share) and `.depth` (fall ÷ peak, ratio) — with the recovery date if the peak
was regained. `analytics/drawdown.deepest_from_levels` reads levels rather
than returns so the first bar of a window can be the peak (`find_episodes`
cannot make it one). Floor `DRAWDOWN_MIN_OBS = 20`, a producer parameter; a
window that never fell is a statement (`no_drawdown`), not a zero.

**Effect.** "How much did it drop" slots a computed, ledgered fall or depth;
no cell or sentence has to carry a peak under a label that says decline.

## S3 — a stated share count is carried to the date it is valued on

**Feature.** Market value, weights, sector and issuer concentration, the
limit checks on them, P&L and the value path — everything that multiplies
`positions.quantity` by a price.

**Residual.** The quantity is a snapshot as of the upload; a split between
that date and the run date put count and close on different bases, and the
position at a fraction of itself (V5 §5, left as "a holdings-data problem").

**Built.** `analytics/splits.py::carry_quantity` — multiply by each ratio
with an ex-date in (stated, valued], divide when valuing earlier. The splits
come from the SAME provider call as the prices (yfinance's history frame with
`actions=True`; `PriceBar.split_ratio`), are written to `stock_splits`
(`infra/migrations/v21_stock_splits.sql`) by `ingest_market_prices`, and are
read once in the workflow's `_load_inputs`, which carries every holding to the
run date and keeps `stated_quantity` / `stated_as_of` / `split_factor` beside
the carried `quantity`. Holdings carried through a split are named on the
run's timeline (`load_inputs` payload `splits_applied`). The ⓘ statements for
market value and the value path say so.

**Effect.** Count and close are on one basis on the run date, so weights and
concentration are continuous across a split. Not done: holding history before
the stated date — there is none to carry.

## S4 — the attribution history is on one factor set

**Feature.** The factor regression and its stored rows per run
(`factor_attributions`, the fit's record on `exposure_metrics`).

**Residual.** V20 took `^VIX` out; runs since regress on seven factors, every
run before holds an eight-factor fit — R², residual, VIF and contributions not
comparable across the seam, and an old run's VIX row readable.

**Built.** `scripts/reattribute_runs.py`: re-fits each completed run's
attribution on the current factor set from the prices the desk holds, with
the workflow's own inputs (positions_for_run, the carried count, the same
`calc_factor_attribution` and config), replaces its rows, updates the fit's
record, and writes a `reattribute` event on the run's timeline with the
before/after numbers. Runs that never recorded a fit (a seed's "previous"
run) are left alone: a first fit under a re-fit's name would be invention.
Dry run 2026-09-04 against the live database: 28 runs would be re-fitted, 2
already on the current set, 2 left as is. Measured in that dry run: removing
VIX moves max VIF from 17.9 to 16.8 on the demo book — the collinearity is
SPY/QQQ/IWM, and every run stays `collinear`. **`--apply` has not been run**:
it rewrites production rows and waits for the boss's word (back up first:
`scripts/backup_db.sh`, then `python scripts/reattribute_runs.py --apply`).

**Effect.** One factor set across the history; the daily reports' text stays
what it was on its day.

## S5 — the critic outside the gate

**Feature.** The paragraph block of `respond` — the one place a label is
still the model's after V19.

**Residual.** "market cap at $919.77" with the slot `LLY.close`: the gate
proves provenance, not the words beside the figure, and by the 9/1 contract no
lexical rule and no model goes into the gate.

**Built.** `services/prose_critic.py`: reads RENDERED blocks, marks every slot
in a paragraph (`⟦k⟧(value)`), tells a second model the desk name and unit
beside each marker with a grammar of how the desk names things, and asks
what the sentence claims the figure is — `agrees` / `disagrees` / `unclear`,
no score. `chat` is passed in, never imported; no exit or gate imports the
module (test pins both). `scripts/critic.py` is its offline seat: a battery's
traces or a session's messages in, a per-slot report out.

**Where it sits, and the decision left open.** Offline, as a measurement,
today. Inline it would be one call after the gate accepts — a non-blocking
annotation beside the sentence ("the desk's name for this figure is LLY's
closing price"), one completion per paragraph with slots, ~2–4 s and a
model's cost per turn. Whether to pay that per turn, or only per battery, is
a product decision and is not made here.

## Suite

Offline 1987 → **2043** (`test_v21_batch`, `test_v21_drawdown`, `test_v21_splits`,
`test_v21_critic`; one V2 audit list extended). Live: see docs/spikes/V21_COVERAGE.md §2.
