# V22 coverage — the book's figures in the algebra, measured

Companion to docs/IMPLEMENTATION_PLAN_V22.md. 2026-09-04.

## §1 Offline

2043 → **2095** passed. `tests/test_v22_book_algebra.py` (43): the separator
and the name grammar; a run weight typed with base, date, entity; unknown
name / collinear coefficient / unknown row refused; the seven base rules;
trim-to-limit as two calls; post-trade weight as two calls; two runs' weights
refused for add and differenced for change; the holdings ranked by weight
with a place per name; weight and market value not one measure; **parity**
headroom = subtract, net beta = scale then add; the analysis row's own type;
an analysis distance as operand; the sale's arithmetic (renormalisation,
sectors, partial sale, the exact trim that lands on the warning line) and its
five refusals; the scenario row's names, units and groups; writer ⊆
declaration; a scenario weight as operand with the scenario as base; the
tool's face, schema and the grammar in the descriptions; the `book_derived`
group; an ordering carrying its base. `test_symmetry` learned the new group
key and, on the way, caught the first draft of `_from_scenario` spelling
column names the resources already declare — the columns are now read from
the declaration.

## §2 Live, against the database (host, owner role, before the rebuild)

Latest completed run `run_b791e7985dcd` (2026-09-03), 10 holdings, market
value $10,986,070.

| step | result |
|---|---|
| `run:issuer_exposures.MSFT.weight` resolves | 0.16251671, ratio, as of 2026-09-03, base = the run, entity MSFT |
| excess = current − warning (MSFT) | 0.01251671, ratio, base the run, a reading at 2026-09-03 |
| dollars_to_sell = excess × book market value | **$137,509.45**, money, base the run, about `issuer_concentration:MSFT`; on the table as `dollars_to_sell`, MONEY |
| MSFT weight, this run + the run of 2026-09-02 | `different_books` |
| the same two, differenced | +0.00240192 (a one-day change) |
| `rank` over ten `run:issuer_exposures.<T>.weight` | MSFT 1 … NVDA 10; names `issuer_exposures.weight.<T>` and `.rank.<T>` on the row |
| **parity, headroom** | 20 of 20 checks: panel `room_to_breach` == `calculate(subtract)` to the last digit |
| **parity, net beta** | not reachable through operands on THIS run: it is `collinear`, every single beta is `not_alone`, and the calculator refuses them as the table projects them. The panel's net remains the only quotable route under collinearity (V11-F), which is the intended asymmetry; the offline parity holds on a non-collinear fixture |
| an analysis distance × market value | `dollars_of_room`, money, base the run |
| `hypothetical_book(run, sell NVDA)` | proceeds $456,900; book $10,529,170; 9 names, MSFT 16.96%, AAPL 15.59%, JPM 15.47%, LLY 13.22% …; **four** issuer-concentration warnings where the run had two (AAPL and JPM cross 15% once NVDA's 4.16% is spread over the rest); 91 names on the row; `checks_not_run`: daily_loss, rolling_volatility_30d |
| scenario MSFT weight − run MSFT weight | +0.00705221, ratio, of neither book; their sum `different_books` |
| `hypothetical_book(run, sell 9.06% of MSFT)` | MSFT lands at 15.0000060% — the trim that clears the line by the arithmetic, still `warning` because the check is ≥, which is the engine's rule and the right one to see |

The battery's own question — "say I sell NVDA, where does that leave
concentration, anything get tight" — is answered by the seventh row: tighter,
not looser; two names newly over their warning line.

The live check wrote 52 ledger rows tagged `invoked_by = v22-live`; they are
real computations and stay (the ledger is append-only).

## §2b Live, through the deployed face (after the first rebuild)

Two of the battery's own questions, one session each, dev owner
(`scripts/agent_battery.py`, MCP over the host port). Both reached the gate
on the new code, and both taught something the database check could not:

| turn | what the model did | what it exposed | closed by |
|---|---|---|---|
| "say I sell NVDA outright — anything get tight?" | snapshot → **`hypothetical_book(NVDA)` on the first try** → `read_quantities(calc_id)` → `unknown_run` → a slot naming the whole id → three refusals → an answer with a table | (a) `read_quantities` only read runs, and a scenario is a run-shaped row; (b) the table's two columns derived the same header (`issuer exposures weight` twice): the scenario's names ARE the run's, so nothing said which column was which, and a reader saw `NVDA \| 4.16% \| 16.3% \| 17.0%` | `read_quantities` reads a scenario row; the scenario row carries a **subject** (`after_sale_of_NVDA`) that the renderer prefixes into derived names, so the after-column reads `after sale of NVDA issuer exposures weight` (pinned through `derive_table`) |
| "how much MSFT to sell, in dollars?" | snapshot → `calculate(subtract, run:risk_alerts…current_value, run:risk_alerts…limit_value)` = 1.25% ✓ → `calculate(multiply, calc_…:issuer_concentration:MSFT.excess_weight, run:portfolio_market_value)` → **`undated_operand`** → an honest "the dollar amount is unavailable" | the model wrote `ref:name` for a calculator row that holds ONE figure (the table shows it under that name), and `_named_context` knew runs, analyses and scenarios but not a calculator row's own `result_type` | a named figure on a single-valued calculator row resolves as the bare row (its leaves, base and date intact); `_named_context` reads `result_type.base` and `basis.instant` |

The model chose the right tools unprompted in both turns — the scenario
primitive on the first call, the two-step trim arithmetic on the first
try — which is the part of this batch no offline test could show. The two
refusals were the desk's, not the model's, and both were the same shape: a
row the reader treats as a run (a scenario) or as a figure (a calculator
result) that one seam still treated as "a ledger row". The rows that
mislabelled a table in turn 1 are ALSO the V21 §4(a) heterogeneous-row
defect (a row mixing NVDA's and MSFT's cells takes NVDA's label), which this
batch does not touch and which the status box carries as its own item.

## §2c Live, after the second rebuild (the image that carries §2b's fixes)

| turn | calls | what happened |
|---|---|---|
| "say I sell NVDA outright — anything get tight, anything get better?" | snapshot → `hypothetical_book(NVDA)` → `rank` over the NINE scenario weights (`calc_…:issuer_exposures.<T>.weight`) → respond (three refusals, then accepted), 27 s | A before/after table whose columns read **`issuer exposures weight \| after sale of NVDA issuer exposures weight \| issuer exposures market value`**, nine rows labelled by ticker, 28 figures verified against the run and the scenario row; "$10.53M of market value" from the scenario's own metric. Prose: NVDA's concentration gone, every survivor a bigger slice, MSFT still above warning, no sector pushed over. Not said, though on the table: AAPL and JPM newly over their 15% line (`count.alerts` 4 vs 2) — the model's reading, not the desk's |
| "how much MSFT to sell, in dollars?" | snapshot → subtract → divide → multiply → respond, **zero refusals, 5.0 s** | A different, equally valid route from turn 2b: overweight ÷ weight = the fraction to sell, × MSFT's market value = **$137,509.46**, printed "$138K". One slot, one figure, verified |
| "rank the holdings by weight and say how much room the top name has before it breaches" | snapshot → `rank` over ten `run_…:issuer_exposures.<T>.weight` → respond ×3 refused → `read_quantities` → subtract → respond, 28 s | The ordering is computed and correct (MSFT … NVDA). Two things went wrong on the model's side and one on the desk's: it wrote a SLOT with `ref = run_…:issuer_exposures.MSFT.weight` (the operand grammar, where a slot's ref is a bare id) and was refused `malformed_answer` twice without being told that; it computed `limit_value − current_value` from the ALERT row and called it "room before breach" (−1.25%: that is the room to the WARNING, which an alert's `limit_value` is) instead of calling `get_portfolio_analysis`, whose `room_to_breach` (+3.75%) was one call away |

Net of the three: the two questions the battery lost are answered with
computed, verified figures, and the model reached for the new primitive and
the new operands unprompted. Turn 3's mislabel is the V19/V21 prose class
(the critic's territory, not the gate's) with a naming cause underneath —
`risk_alerts.*.limit_value` is the tier that fired, which for a warning IS the
warning level, and the name does not say so.


## §3 Residuals (registered, not patched)

- **Net beta parity under collinearity** is structural, not a gap: the legs
  are projected, the sum is not. If the live book stops being collinear the
  live parity can be run as the offline one is.
- **A scenario does not re-fit**: no factor exposures, no volatility, no
  P&L on the hypothetical book. Two checks (`daily_loss`,
  `rolling_volatility_30d`) do not run and are named. Re-fitting is a
  regression over a history that does not exist for the new book.
- **`rank` names are `issuer_exposures.weight.<T>`**, not
  `issuer_exposures.<T>.weight.rank`: the ordering row's grammar is the
  quantity's, and the run-family patterns do not claim it, so its group is
  `book_derived`, not `concentration`.
- **The proceeds leave the book.** A scenario that holds the cash is a
  different scenario with a cash line the run does not have; not built.
- **The budget's unit** (V21_COVERAGE §3) is untouched. A scenario is one
  call where the algebra would take nine; the ten-name read remains ten.
- **A slot's ref is a bare id; an operand may be `ref:name`.** Turn 3 wrote
  the operand grammar into a slot and was refused `malformed_answer` with no
  sentence naming the difference. That belongs to the refusal-letter pass the
  status box already carries (V21_CONVERSATIONS §9 item 1), not to this
  batch; registered here because V22 is what made the two grammars coexist.
- **`risk_alerts.*.limit_value` does not say which tier it is.** For a
  warning alert it is the warning level; a reader — and the model — reads
  "limit" as the breach line. The panel's `room_to_breach`/`room_to_warning`
  say it; the alert column's display name ("limit") does not. A display-name
  decision, not a V22 change.
- **The scenario's new alerts are on the table and were not read out**
  (turn 1: AAPL and JPM newly over warning; `count.alerts` 4 against the
  run's 2). The desk computed it; whether the prompt should ask for
  "what changed in the checks" is the V21 §11 model-behaviour pass.

## §4 Suite and deploy

- Offline 2095 passed; no migration (no schema change: the scenario is a
  ledger row, the base is a key in `result_type`).
- Offline after the live findings: **2100** passed.
- Images: api, mcp, worker rebuilt and recreated twice (once for the batch,
  once for §2b's fixes); web untouched. Deploy judged in the container, not
  by the commit (8/27's lesson): `hypothetical_book` ×5 in
  `tools/definitions.py`, `_book_rule` in `typed_calculator.py`,
  `analytics/scenario.py` present, `after_sale_of_` in `quantities.py`,
  `_is_single_valued` in `typed_calculator.py` — all grepped in the running
  api, mcp and worker containers; `/api/health` ok; `exposure-mcp` healthy.
- No migration; no backup needed (nothing in production was rewritten — the
  live checks appended 52 tagged ledger rows and the live turns their own).
