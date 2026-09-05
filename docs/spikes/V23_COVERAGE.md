# V23 coverage — the catalogue, one compute, ten tools, measured

Companion to docs/IMPLEMENTATION_PLAN_V23.md. 2026-09-05. Phases A–D built and
deployed; E (the comparison block) waits on decision 4; readings carry no
typical range (decision 1 open).

## §1 What changed, in numbers

| surface | before | after |
|---|---|---|
| tools on the meta face | 44 | **10** (describe, read_fundamentals, read_filings, read_prices, read_book, compute, think, search_web, start, respond) |
| tools on the research face | 25 | **8** (the six shared + search_web + submit_brief; its compute refuses book methods by subject kind) |
| methods promoted to tools | 13 | 0 — all in `analytics/skill.py` (46 methods: 32 formulas + issuer.panel + 7 price + 6 book, each with `authority` and `fails_when`; a constructor error otherwise) |
| skill entries | definitions only (32 formulas, 29 metric notes) | + 17 readings (qualitative) + 13 procedures (the battery's angles) |
| catalogue | three tools, three formats, 34k chars to see the desk | one `describe(subject)`; live default layers: desk 5.9k, MSFT 7.8k, KO 4.8k, port_001 2.8k, run 7.0k (ceiling 8k) |
| kinds of absence the model can cite | 1 (a tool refused) | 3 (not_reported / not_held / cannot), as data |
| descriptions + schemas on the meta face | 31,003 chars | **11,363** (target 6k not met: respond's block grammar and compute's op list are most of it — registered) |
| `_SYSTEM` | 3,072 chars, names nine tools | the contract; names the entry point and the discipline |
| budget unit | a tool call | an assistant message (`agent_sessions.charged_message_id`, `v23_budget_per_message.sql`, applied live) |
| offline suite | 2100 | **1822** passed (the collapse removed per-tool parametrised cases; `test_v23_catalogue_and_compute` 40) |

## §2 Live, first rebuild (2026-09-05) — what the catalogue still got wrong

Four questions through the deployed face. The model reached for `describe`
first in every turn (unprompted by name), `compute(op=subtract, run_…:…)`
on the second call of turn 1, `read_filings(item='7')` when the figures were
not held. Everything it did wrong was something the CATALOGUE let it do:

| turn | what went wrong | cause | closed by |
|---|---|---|---|
| rates, 100bp | `describe(subject="null")` → company_not_found; then `describe("port_")`, `read_book("port_")` | the schema said null, the model wrote the string; nothing said where the portfolio ids are | desk aliases (`""`, `null`, `None`, `desk`…) all mean the desk; the description and the prompt say a book question starts at describe() with no subject, never a guessed id |
| trim MSFT | describe(MSFT) put three names on the table and not the book's market value; the model then wrote `issuer_exposures.MSFT.market_value` bare and `book_market_value*0.15` as operands | a held issuer's catalogue was a map without the four figures a trim is arithmetic over; no `scale` op; a bare name's refusal did not say "add the row" | a held issuer's entry puts its three columns, its check's three tiers, the alert's columns and `exposure_metrics.portfolio_market_value` on the table, and lists the run's methods (book.sell …); `scale` is an op with `params.factor`; a bare run name is told `run_<id>:<name>` |
| AMZN vs MSFT cash | eight `read_fundamentals` calls guessed metric names (`capital_expenditures`, `repurchases_of_common_stock`…); the first refusal held the other seven, twice | the default fundamentals layer gave counts, not names; the refusal listed nothing; the batch hold was by tool (V21 §7 residual) | the layer lists the 37 names; `metric_not_filed` carries `available` and `held_on: {metric}`; `agents/batch.holds` holds only calls repeating the named argument |
| sell NVDA | computed the room, then wrote "without running a scenario" — and did not run one | describe(NVDA) listed issuer and price methods; `book.sell` is a run method and was not in the issuer's catalogue | `methods_on_this_run` and the portfolio procedures ride on the held-issuer entry |

## §3 Live, second and third rebuilds

**Second rebuild** (desk aliases, held-issuer names, metric names, argument-scoped
hold, `scale`, bare-name refusal):

| turn | what happened |
|---|---|
| rates, 100bp | describe() → **`compute(method='price.beta', params={benchmark:'TLT'}, subject=[ten tickers])` — one call, ten betas** — the per-name rate sensitivity the desk had called `cannot` since V21 (C04 substituted day contributions for it). Answer: a ranked name-by-name map with the honest caveat that it is historical sensitivity, not a shock loss. 20 figures verified |
| AMZN vs MSFT cash | the first `read_fundamentals` guessed names; the refusal's `available` list was read and the next eight reads (both issuers, four metrics) used the desk's names; the argument-scoped hold let AMZN's four wrong names each be refused while MSFT's copies of the SAME wrong names were held — the V21 §7 shape, right this time. Then `calc_…:capex@2025-12-31` as an operand was refused `undated` (a series point had no operand form) and the turn degraded |
| trim MSFT | `book.sell` at a fraction, then `proceeds` could not be slotted (the scenario row published no name for it); two `limit_value` names guessed for `warning_level` with no nearest-name hint |
| sell NVDA | computed weight gaps instead of a scenario; describe() at the desk level did not say how a scenario is run |

Closed by: `trade.proceeds` / `trade.sold.<T>.market_value` / `.fraction` on the
scenario row; `unknown_name` carries the five nearest names the row holds; a
series point `head@period` is an operand with its own period (live: AMZN
capex@2025-12-31 − buybacks@2024-12-31 typed as money over two windows); the
desk's portfolio entries carry the scenario call.

**Third rebuild** — the same four questions with KO in place of rates:

| turn | calls | refusals | what the desk produced |
|---|---|---|---|
| sell NVDA | describe → `book.sell` (one wrong params shape, then right) → respond | 4 (grammar) | a before/after table whose after-columns read `after sale of NVDA …`, 15 figures verified; prose says the rest of the book tightens and names MSFT, AAPL, JPM, LLY over their lines. It says "remains over" for AAPL and JPM, which the sale pushed over — a reading, not a figure |
| trim MSFT | describe → `multiply(MV, warning)` → `subtract(MSFT MV, that)` → respond | **0** | "position $1.79M, warning threshold $1.65M, sell **$138K**", 8 s, three figures cited — the V22 route, found unprompted |
| AMZN vs MSFT cash | describe(expand=fundamentals) ×2 → **nine `read_fundamentals` in one message, all with the desk's names** → two `read_filings` queries → respond | **0** | one table (two issuers × capex, OCF, buybacks, debt series) and three paragraphs: Amazon reinvest-first, no buyback, debt rising; Microsoft reinvesting AND returning $22B, debt flat; a bottom line. 18 figures verified, 15 citations. **The V21 C05 turn shipped four rows and no sentence; this one is the analysis** |
| add KO at 5% | describe → `book.buy` (one wrong params shape, then right) → respond | 2 | a before/after mandate table (gross exposure, LLY, MSFT, KO's own check), "no new breach; LLY and MSFT stay the warnings", an offer to test displacement. 16 figures verified. The prose carries three NAMES written as text after two refusals ("at limit_checks.issuer_concentration:KO.current_value of the book") — a name in prose has no digits and the gate lets it through |

What the third round says about the division of labour: given a catalogue that
names things, the model chose the method (book.sell, book.buy, price.beta over
a list), the route (MV × tier, then subtract) and the comparison (AMZN against
MSFT on four uses of cash) without any tool description telling it to. Where
it still fails, it fails in the grammar (a name written as text; a wrong params
shape on the first try; heterogeneous table rows) and in reading ("remains"
for a name the sale pushed over), not in what it looked at.

## §4 Residuals (registered)

- **A name written as text passes the gate.** `limit_checks.issuer_concentration:KO.current_value` in prose has no digits; the text rule does not see it. A closed lookup (a run string equal to a name the table holds) would refuse it — a validation change, and by the 9/1 contract the boss's to make.
- **First params shape wrong** for book.sell / book.buy on the first call ("shares": "all"; a flat ticker/weight): `invalid_params` carries the schema and the second call is right, so it costs one round trip, not the turn. describe(expand=methods) shows the params; the default layer shows only names.
- **Heterogeneous table rows** (a run cell and a scenario cell in one row) are still laid out by the model; the V21 §4(a) defect and the status box's item ④, unchanged.
- **"Remains over" for a name the sale pushed over**: a reading error the desk's figures contradict on the same table. The comparison block (decision 4) is the structural answer.

- **Description surface 11.4k, not 6k.** respond's grammar is the gate's contract and stays; compute's op enum could move behind describe. Not done this batch.
- **Readings carry no typical range** (decision 1). **No comparison block** (decision 4).
- **`tests/battery/questions_round4*.json`** name old tools in their keep-lists; `scripts/ablation_battery.py --arm narrow` would deny every tool until they are rewritten. Left as is: the ablation arm is not part of the current battery.
- **Ten-name reads still ten calls?** No: `read_fundamentals` is per ticker, but the budget is per message, so ten reads in one message cost one unit. `compute(method, subject=[…])` is one call.
- **describe(desk) under the owner role lists every portfolio**; under RLS it lists the caller's own plus the public one.

## §5 The conversation battery, three runs (2026-09-05)

Same 13 conversations, 31 turns, three stacks: V21 (44 tools, 9/4), V23 (10
tools), V23-R (V23 plus the two closed grammar refusals below).

| criterion | V21 | V23 | V23-R | | deterministic | V21 | V23 | V23-R |
|---|---|---|---|---|---|---|---|---|
| so_what | 3/15 | 6/15 | **10/15** | | verified figures | 228 | 309 | **325** |
| ranking | 3/10 | 4/10 | 4/10 | | citations | 90 | 103 | **119** |
| trigger | 4/6 | 5/6 | 3/6 | | gate refusals | 15 | 17 | **14** |
| grounded_claims | 16/22 | 13/22 | 13/22 | | slot written as string | 9 | 15 | **1** |
| precision | 6/7 | 4/7 | 5/7 | | name written as prose | 2 | 7 | 5 |
| follows_on | 13/18 | 13/18 | 12/18 | | calls held behind a refusal | 22 | 19 | **1** |
| netting | 1/2 | 0/2 | 0/2 | | turns lost to the gate | 2 | 3 | 2 |
| no_linear_locating | 4/4 | 4/4 | 4/4 | | tool calls | 228 | 240 | 237 |
| **total** | 50/84 | 49/84 | **51/84** | | | | | |

**What moved.** The tool path straightened (V21: five entry points rotating —
evaluate_formula 39, get_flow 21, snapshot 20, describe_issuer 16,
read_quantities 16; V23: describe 41 → read_fundamentals 47 → compute 38).
`so_what` 3 → 6 → 10 across two independent judge passes with a causal chain
(procedures give the close a shape; the grammar fix lets more turns reach
it). The refusal mix changed from all-grammar (15/15) to part-evidence (V23:
5 `unsupported_assertion`, 2 `unknown_name`) — the gate began reporting
capability gaps rather than spelling.

**The two closed grammar refusals (V23-R).** A turn-by-turn diff of V21 vs
V23 showed 27 malformed answers of which 22 were two shapes the gate could
name and did not: a slot serialised into a string (C08#t1 sent the identical
one NINE times and lost the turn) and a table name written as prose (C09#t2
shipped `risk_alerts.issuer_concentration:LLY.current_value` to the reader).
Both are lookups: `slot_written_as_string` (an object literal carrying ref
and name, whatever quoting survived) and `name_written_as_text` (a COMPOUND
name the session's table holds — only names with a dot, colon or @, so
`capex` and `proceeds`, which are words, are left alone). The resolver hands
the table's names to `validate_shape`; no sixth invariant. Result: slot as
string 15 → 1, held calls 19 → 1.

**The two turns still lost are registered capability gaps, not grammar.**
C03#t3 ("has it been building?") — no cross-run series exists; the model said
so correctly, then cited a run id it had recalled from the transcript and was
refused `not_on_table` six times. C09#t1 — the model read "top six products
accounted for 82 percent" in the 10-K and could not write it: a figure inside
a verified quotation is still refused (V21_CONVERSATIONS §9 item 0, the status
box's item ②).

**Found on the way.** `describe()` at the desk lists 7 portfolios in storage
order; four are empty development probes and the real book is seventh — a
catalogue that mirrors storage rather than salience.

**On the scores.** One judge pass each; 14 regressed / 13 improved / total
50-49-51 is mostly noise. Trusted: the deterministic columns, and `so_what`
(two runs, same direction, large). Not trusted: `trigger` 5 → 3 with no
related change between the runs. The rubric also scores an honest "the desk
does not hold this split" (V23's C04#t2) below V21's substituted wrong figure
— a criterion for correct abstention is missing from the battery.

**Gaps after this batch, by root cause** (the architecture discussion of
2026-09-05, recorded in the topic log): the ontology admits one kind of truth
(a computed quantity) where the desk has four (computed, attested verbatim,
structural attribute, checked absence); the book world has an algebra (V22)
and no calendar; the catalogue mirrors storage and the session has no focus;
knowledge is delivered at discovery (describe) and not at use (the table
slice carries a path, not an identity). The proposed redraw — the model writes
pointers and argument, the desk fills facts and shows what each fact IS, the
gate resolves pointers in session scope and checks their kind — is a
restructuring, not a batch, and waits on the boss.

