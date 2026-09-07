# V26 live battery — findings log

Rules of this run (boss, 2026-09-07): **no code is changed while the battery runs.**
Every problem is recorded here with its trace, and fixed only after the run is scored.

Stack: rebuilt 2026-09-07 02:29 from `ddcb682`; mcp/api/web/worker up; all nine service and
analytics modules md5-identical to the working tree. Battery runs in-process against the same
Postgres, with `MCP_URL=http://127.0.0.1:8104` — so **every tool call in this run went through the
rebuilt MCP container**, not through local code. The stack was verified healthy throughout:
`desk-for-one.com/`, `/issuer/MSFT` and `/api/health` all 200, local api/web 200, and the only
errors in an hour of container logs are the X3 `fact adapter failed for describe` traces, which
confirms X3 fires on the deployed path.

What was run: 4 conversation batteries (V21 and V24, each at concurrency 3 and again serially)
= **102 turns**, all answered, none crashed; 4 semantic rubric scorings; and two read-only
capability audits (56 `describe` combinations, 46 registry methods, 9 issuers × 11 measures).

---

# SUMMARY — ranked by severity

| # | finding | layer | severity |
|---|---|---|---|
| **X8/X14** | a **wrong figure verified and shipped**: "the top five carry 63.1%" when the true answer is 71.2% — the model summed five arbitrary names, never ranked, and fabricated a cross-run "unchanged" by summing the same run twice. The serial replicate of the identical question answered 71.2% correctly. Non-deterministic and indistinguishable downstream. | agent + validation | **critical** |
| **X15/X16** | **role errors**: a real figure given a role it does not have — a threshold read as a current reading ("already at 20.0%" when the check is at 16.25%), money called days ("$10.99M days"), a ratio called a multiple ("128.3% times"), the same series point on both sides of a growth claim ("revenue grew from $65.18B to $65.18B"), and one session's P&L used to explain a 55-day drawdown with positive contributions called "the larger drag" (X18). All gate-verified. **Five reader-visible false statements in 102 turns.** | agent + validation | **critical** |
| **X1/X2** | **zeros from an IN-FLIGHT run reached the reader as facts**. `describe(run_id)` refuses an incomplete run; `read_book(run_id)` does not. | tool | **critical** |
| **X3/X4** | `describe(ticker, expand='filings')` **crashes on every issuer** (`UnknownUnit: 'Item 1A'`). The whole filings discovery route is dead. No fixture covers the path, so 2,133 offline tests miss it. | tool | **high** |
| **X10** | **35 occurrences in 12 turns** of a passage id written where a NUMBER belongs, rendering as `[10-K Item 7]` mid-sentence. Structural: the figure lives only in prose, the model may not write numbers, so the only available id is the passage's. | skill + user report | **high** |
| **W5/P3/P9** | `unknown_series` **18 times** — a series fact id passed to a series statistic. `_stat` resolves the operand, then throws the resolution away and passes the caller's `f_` ref. The V25 `compute` description tripled the attempts; every one lands here. | service | **high** |
| **X9** | **31 of 35 superlative claims made with no `rank` call.** The primitive built in V17 to stop "comparing by eye" is used 4 times in 35 opportunities. | agent | **high** |
| **X5/X6** | **12 of 46 methods do not resolve** on the book's largest holding; `debt_to_ebitda` resolves for **2 of 9** issuers. `total_debt` fails and cascades to 8 measures. | data ingest | **high** |
| **X13** | a **missing signpost became a false statement**: `read_fundamentals(metric='accruals_ratio')` → `metric_not_filed` → the answer told the user the desk has no accruals figure. It resolves for all 9 issuers. | tool | medium |
| **P6/P2** | the V25 **domain names entered the method and section namespaces** — four domain names passed to `compute(method=…)` in one call, one passed to `read_book(names=…)`. Three vocabularies, one namespace. | skill → tool | medium |
| **P14** | the **V25 arithmetic closure was used successfully 3 times in 102 turns** (2 N-ary `add`, 1 `params.by`); set statistics **zero**. | service + skill | medium |
| **P7/W4** | the participation-rate desk rule causes **over-refusal**: the model declines to compute days even when the user supplies the rate. | skill | medium |
| **X12** | "has the sector shape **drifted**" answered from a single snapshot, no run touched, a level reported as a change. | agent | medium |
| **X20** | **`price.beta` succeeded 0 times in 102 turns.** All 5 calls that named it paired it with an `op` (`latest`/`avg` over a list of subjects) and hit `op_or_method`. It works perfectly when called cleanly. It is the method the desk's own rules name as THE per-name rate/credit sensitivity, and it has never produced a figure in a live conversation. | tool schema | **critical** |
| **W7/W8** | tool-surface friction: `price.adv` called with `window` not `window_days`; `read_fundamentals` asked with human-language metric names ×6; 11 non-methods passed to `compute(method=…)` (filed metrics, domain names, and the ops `rank` and `yoy`). | tool | medium |
| **X18/X19** | a 55-day drawdown explained with one session's P&L (`book.explain_episode` called **0 times in 102 turns**); a COUNT rendered as `55 on port_001@2026-09-03`. | agent / user report | high |
| **P14b** | only **3 of 102 turns opened a domain card** (`expand='procedures'`); the desk rules render on every describe and leave no measurable signature in the answers. | skill | medium |
| **X7** | **the instrument cannot resolve what it is being asked to report**: two runs of identical code differ by 5 points on 87. The battery mutates the desk it measures (3 exposure runs created mid-battery, 9 turns read one), reads a live internet, and is scored by a model. | test harness | **high (methodology)** |

**Scores.** V21: 64/87 (9/6) → 54 concurrent / 59 serial. V24: 30/53 → 25 / **25**.
V21's drop does not reproduce; V24's does, twice, on the criteria the blocked routes feed.

**What V25 demonstrably bought.** `price.adv` produced `/day` figures for the first time and
N03-liquidity went 0/5 → 4/5. The N-ary fold made the top-five question answerable in one call —
and in one of two replicates it answered wrongly (X8), which is the run's central lesson:
**closing a capability gap without the matching constraint converts a visible failure into an
invisible one.**

---

## SMOKE (N03-liquidity, 2 turns) — the case V25 was supposed to fix

Both turns answered; t1 3 tool calls + 1 gate refusal, t2 6 calls. Answers in
`docs/spikes/v26/SMOKE.json`.

### P1 — `price.adv` never called; the desk claims an absence it does not have (SKILL layer)
t1 closes: *"it does not hold ADV, bid-ask, or market-impact figures for these holdings here,
so I cannot turn this into a hard liquidation-time ranking"*.
t2 closes: *"the desk does not hold a daily-volume figure for MSFT"*.
Both are FALSE. `price.adv` is a registry method, it is listed by name in the desk-level
`describe` payload the model read, and the new `book_liquidity` domain names *"each name's
dollars a day traded over the window"* as its evidence.

What the model actually did: `describe(subject=null, expand='book')` → level 1 only (domain
names + two `asked_as` phrases each). It never opened the domain, so it never read the evidence
list. Identical in shape to the 2026-09-06 measurement: 1 of 23 describes opened a card.
**Conclusion: the level-1/level-2 split does not make the model expand. Knowledge that is one
call away is knowledge the model does not have.**

### P2 — the domain name is now a new wrong-address surface (SKILL/TOOL boundary)
t2 step 14: `read_book(ref=run_aacdb498c66f, names=["book_liquidity", "positions"])` →
`unknown` + `nearest`. The model read the DOMAIN name `book_liquidity` as a readable figure
name on the run. This is the same class as the 2026-09-06 finding (method names passed to
read_book, 7 times) — the V25 rewrite added a third vocabulary to the same namespace
(table names, method names, domain names) with nothing marking which tool consumes which.

### P3 — `compute(op='latest', operands=[f_…])` → `unknown_series` (SERVICE layer, V25 regression)
t2 step 20: the model passed a price-series FACT id (`f_d3a4d95af2aa`) to a series statistic.
`compute_service._stat` resolves the operand, sees a `TypedSeries`, and then calls
`series_service.series_stat(db, operands[0], …)` with the ORIGINAL ref — an `f_` fact id — which
`load_series` looks up in `calc_ledger` and cannot find. The resolver knew the underlying row;
the dispatch threw that away. Introduced by the V25 `_stat` rewrite (`eed93f1`).
Fix (after the run): pass the resolved series' `source_id`, not the caller's ref.

### P4 — liquidity answered as concentration (ANALYSIS quality, consequence of P1)
t1 ranks by WEIGHT and calls it a liquidity answer ("By weight ranking, MSFT is the largest").
This is the exact substitution the 2026-09-06 battery recorded, unchanged.

### P5 — t2 computes a figure it already holds
Having read `issuer_exposures.MSFT.quantity` = 3500 shares, the model divides market value by
the close to "derive" the share count, and reports the derivation as if it were the finding.

---

## REGRESSION V21 (13 conversations, 31 turns) — all answered, none crashed

`docs/spikes/v26/REGRESSION_V21.json`, diagnostics `DIAG_V21.json`.

| | 2026-09-06 measurement | this run |
|---|---|---|
| llm round trips / turn (median) | 6 | 6 |
| tool calls / turn (median) | 6 | 5 |
| gate refusal rate | 23/43 = 53% | 20/51 = 39% |
| turns that opened a domain card | 1/23 | 1/31 |
| compute refusals | 22 in 20 turns | 21 in 31 turns |

### P6 — the V25 domain names entered the METHOD namespace (SKILL → TOOL)
`C01-trim-one#t2`:
`compute(method=["issuer_profitability","issuer_earnings_quality","issuer_credit_and_balance_sheet","issuer_capital_allocation"], params={"last_n":4}, subject=["LLY","MSFT"])`
→ `unknown_method`. Four domain names in one call. On 2026-09-06 the same class cost one call
(`capital_allocation` as a method); the rename made the surface bigger, not smaller. With P2
(domain name passed to `read_book`) this is now the single most common addressing error:
the desk has three name vocabularies — run-table names, method names, domain names — in one
namespace, and nothing in the payload marks which tool consumes which.

### P7 — `describe(expand='filings')` raises `fact_adapter_error` — 4 times (TOOL, hard bug)
NVDA, AMZN, LLY×2. A hard adapter exception, surfaced to the model as a tool error. It aborted
the filings route in three conversations that needed it. Highest-severity item in this run.

### P8 — `op_or_method`, 4 times (TOOL schema)
The model fills BOTH `op` and `method` when it wants "run this method and take the latest /
average of it": `{"op":"latest","method":["price.beta" ×10],…}`, `{"op":"avg","method":"net_debt_to_ebitda","subject":[8 tickers]}`.
The schema permits both fields, and compute refuses the combination. The model's intent —
a method over a list of subjects, then a statistic over the results — is exactly what the
V25 set statistics do, in two calls; nothing tells it so.

### P9 — `unknown_series` on a fact id, 3 more times (SERVICE, confirms P3)
`{"op":"pct","operands":["f_43b130725a16"]}`, `{"op":"latest","operands":["f_f223f201c354"]}`,
`{"op":"pct","operands":["f_f223f201c354"]}`. Same defect as P3: `_stat` resolves the operand
to a `TypedSeries` and then hands `series_stat` the caller's `f_` ref instead of the resolved
row's id. Four occurrences across smoke + V21.

### P10 — `read_fundamentals` asked for FORMULA names, 3 times (TOOL, missing signpost)
`metric='free_cash_flow'`, `metric='net_debt_to_ebitda'`, `metric='total_debt'` → `metric_not_filed`.
`evaluate_formula` has the reverse signpost (a filed metric asked as a formula is told to use
`read_fundamentals`); `read_fundamentals` has no signpost back to `compute`.

### P11 — invented ids: `port_?`, `port_1`, `run_85acaef8d4c` (AGENT)
3 occurrences. The desk-level describe lists the real ids; the model still guessed.

### P12 — knowledge and capability disagree on ordering the uses of cash (SKILL vs SERVICE)
`issuer_capital_allocation`'s compare段 says *"the ordering of the uses"*. `C05-amzn-capital#t1`
did exactly that: `rank(capex, buybacks, debt_repayment)` → `incomparable_quantities`, because
rank requires ONE measure across holders. The domain tells the model to do something the tool
refuses. Either rank grows a "several measures of one subject" mode, or the domain stops asking
for an ordering.

### P13 — `issuer.panel` with `last_n` → `invalid_params`, twice
The V25 refusal fires and names the alternative. The model wanted a panel over time; there is
no such thing. Recording it as a demand signal, not a defect.

### P14 — the V25 arithmetic closure was never used successfully — ZERO times
Measured over all 31 turns: `params.by` 0, N-ary `add`/`multiply` 0, set `sum/avg/min/max/std` 0,
formula `last_n` 7 attempts of which 0 succeeded (2 refused, 5 held behind a refused sibling).
No `MONEY_PER_DAY` / `COUNT_PER_DAY` figure appears anywhere in the run.
The closure is in the `compute` description the model reads on every call. It is not reached.

### P15 — 36 of 46 registry methods never called
Never once: every days/working-capital measure, every leverage and coverage measure, every
price-context measure except `price.beta`, `roe`/`roa`/`roic`, `gross_margin`, `net_margin`.
`price.beta` (10 calls) is the exception and it is the one measure named in a desk RULE that is
rendered at every describe level, not behind an expand.

### P16 — one false-absence claim (`price.beta`, C04-rates-100bp#t2)
The answer quotes the desk's own `per_name_factor_sensitivity` absence — whose text says to use
`price.beta` with TLT as benchmark — and stops at "not held", after having called `price.beta`
ten times in the same turn. The absence fact's text is being read as a refusal rather than as
a route.

### P17 — other refusals worth keeping
`not_alone` on a collinear factor leg (correct); `duplicate_operand` on `rank(f_x, f_x)`;
`unknown_operand` on an invented `MSFT:operating_income` ref syntax; `series_only` on
`pct(f_a, f_b)` (the V25 refusal, working as designed).

---

## REGRESSION V24 (12 conversations, 20 turns) — all answered, one hard failure

`docs/spikes/v26/REGRESSION_V24.json`, diagnostics `DIAG_V24.json`.

| | 2026-09-06 | this run |
|---|---|---|
| llm round trips / turn (median) | 6 | 7 |
| tool calls / turn (median) | 6 | 8 |
| gate refusal rate | 23/43 = 53% | 15/35 = 43% |
| compute refusals | 22 | 23 |
| turns that opened a domain card | 0/20 | 0/20 |

### W1 — WHAT THE V25 ARITHMETIC ACTUALLY BOUGHT
**N06-top-five went from a lost turn to a correct one.** 2026-09-06: 16 tool calls, seven chained
`add` refusals, turn lost. Now: 7 calls, one `add` over five weights, one over the prior run's
five, and the answer *"the top five carry 63.1% … the prior run's top five also sum to 63.1%, so
neither tighter nor looser."* The N-ary fold did exactly what it was built for.
`params.by` was used once and correctly (N03, ten market values over one ADV).
Set statistics (`sum/avg/min/max/std` over a set): **still zero uses across all 51 turns.**

### W2 — `price.adv` WAS called this time, and the flow unit reached the reader
N03-liquidity t1 called `price.adv` for the book and wrote *"$15.67B/day, $16.58B/day, $2.80B/day"*.
The `MONEY_PER_DAY` class and its `/day` rendering work end to end. Contrast the smoke run, where
the same question produced a false absence — the difference is that here the model reached the
method, and there it did not. The trigger is not reliable.

### W3 — **a wrong figure shipped to the reader: "$10.99M days"** (ANALYSIS, not caught by any gate)
N03-liquidity t2, asked "how many days at a quarter of daily volume", answered:
*"the exit would be about $10.99M days at a quarter of its daily volume … computed from the AAPL
holding value $1.64M and the AAPL weight 14.9%"*.
It divided a market value by a WEIGHT. `MONEY ÷ RATIO = MONEY` is a legal row, so the unit algebra
had nothing to object to; the flow dimension prevented a false COUNT but not a false SENTENCE.
This is the 2026-09-06 "249.9% days" failure in a new costume. The gate does not judge sentences
(9/1 contract), so nothing stopped it.

### W4 — the desk rule on participation rate causes OVER-refusal
N03 t1 closes: *"The desk does not hold a hard days-to-liquidate figure for each name because it
fixes no participation rate."* That sentence is the rule I wrote on 2026-09-07 ("the desk fixes
none; the user's, or none") read as a prohibition. The user's question in t2 SUPPLIED the rate
("at a quarter of daily volume") and the model still did not compute days correctly.
The rule needs to say what to do when a rate is given, not only that the desk fixes none.

### W5 — `unknown_series` is now the single largest defect: 14 in V24, 3 in V21, 1 in smoke = 18
Every one is the same shape: a series FACT id (`f_…`) passed to a series statistic.
`N08-whats-in-the-price#t1` states the defect in the answer itself:
*"I can't give you a clean high-vs-low read … the 1-year price series is held as $162.21, but
compute will not accept that series id for max/min"* — and then guesses "upper end of its range"
with no figure. The turn is lost to the defect and produces an ungrounded claim on the way out.
On 2026-09-06 this error appeared 6 times; it is now 18. **The V25 `compute` description
("a statistic over one series, or sum/avg/min/max/std over two or more figures") tripled the
model's attempts at series statistics, and every attempt lands on an unfixed address translation.
Net effect of that description change, measured: worse.**
Cause (unchanged from P3): `compute_service._stat` resolves the operand, gets a `TypedSeries`
that knows its underlying row, and then passes the caller's `f_` ref to `series_service.series_stat`.

### W6 — N10-margin-debate: complete turn loss, 17 calls, 4 gate refusals, no answer
*"I could not produce an answer I can stand behind for this turn."* The route: a 4-operand
`divide` → `operands` refusal, then a 2-operand `divide` → `not_a_quantity` (one operand was a
ranking row). Gross margin is a one-call registry method (`compute(method='gross_margin',
subject=['AAPL','MSFT'])`) and the model never used it — it tried to build the ratio by hand
from filed lines. `gross_margin` was called twice in the run, elsewhere.

### W7 — `price.adv` called with the wrong parameter name
`{"method":"price.adv","params":{"window":"3m"}}` → `invalid_params`. The card declares
`window_days` with enum 20/30/60. The model generalised `window` from the other price methods.
Four of the seven price methods take `window`, one takes `window_days`, one takes both, one
takes neither. The parameter vocabulary is not uniform.

### W8 — `read_fundamentals` asked with human-language metric names
`"cash and cash equivalents"`, `"total debt"`, `"shareholders' equity"`, `"capital_expenditures"`,
`"depreciation_and_amortization"` → `metric_not_filed` ×6. The real names are `cash_and_equivalents`,
`capex`, `depreciation_amortization`. `describe(ticker, expand='fundamentals')` lists them; the
model did not read the list before guessing.

### W9 — `describe(expand='filings')` `fact_adapter_error` again (LLY) — 5 occurrences over both runs
Confirms P7 as reproducible, not incidental.

### W10 — one false-absence claim (`price.drawdown` / `book.drawdown_episodes`)
N04-drawdown-anatomy: *"the drawdown-episode and explain-episode rows are not held on the run
surface I was able to read"* — both are registry methods on the PORTFOLIO, and the model was
looking at a run.

---

## SCORES — both batteries regressed, and the regression decomposes

Same rubric, same criteria files, same judge.

| | 2026-09-06 | 2026-09-07 | Δ |
|---|---|---|---|
| V21 conversations (31 turns) | 64/87 | **54/87** | −10 |
| V24 conversations (20 turns) | 30/53 | **25/53** | −5 |

Per criterion, the two runs together: `so_what` 15/24 → 10/24, `grounded_claims` 28/35 → 24/35,
`precision` 11/16 → 8/16, `follows_on` 23/26 → 19/26, `trigger` 6/9 → 5/9.
Up: `ranking` 5/17 → 5/17 (V24 alone 0/7 → 2/7), `netting` 0/3 → 1/3, `honest_absence` 2/6 → 3/6.

**The one thing V25 was built for improved most.** N03-liquidity went 0/5 → 4/5 across its two
turns; N06-top-five 0/3 → 1/3 and won its turn. Everything else moved down.

### Where the −15 comes from — four causes, and only one of them is a code regression

**(a) `unknown_series`, a real defect, tripled (6 → 18).** It cost figures in
N01, N02, N05, N07, N08, N09 and C13. `N08-whats-in-the-price#t1` names it in the answer and then
guesses a conclusion with no figure — one lost `grounded_claims` and one lost `precision` directly
attributable. `C05-amzn-capital#t2` lost both its criteria hedging on growth rates it could not
compute because `compute(method='capex', last_n=4)` is `unknown_method` (capex is a filed metric,
not a formula) and `yoy` on the fact id is `unknown_series`.

**(b) THE BATTERY IS NOT A CONTROLLED EXPERIMENT — it mutates the desk while it runs.**
`C06-new-name-ko#t3`, `C07-vol-rising#t1` and `N04-drawdown-anatomy#t1` each issued
`start(kind='exposure_run')` on port_001. Three new runs were created mid-battery
(`run_e6249206a002`, `run_af342695cf2b` 02:41, `run_6093c5caee31` 02:52). Nine other turns then
read one of them: C07, C10#t2, C11#t2, C12#t1, C12#t2, N03#t2, N04#t2, N05#t1, N06#t1, N12#t2.
At concurrency 3 on ONE shared portfolio, a conversation's answer depends on what another
conversation did seconds earlier. **No cross-run comparison of scores is sound until the battery
either runs serially on a frozen book or gets its own portfolio per conversation.**

**(c) live web.** `C10-news-to-position` reads `search_web`; its `grounded_claims` result depends
on what the internet said that hour.

**(d) judge variance.** The rubric's own docstring says the semantic pass "reports a distribution
over repeats, never a verdict on one run." A −15 over 140 binary judgments on ONE repeat is
inside the range this instrument was designed not to adjudicate.

---

## THE MOST SEVERE FINDING OF THE RUN

### X1 — zeros from an INCOMPLETE run reached the reader as facts (TOOL layer)

`C07-vol-rising#t1`. The model started an exposure run, then, in the same turn:

```
18 read_book {"ref":"run_af342695cf2b","names":["risk_state","alerts","attribution"]}
   -> keys: run_id, section, facts          <-- accepted, on a run that was still RUNNING
```

and answered:

> *"The only current run facts are that **0 has no limit checks evaluated, 0 has no checks fired**,
> and the alert section is empty, so there is no new evidence of a volatility breach."*

`describe(run_id)` refuses a run that is not completed (`run_not_completed`).
`read_book(run_id, sections)` does not: it read an in-flight run and the adapter minted `0` as
SCALAR facts, which the gate then verified as real figures because they are real ledger rows.

This is the exact class the desk's own rule forbids — *"a risk no factor measures is reported
unmeasured, not zero"* — arriving through a door nobody had closed. It is not a battery artifact:
any user who asks a question that triggers a run can be told the book has zero checks and zero
alerts.

### X2 — `start` is fire-and-forget and the same turn reads the result
The turn that starts a run reads it 5 seconds later. Nothing in the desk tells the model that a
started run is not readable yet, and `read_book` does not enforce it.

### X1 mechanism, confirmed read-only in the code
`catalogue_service._run()` refuses a run that is not completed:
`if run.status != "completed": return _err("run_not_completed", …)`.
`run_reads_service._run_or_error()` — which `read_book(run_…)` goes through — checks existence
and RLS visibility only, never status. Two doors into the same room; one is locked.


### X3 — `describe(ticker, expand='filings')` is 100% dead, on every issuer (TOOL layer)

Reproduced read-only on NVDA, LLY, AMZN and MSFT — all four raise:

```
UnknownUnit: describe: no unit declared for numeric key 'Item 1A' (subject NVDA);
             add it to fact_adapters.UNIT_BY_KEY or remove it from the payload
```

`catalogue_service._filings()` adds `items_detail = {item_code: count}` — `{"Item 1A": 3, …}` —
**only when `full=True`, i.e. only under `expand='filings'`**. The fact adapter walks the note,
finds a numeric leaf under the key `Item 1A`, and refuses to mint a fact without a declared unit.
The wrapper turns that into `fact_adapter_error` and the model loses the call.

Why 2,133 offline tests miss it: `tests/test_fact_adapters.py` has fixtures for
`describe_issuer_expand_fundamentals` and `describe_issuer_expand_methods` but **none for
`expand='filings'`**. The payload shape that crashes exists on no fixture.

Present since V24 (the adapter's `UnknownUnit`) over a payload key added in V23 (`dacef3d`).
The 2026-09-06 battery recorded one `describe:fact_adapter_error` and it was never diagnosed;
this run produced five, in NVDA, AMZN and LLY conversations — the three that most need filings.

**This is a whole discovery route dead for the entire filings domain.** It is the first thing to
fix after the run.

---

## CAPABILITY AUDIT — read-only, independent of the model

### X4 — every `describe` path probed: 56 combinations, 3 failures, all X3
`describe(subject, expand)` over {desk, MSFT, JPM, KO, ZZZZ, port_001, two runs} × {none + 6 expands}:
only `expand='filings'` crashes, and it crashes on every issuer (MSFT, JPM `'Part II, Item 1A'`, KO).
No other adapter crash and no I1 violation anywhere in the catalogue. X3 is exactly scoped.

### X5 — 12 of 46 registry methods do not resolve on the book's largest holding
Calling every method once on MSFT / `run_aacdb498c66f` / `port_001`: 34 produced a figure,
9 refused, 3 need parameters. Every one of the 9 traces to `total_debt`:

> `total_debt is not produced for MSFT as of 2026-03-31: the widest non-overlapping set of
> reported debt components …` (`incomplete_cover`)

and it cascades to `net_debt`, `debt_to_ebitda`, `net_debt_to_ebitda`, `debt_to_operating_cash_flow`,
`fcf_to_debt`, `invested_capital`, `roic`. `ebitda` fails separately on missing D&A.

### X6 — the credit domain has thin coverage across the whole universe

| measure | issuers where it resolves (of 9) |
|---|---|
| `accruals_ratio` | 9 |
| `ebit_interest_coverage` | 8 (JPM correctly refused as a bank) |
| `free_cash_flow`, `days_inventory` | 7 |
| `total_debt`, `net_debt` | 5 |
| `gross_margin`, `ebitda` | 4 |
| `roic` | 3 |
| `debt_to_ebitda`, `net_debt_to_ebitda` | **2** (AMZN, XOM only) |

JPM's refusals are correct by policy. The rest are ingest gaps.

**This reframes two earlier findings.** `C06-new-name-ko#t2`'s *"I can't make the exact leverage
comparison you asked for from the figures this desk holds"* is HONEST, not a model failure —
`net_debt_to_ebitda` genuinely resolves for 2 of 9 names. And the fact that the model "never called
the leverage measures" (P15) is partly the measures not being callable.

It also sets a constraint on the expanded battery: any question in
`issuer_credit_and_balance_sheet` is, for 7 of 9 issuers, an honest-absence test whether the
author meant it to be or not.

---

## X7 — THE INSTRUMENT CANNOT RESOLVE THE DIFFERENCE IT WAS BEING ASKED TO REPORT

The V21 conversations were run TWICE on 2026-09-07 against identical code — once at concurrency 3
and once serially — and scored by the same judge with the same criteria.

| criterion | 2026-09-06 | 09-07 concurrent | 09-07 serial |
|---|---|---|---|
| follows_on | 16/18 | 14/18 | 13/18 |
| grounded_claims | 19/22 | 16/22 | 18/22 |
| honest_absence | 1/3 | 2/3 | **3/3** |
| netting | 0/2 | 0/2 | 0/2 |
| precision | 5/7 | 4/7 | 6/7 |
| ranking | 5/10 | 3/10 | 3/10 |
| so_what | 10/15 | 7/15 | 9/15 |
| trigger | 4/6 | 4/6 | 3/6 |
| **TOTAL** | **64/87** | **54/87** | **59/87** |

**Two runs of the same code differ by 5 points on 87 — 6%.** The "regression" against 2026-09-06
is −10 concurrent and −5 serial. The serial figure is inside the spread the instrument produces
on itself.

Three separate sources of variance are stacked in one number:
1. the battery mutates the desk it measures (X above: three exposure runs created mid-battery,
   nine turns read one);
2. `search_web` reads a live internet;
3. the semantic judge is a model, and the script's own docstring says it "reports a distribution
   over repeats, never a verdict on one run."

**Nothing about V25's effect on answer quality can be concluded from a single run of this battery.**
What CAN be concluded is mechanical and countable, and all of it is in the sections above:
`unknown_series` 6 → 18, `describe(expand='filings')` dead on every issuer, zeros from an
in-flight run reaching the reader, N-ary `add` winning a turn it used to lose, `price.adv`
producing `/day` figures for the first time.

### What the serial run shows that the concurrent one hid
- `honest_absence` **3/3**, the best it has ever scored. Three of its refusals are the ROIC chain
  from X5, said correctly: *"Microsoft is best on operating margin, but that ranking does not hold
  on ROIC, where Alphabet is best among the names the desk can state."*
- 20 distinct registry methods called (concurrent run: 17; V24 run: 7).
- `unknown_series` once, not three times — the serial run reached for METHODS where the concurrent
  run reached for series statistics on fact ids.
- median round trips 5, not 6.

### Note on the false-absence detector
`scripts/v26_diagnose.py` flags a sentence that claims the desk lacks something whose method exists.
Given X5/X6 it over-flags: three of the six flags in the serial run are ROIC claims that are TRUE
(ROIC genuinely does not resolve for MSFT). The confirmed FALSE ones across all runs are
`price.adv` ×2, `price.beta` ×2, `price.volatility` ×2, `price.drawdown` ×1.

---

## X8 — THE MOST IMPORTANT FINDING: a verified, confident, WRONG answer

**This corrects W1 above.** `N06-top-five` did not go from a lost turn to a correct one. It went
from a turn that failed loudly to a turn that succeeds silently at the wrong thing.

The question: *"what share of the book do the top five names carry between them, and is that
tighter or looser than the run before this one"*

The answer, shipped: *"The top five names carry **63.1%** of the book at 2026-09-03. Against the
run before this one, that is unchanged: the prior run's top five also sum to 63.1%, so the book is
neither tighter nor looser."*

Ground truth from `issuer_exposures` on the run it read:

| | names | sum |
|---|---|---|
| the model summed | AAPL, MSFT, LLY, JPM, **XOM** | 63.1% |
| the actual top five | MSFT, AAPL, JPM, LLY, **GOOGL** | **71.2%** |

It included XOM (9th largest, 4.4%) and excluded GOOGL (5th largest, 12.5%). **The answer is
8 percentage points wrong.**

**It never ranked.** The trace shows three `read_book` calls fetching an arbitrary and growing
list of names, then one `add` over the five ids it happened to hold. There is no `rank` call in
the turn.

**And the cross-run comparison is fabricated.** `top_five_share` = 0.6311529 and
`top_five_share_prev` = 0.6311529 — identical to eight decimal places. It read the SAME run twice
and summed the SAME five weights, then reported the result as the previous run's, and concluded
"unchanged". There is no prior run in the trace at all.

**The gate verified both figures.** Both are real ledger rows with real provenance and real
operands. The gate's contract is where a figure came from, not whether it is the right figure —
and "these are the wrong five facts" is outside that contract by design.

### What this says about V25
The N-ary fold removed the arithmetic obstacle that used to make this question fail. It did not add
the constraint that makes the answer right. Before: seven refused `add` calls and a lost turn —
loud, and the reader learns nothing false. After: one clean `add` and a wrong number the whole
verification chain endorses. **Closing a capability gap without the matching constraint converted
a visible failure into an invisible one.**

The desk already owns the primitive that would have caught it — `rank`, which exists precisely
because "the model compared by eye" (V17). Nothing requires a superlative to rest on it.

### X9 — the ordering primitive is used in 4 of 35 opportunities

Across all four traces, 35 turns make a superlative or ordering claim ("largest", "biggest",
"the most", "top five", "worst", "best"). **31 of them make it with no successful `rank` call in
the turn.**

| | turns |
|---|---|
| superlative claimed, ordering computed | 4 |
| superlative claimed, ordering NOT computed | **31** |

(The regex over-catches narrative uses — "the most likely risk", "first" as a discourse marker —
so the true denominator is smaller. The direction is not in doubt: N06's 8-point error is what
this looks like when the eye is wrong.)

`typed_calculator.rank` was built in V17 for exactly this: *"asked which of five holdings carried
the highest accruals ratio, the model laid out five true, correctly cited values and wrote '3.40%
on JPM was the highest, above 4.11%' — every slot true, the ordering false."* The primitive exists,
is one call, and is not reached. Nothing in the desk requires a superlative to rest on it, and
`ranking` scores 3/10 and 2/7 on the two batteries.

---

## X10 — a passage id written where a NUMBER belongs renders as `[10-K Item 7]` — 35 occurrences in 12 turns

`C09-lly-concentration#t2`, asked *"put a number on it — how much of the top line are we talking
about"*, shipped:

> *"The filing says Mounjaro and Zepbound together accounted for **[10-K Item 7]** of total
> revenues in 2025."*

What the model wrote to `respond`:

> `"…together accounted for f_92e5a6314108 of total revenues in 2025."`

`f_92e5a6314108` is a PASSAGE fact — a 10-K Item 7 chunk. The renderer renders a passage inline as
its label. The sentence therefore has a citation label where the figure goes, and the reader gets
no number at all on the one question that asked for one.

**The mechanism is structural, not a slip.** The share is stated only in filing prose; the desk
holds it in `not_held` and not as a figure; the system prompt forbids the model from writing a
number; so the only id it can put in the sentence is the passage's. V24's rule *"a passage inline
is a mark"* made that legal, and the gate accepts it.

The correct move under the desk's own rule is to QUOTE the filing's sentence, so the number arrives
as the issuer's words. Nothing makes the model do that instead.

This is the sharpest argument yet for the pending "解禁写数字" decision: while the model must write
ids rather than values, a figure that exists only inside prose has no id that can stand in a
sentence.

## X11 — a dimensionless ratio rendered as a percent and then called "times"
- `N04-drawdown-anatomy#t2`: *"the book's drawdown is **1523.8% times** the latest attribution return"*
- `N12-sector-drift#t2`: *"MSFT is about **128.3% times** LLY by weight"* (0.1625 ÷ 0.1267 = 1.283)

`RATIO ÷ RATIO = RATIO`, rendered as a percent; the model then wrote "times" around it. The
`MULTIPLE` class exists for exactly this reading and the registry cannot declare it for an ad-hoc
quotient the model names itself.

## X12 — "drift" answered with a single snapshot
`N12-sector-drift#t1` asks whether the sector shape has drifted. The turn touched **no run at all**
and answered with today's weights, then called a level ("trips issuer-concentration warnings") a
drift. A change over time was never fetched — the same missing comparison as X8, without the
fabricated second figure.

## X13 — a missing signpost turned into a false statement to the user

`SERIAL_V24 / N01-earnings-quality` closes:

> *"One figure I cannot give you is **accruals_ratio**: the desk shows that NVDA has no filed fact
> under that metric, so there is no held figure to cite."*

`accruals_ratio` resolves for **all nine issuers** (X6). What happened: the model asked
`read_fundamentals(metric='accruals_ratio')`, which correctly answered `metric_not_filed` —
because it is a formula, not a filed line — and the model read that as the DESK not holding it.
`compute(method='accruals_ratio', subject='NVDA')` produces the figure in one call.

`evaluate_formula` carries the signpost in the other direction (a filed metric asked as a formula
is told to use `read_fundamentals`, added in V19 after a battery burned ten calls on it).
`read_fundamentals` has no signpost back to `compute`. The asymmetry now costs a false statement
to the user, not just a wasted call.

---

## SCORES, FINAL — four runs

| | 2026-09-06 | 09-07 concurrent | 09-07 serial |
|---|---|---|---|
| V21 conversations (31 turns) | 64/87 | 54/87 | 59/87 |
| V24 conversations (20 turns) | 30/53 | 25/53 | **25/53** |

**V21's drop does not reproduce** (spread of 5 between two runs of the same code — the instrument's
own noise, X7). **V24's drop reproduces exactly**: 25/53 twice, −5 against 2026-09-06, with the
same criteria falling both times — `so_what` 5→3 and 2, `precision` 6→4 and 5, `follows_on` 7→5 and 6.

The V24 conversations are the ones that lean on issuer fundamentals, series statistics and price
context — precisely the routes `unknown_series` (X5/W5, 18 occurrences), the `read_fundamentals`
signpost gap (X13) and `describe(expand='filings')` (X3) block.

---

## X14 — the same question, the same code, twice: once right, once 8 points wrong

`N06-top-five` in the SERIAL replicate:

> *"The top five names carry **71.2%**, which is 0.7116 of the book as of 2026-09-03 … the five
> names are MSFT, AAPL, JPM, LLY, and GOOGL. I cannot yet say whether that is tighter or looser
> than the run before this one, because the desk has not been shown the prior run's top-five
> share."*

Correct figure, correct five names, and an honest refusal of the comparison it could not make.
The concurrent replicate of the identical question produced 63.1%, the wrong five names, and a
fabricated "unchanged".

**The failure is not a capability gap; it is unconstrained.** The model sometimes picks the right
five and sometimes does not, and downstream nothing distinguishes the two: both figures are real
ledger rows, both pass the gate, both are rendered with a chip the reader can click. The right
answer and the 8-point-wrong answer are indistinguishable to every mechanism the desk has.

## X15 — ROLE ERRORS: a real figure given a role it does not have

Three shapes of the same defect, all verified by the gate:

| turn | shipped | truth |
|---|---|---|
| `N03-liquidity#t2` | *"the exit would be about **$10.99M days**"* | market value ÷ weight; a MONEY figure called days |
| `N12-sector-drift#t2` | *"MSFT is about **128.3% times** LLY by weight"* | a RATIO of 1.283 rendered as a percent and called "times" |
| `C03-smoke#t3` (serial) | *"its issuer-concentration check is **already at 20.0%**, a breach-level reading of 0.2 … already beyond the warning side"* | the check is at **16.25%**; 0.20 is the BREACH THRESHOLD, not the reading. Ground truth: `current_value 0.16251671, warning 0.15, breach 0.20, status warning` |
| `N06-top-five#t1` | *"the prior run's top five also sum to 63.1%"* | the same run summed twice |

Every figure in that table has correct provenance. The gate's contract is where a number came
from; the ROLE a sentence assigns it — a threshold read as a reading, a stock read as a duration,
a self-comparison read as a time series — is outside it by design (the 2026-09-01 contract).
This run makes the cost of that boundary concrete: four reader-visible wrong statements in 102 turns,
none catchable by any existing mechanism.

## X16 — *"revenue grew from $65.18B to $65.18B"* — the same address on both sides of a growth claim

`SERIAL_V24 / N09-no-forecast#t1` shipped:

> *"revenue grew from **$65.18B** to **$65.18B** over the last reported year"*

What the model wrote:

> `"revenue grew from f_4dde9f980c7b@2025-12-31 to f_4dde9f980c7b@2025-12-31"`

**The same fact, the same period, twice.** `f_4dde9f980c7b` is a SERIES fact holding
`[['2021-12-31', 28.32B], ['2022-12-31', 28.54B], ['2023-12-31', 34.12B], ['2024-12-31', 45.04B],
['2025-12-31', 65.18B]]`. The correct sentence was one address away: `@2024-12-31` to
`@2025-12-31` is +44.7%, a figure the other replicate of this same turn quoted correctly.

The gate accepted it: both addresses resolve, both are real points of a real series, and nothing
forbids the same address appearing twice in a "from … to …" construction. Another X15 role error,
and the fourth reader-visible false statement in the run.

(Not caused by the 2026-09-06 change that made `f_scalar@own-date` legal — this is a series fact,
where `@period` was always legal. The model simply addressed one point twice.)

Note also: the turn's `verified.matches` contains an entry with `value: None` — the series fact
itself, which has points rather than a value. A null-valued entry in the verification record is
not wrong, but it is not a figure either, and it is counted alongside ones that are.

---

## X17 — quality by analyst domain, across all four runs (280 criteria judgements)

| domain | met/total | rate |
|---|---|---|
| `issuer_earnings_quality` | 5/20 | **25%** |
| `book_market_risk` | 11/24 | 46% |
| `book_events` | 5/10 | 50% |
| `book_drawdown_and_attribution` | 9/18 | 50% |
| `book_hypothetical_trades` | 19/36 | 53% |
| `issuer_profitability` | 12/22 | 55% |
| `issuer_outlook_boundary` | 9/16 | 56% |
| `issuer_capital_allocation` | 16/28 | 57% |
| `book_liquidity` | 6/10 | 60% |
| `issuer_business_risk_from_filings` | 24/36 | 67% |
| `book_composition` | 18/26 | 69% |
| `issuer_price_context` | 6/8 | 75% |
| `book_limits_and_triggers` | 7/8 | 88% |
| open diligence (C03) | 16/18 | 89% |

**`issuer_earnings_quality` at 25% is the worst domain by a wide margin**, and it is the one whose
whole method — a measure read as a SERIES over its own history — runs straight through the
`unknown_series` defect (W5, 18 occurrences, concentrated in N01 and N02) and the
`read_fundamentals` signpost gap (X13, which turned into a false statement about `accruals_ratio`).
The domain knowledge is fine; the route it names is blocked.

The two best domains are the two that need no series and no formula: limits (read the run's own
rows and subtract) and open-ended diligence (any evidence counts).

## X18 — a 55-day drawdown "explained" with one session's P&L, and positive numbers called a drag

`SERIAL_V24 / N04-drawdown-anatomy#t2`, asked what drove the drawdown the previous turn had dated
**2026-01-07 → 2026-03-27, 55 sessions to the trough**:

> *"the bigger part was 'something we owned', not pure market beta … Their **drawdown
> contributions** on the run surface were AAPL 0.15%, MSFT 0.43%, GOOGL 0.20%, NVDA 0.07%,
> JPM 0.24%, AMZN 0.11%, TLT 0.01%, HYG 0.01%, LLY −0.01%, XOM −0.05% … the **larger drag** came
> from the equity sleeve, especially AAPL 0.15%, MSFT 0.43%, GOOGL 0.20%"*

Ground truth: those are `issuer_exposures.contribution` on `run_6093c5caee31` — **one session's**
contribution, dated 2026-09-03, six months after the episode ended. Verified against the table:
MSFT +0.43%, JPM +0.24%, GOOGL +0.20%, AAPL +0.15%, … XOM −0.05%. Exactly the answer's list.

Three errors compounded:
1. a single session's attribution used as a 55-day episode's decomposition;
2. **positive** contributions described as "the larger drag";
3. a conclusion drawn from them — "not pure market beta" — that the evidence cannot support.

The desk owns the right method: `book.explain_episode(peak, trough)` returns each holding's
contribution between exactly those two dates. **It was called zero times in all four runs.**

The desk's own rule already says *"a day's P&L contribution is not a sensitivity"* — written for
the rates question. The same confusion reappears for drawdowns, where no rule names it. A rule
that lists one instance of a confusion does not generalise to the next one.

## X19 — a COUNT rendered as `55 on port_001@2026-09-03` (USER REPORT layer)

`SERIAL_V24 / N04#t1`:

> *"How deep: **12.0% on port_001@2026-09-03**. How fast: it took **55 on port_001@2026-09-03**
> to reach the trough, then **24 on port_001@2026-09-03** to get back to the prior peak."*

The renderer appends `on <subject>@<date>` to every fact it substitutes. For a day-count that
produces a sentence with no unit and a spurious date: "55 on port_001@2026-09-03" where the reader
needs "55 sessions". The figures are right (12.0% deep, 55 sessions down, 24 back, recovered
2026-05-01 — all correct against `book.drawdown_episodes`); the rendering makes them unreadable.

---

## X20 — `price.beta` succeeded **0 times in 102 turns**, and the cause is one schema decision

Counting method CALLS by outcome (a correction: the first pass counted mentions, and one call
listed `price.beta` ten times — the substance is unchanged, the magnitude is smaller):

| method | successful calls | failed calls | turns that reached for it |
|---|---|---|---|
| **`price.beta`** | **0** | 5 | 3 |
| `gross_margin` | **0** | 4 | 2 |
| `issuer.panel` | **0** | 2 | 2 |
| `book.analysis` | 1 | 5 | 5 |
| `book.explain_episode` | **0** | 0 | **0 — never attempted** |
| `accruals_ratio` | **0** | 0 | **0 — never attempted** |
| `price.adv` | 3 | 2 | 1 |

`price.beta` works. Called cleanly it returns immediately:

```
compute(method='price.beta', subject='MSFT', params={})              -> beta 0.955 vs SPY
compute(method='price.beta', subject='MSFT', params={'benchmark':'TLT'}) -> beta -0.036 vs TLT
```

Every one of the 5 live calls that named it paired it with an `op`:

```
{"op":"latest","method":["price.beta" ×10],"params":{"benchmark":"TLT"},…}   -> op_or_method
{"op":"latest","method":"price.beta","params":{"benchmark":"SPY"},"subject":[9 tickers]} -> op_or_method
{"op":"avg","method":"price.beta","params":{"last_n":1,…},"subject":[10 tickers]}        -> op_or_method
```

The model is expressing a two-step intent — *run this method over these ten names, then take the
latest / the average* — in one call, because the schema has both an `op` field and a `method`
field and nothing says they are exclusive until the refusal. `compute` refuses the combination
and offers no route.

**This is the highest-leverage single finding of the run.** `price.beta` against TLT and HYG is
the method the desk's own DESK_RULES name as *the* per-name rate and credit sensitivity — the
answer to `book_market_risk`, the domain scoring 46%. It has never once produced a figure in a
live conversation. The 2026-09-06 battery's `op_or_method` refusals (4) and this run's (6) are the
same wall.

It also corrects P15: `price.beta` was not "the exception that got called ten times". It was named
in five calls across three turns and worked zero times. Two of the domain's other named measures,
`accruals_ratio` and `book.explain_episode`, were never attempted at all.

---

## X21 — the knowing-doing gap, measured: 22% of turns called any method their own domain names

For each turn, take the domain its question belongs to, take the methods that domain's `evidence`
段 names, and ask whether the turn successfully called any of them.

| domain | turns that reached their own evidence |
|---|---|
| `book_market_risk` | **0/8 — 0%** |
| `book_events` | 0/4 — 0% |
| `book_limits_and_triggers` | 0/4 — 0% |
| `issuer_earnings_quality` | **0/8 — 0%** |
| `book_drawdown_and_attribution` | 1/6 — 17% |
| `book_hypothetical_trades` | 3/12 — 25% |
| `issuer_capital_allocation` | 3/10 — 30% |
| `issuer_profitability` | 3/8 — 38% |
| `book_liquidity` | 2/4 — 50% |
| `issuer_price_context` | 3/4 — 75% |
| **TOTAL** | **15/68 — 22%** |

Two 0% rows have a mechanical cause and one does not:
- `book_market_risk` 0/8 is X20 — `price.beta` never once returned a figure — plus `book.analysis`
  failing 5 of 6 attempts.
- `issuer_earnings_quality` 0/8 is W5 + X13 — the series route blocked and the signpost missing.
- `book_limits_and_triggers` 0/4 is **not a failure**: the domain names `book.analysis`, and the
  model read the run's limit-check rows directly with `read_book`, which is the better route. That
  domain scores 88% on the rubric. The evidence list, not the model, is wrong there.

So the 22% figure mixes two things: routes the model cannot reach (market risk, earnings quality)
and routes the domain named badly (limits). Both are skill-layer defects; only the first is the
model's.

## X22 — 10% of turns exhaust the 15-call budget, and refused calls are what spends it

| | |
|---|---|
| turns at or over the 15-call turn budget | **10 / 102** |
| worst turn | `C06-new-name-ko#t2` — 31 calls, 16 held back |
| calls held back or not attempted | 91 occurrences across 13 conversations |

The turns that run out are the turns with the most refusals: `C06` (31 calls), `N05-market-or-us`
(22), `C10` (20), `C11#t3` (19), `N07-capex-cycle#t2` (18), `C01#t2` and `N10` (17).
Across the run there were **45 compute refusals and 24 other tool refusals** — roughly 70 calls
that produced nothing, out of a budget of 15 per turn.

Every defect above therefore costs twice: once as the missing figure, and again as the budget the
retry consumed. `N10-margin-debate` spent 17 calls and returned *"I could not produce an answer I
can stand behind"*; `gross_margin`, which answers its question in one call, failed all 4 times it
was named.

## X23 — `op_or_method` blocks the one pattern V25 was built to enable, and its message does not mention the route

Every `gross_margin` method call in 102 turns paired it with an `op`:

```
{"op":"qoq",   "method":"gross_margin","params":{"months":12},"subject":"AAPL"}  -> held behind not_a_quantity
{"op":"latest","method":"gross_margin","params":{"months":12},"subject":"MSFT"}  -> op_or_method
```

The model's intent — **a measure over its own history** — is exactly what V25's `params.last_n`
provides in one call: `compute(method='gross_margin', subject='AAPL', params={'last_n': 8})`
returns the eight-period series, and `yoy`/`cagr` then apply to it. The model never wrote that
shape for a formula. It wrote `op` + `method`, and got:

> `op_or_method: give exactly one of 'op' (arithmetic over operands) or 'method' (a registry method
> over a subject)`

The message says what is forbidden and nothing about what to do instead. Compare the V19 signpost
on `evaluate_formula`, which names the tool that holds the metric — the pattern the desk already
knows works.

Having been refused, the model built the ratio by hand with `divide` (which succeeded), then asked
`qoq` of the resulting fact id and hit `unknown_series` (W5). **Two walls in series, and behind
them the capability that answers the question in one call.**

This is the mechanism behind `issuer_earnings_quality` at 25% / 0% evidence recall,
`issuer_profitability` at 55%, and `book_market_risk` at 46%: all three domains are built on
"a measure, over its history or across a list", and that shape cannot currently be expressed.

---

## X24 — every refusal in the run, ranked by how many TURNS it touched

**183 refusals across 49 of 102 turns.** Nearly half of every turn in the battery hit at least one.

| refusal | occurrences | turns touched | layer |
|---|---|---|---|
| **`op_or_method`** | 15 | **14** | tool schema (X20, X23) |
| `unknown_series` | 23 | 12 | service (W5) |
| `unsourced_figure` | 25 | 11 | validation |
| `invalid_params` | 14 | 10 | tool / skill card |
| `not_on_ledger` | 14 | 10 | validation |
| `metric_not_filed` | 13 | 7 | tool signpost (X13) |
| **`fact_adapter_error`** | 11 | 7 | tool (X3 — worse than the 5 first counted) |
| `unverified_quote` | 10 | 6 | validation |
| `unknown_method` | 8 | 6 | skill namespace (P6) |
| `series_only` | 7 | 3 | service (V25, by design) |
| `unknown_portfolio` | 5 | 4 | agent (invented ids) |
| `kind_does_not_fit` | 5 | 5 | validation |
| everything else (16 codes) | 30 | — | — |

**`op_or_method` touches more turns than any other single refusal**, and behind it sit the two
methods the desk most needs (`price.beta`, `gross_margin`) and the capability V25 added for exactly
that intent (`params.last_n`). It is the highest-value fix in this table.

`fact_adapter_error` at 11 occurrences in 7 turns makes X3 the second: one dead code path,
reproducible on every issuer, costing a call and a route each time it is hit.

---

# WHAT TO FIX, IN ORDER (recommendation only — nothing was changed during the run)

Ordered by turns unblocked per unit of change, from the table in X24.

**1. `op_or_method` — tool schema.** Touches 14 turns; behind it, `price.beta` (0 successful calls
of 5) and `gross_margin` (0 of 4). The model writes `op` + `method` because it means *run this
method over these subjects, then take a statistic*. Either make the refusal name the route
(`params.last_n` for a measure over time; two calls for a statistic over a list) the way V19's
signpost does, or let compute express the two-step. **Layer: tool.**

**2. `describe(ticker, expand='filings')` — dead on every issuer.** 11 occurrences, 7 turns, and
a whole discovery route. The payload's `items_detail` (`{"Item 1A": 3}`) is a numeric leaf under a
non-unit key. Add a fixture for `expand='filings'` first — its absence is why 2,133 tests miss it.
**Layer: tool.**

**3. `unknown_series` — service.** 23 occurrences, 12 turns. `compute_service._stat` resolves the
operand to a `TypedSeries` that knows its own row and then hands `series_stat` the caller's `f_`
ref. Pass the resolved `source_id`. One line. **Layer: service.**

**4. `read_book(run_…)` on an incomplete run.** `run_reads_service._run_or_error` checks existence
and RLS but not status, while `catalogue_service._run` checks status. Make the two agree, so zeros
from a running run cannot become facts. **Layer: tool.**

**5. `read_fundamentals` signpost.** A formula name asked as a metric returns `metric_not_filed`
with no route to `compute`. It cost a false statement about `accruals_ratio`. Mirror V19's
signpost. **Layer: tool.**

**6. Superlatives without an ordering.** 31 of 35 claims; the 8-point error in X8 is what it costs.
The primitive exists (`rank`). This one is not a tool fix — it is a constraint question, and it is
the boss's to decide: does the desk require a superlative to rest on a computed ordering, and if
so, where does that requirement live? **Layer: validation or skill.**

**7. The domain namespace.** Domain names are being passed to `compute(method=…)` and
`read_book(names=…)`. Three vocabularies in one namespace. **Layer: skill.**

**8. The battery itself.** It mutates the desk it measures and cannot resolve 5 points on 87
(X7). Until a conversation gets a frozen book or its own portfolio, no score comparison between
runs means anything. **Layer: test harness.**

Not on this list, deliberately: the role errors (X15, X16, X18). Four of the five reader-visible
false statements in this run are sentences that assign a correct figure a role it does not have,
and the gate's contract excludes sentences by a decision taken on 2026-09-01. Changing that is a
contract change, not a fix.

## X25 — two methods central to their domains were never attempted at all

Recounting by CALL rather than by mention surfaced a category the mention count hid:

| method | calls | why it matters |
|---|---|---|
| `accruals_ratio` | **0** | the core measure of `issuer_earnings_quality`, the domain scoring 25%. It resolves for all nine issuers (X6). The turn that needed it asked `read_fundamentals(metric='accruals_ratio')` instead, got `metric_not_filed`, and told the user the desk does not hold it (X13). |
| `book.explain_episode` | **0** | the only method that answers "what drove this drawdown", by returning each holding's contribution between a named peak and trough. Its absence is why X18 happened: the turn explained a 55-day episode with one session's P&L. |

Neither failed. Neither was reached for. Both are named in their domain's `evidence` list, which
was opened in 3 of 102 turns.

## X26 — the serial configuration was clean, and it shows what the harness needs

| | background jobs started | distinct runs read |
|---|---|---|
| V21 concurrent | 2 | 4 (two created during the battery) |
| V24 concurrent | 1 | 3 (two created during the battery) |
| **V21 serial** | **0** | 2, both pre-existing |
| **V24 serial** | **0** | 2, both pre-existing |

The serial runs started nothing because a fresh completed run (`run_6093c5caee31`, minted during
the concurrent V24 pass) was already there, so no turn needed one. That is the condition, not the
concurrency setting: **a turn starts an exposure run when the book's latest run looks stale, and
from that moment the battery is measuring a desk it is changing.**

The harness fix is therefore two things, not one:
1. run serially, and
2. **seed a fresh completed run before the battery starts**, so no conversation reaches for `start`.

With both, V21 scored 59/87 against the concurrent 54/87, and the honest-absence criterion reached
3/3 — the difference between measuring the desk and measuring the battery's own wake.

---

# PART II — THE EXPANDED BATTERY (V26): 55 conversations, 140 turns

Built from ten orthogonal research angles (buy-side portfolio review, liquidity and redemption,
factor and market risk, attribution and drawdown, forensic earnings quality, credit and solvency,
capital allocation, filings-qualitative, adversarial boundary/refusal, conversational mechanics),
each researched against practitioner and regulatory sources, designed into PM-voice conversations,
then adversarially reviewed for answerability, orthogonality against the existing 51, criteria
assignment and voice. 59 survived review, 10 were cut as duplicates by a completeness critic,
6 were added to fill coverage holes → **55 conversations, 140 turns, 466 criteria assignments**.
Run serially against a book with a fresh completed run (the X26 condition), so no turn started one.

## Y0 — scores: the new set is calibrated to the same difficulty

| criterion | old set (51 turns, serial) | new set (140 turns) |
|---|---|---|
| precision | 11/16 = 69% | 63/87 = **72%** |
| follows_on | 19/26 = 73% | 50/84 = 60% |
| netting | **0/3 = 0%** | 6/10 = **60%** |
| ranking | 5/17 = 29% | 11/20 = **55%** |
| grounded_claims | 26/35 = 74% | 55/100 = 55% |
| honest_absence | 4/6 = 67% | 43/81 = 53% |
| so_what | 11/24 = 46% | 33/73 = 45% |
| trigger | 4/9 = 44% | 5/11 = 45% |
| **TOTAL** | **84/140 = 60%** | **266/466 = 57%** |

Three points on shape: `netting` and `ranking` finally score, because the new questions ask for
them in forms the desk can actually deliver (the old set asked for a ranking of things `rank`
refuses). `grounded_claims` falls to 55% because the new set leans much harder on filings text —
see Y2. `honest_absence` sits on 81 of 140 turns; the critic that assembled the set flagged this
itself as over-assignment, so read 53% as "the desk names a gap when one is present" and not as a
clean measure.

## Y1 — THE DOMINANT ERROR: a method name passed to `read_book` — 110 times in 38 turns

| name passed to `read_book(names=…)` | times |
|---|---|
| `book.analysis` | 37 |
| `book.drawdown_episodes` | 24 |
| `book.reconcile` | 23 |
| `book.explain_episode` | 20 |
| four DOMAIN names | 6 |

**110 mentions in 106 `read_book` calls, across 38 of 140 turns.** Every one returns `unknown` +
`nearest`, and the model then tells the reader the desk does not hold the thing.

`book.drawdown_episodes` called cleanly returns immediately:

```
compute(method='book.drawdown_episodes', subject='port_001', params={'span':'1y'})
 -> 2 episodes: peak 2026-01-07, trough 2026-03-27, depth 11.96%, recovered 2026-05-01,
                55 days down / 24 back;  and a second, 6.24%, 18 down / 13 back
```

It was requested 24 times through `read_book` and **zero** times successfully through `compute`.
Six of the run's 16 false-absence claims come from this one confusion:

> *"the desk does not hold a drawdown-episode section for this portfolio"*
> *"the drawdown helpers are not held on the run"*
> *"there is no held figure for the episode calendar, and no method on the desk that turns the
> current max drawdown into elapsed time"*

All three are false. This is P2/P6 from the regression, at its true scale: **three name
vocabularies — run-table names, method names, domain names — share one slot, and nothing marks
which tool consumes which.** In the regression it looked like a medium-severity annoyance (7 and 1
occurrences). Across a wider question surface it is the single most frequent error in the system.

## Y2 — X10 scales with the question: 59 passage marks in 15 turns

Up from 35 in 12 turns. The new set asks more of the questions whose figure lives only in filing
prose, and each one produces the same broken sentence:

> *"Exxon says long-term debt excluding finance leases has **[10-K Item 8]** due within one year"*
> *"the 2027 bucket is in **[10-K Item 8]**"*
> *"…including dividends and share repurchases (**[10-Q Part I, Item 1]**)"*

The amount is simply absent from the sentence. Where the desk holds no fact and the model may not
write a number, the only id available is the passage's, and the renderer prints its label.

## Y3 — false absences nearly quadrupled: 16, against 4 in the regression
Concentrated on `price.drawdown` / `book.drawdown_episodes` (6, all Y1), `price.volatility` (2),
`price.beta` (3). Every one is a route the model could not address, reported to the reader as a
capability the desk lacks.

## Y4 — what the wider surface unblocked
44 distinct methods were called, against 17–20 in the regression; only 15 of 46 were never touched.
Methods that scored zero successes across all 102 regression turns produced figures here:
`gross_margin` 2/2, `issuer.panel` 3/3, `accruals_ratio` 2/3, `price.beta` 4/11 (from 0/5).
`op_or_method` still fired 14 times and `unknown_series` 23.

## Y5 — the gate refused 119 times across 140 turns; 77 turns (55%) hit at least one
`unverified_quote` 35, `not_on_ledger` 31, `unsourced_figure` 25, `id_in_prose` 12,
`kind_does_not_fit` 11. `unverified_quote` leading is new and follows from Y2's territory: the new
set quotes filings far more, and a quotation that is not verbatim in a cited passage is refused.

## Y6 — superlatives without an ordering: 30 of 34 (88%), unchanged from the regression's 89%
A wider question surface did not change it. `rank` remains a primitive nothing requires.

## Y7 — domain cards were opened 3 times in 140 turns
`describe` was called 165 times: 93 at `expand='book'`, 39 `fundamentals`, 18 `filings`,
7 `methods`, 4 `readings`, **3 `procedures`**, 1 bare. The level-1/level-2 split behaves exactly as
it did in the regression and on 2026-09-06: the model does not open the card.
