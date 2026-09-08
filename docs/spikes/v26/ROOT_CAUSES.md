# V26 root causes — three classes, and the design link each rests on

Companion to `FINDINGS.md` (the 242-turn run, finding by finding) and to the seven-layer
frame the desk is discussed in: **agent/LLM → MCP → tool → service → skill → validation →
user report**. FINDINGS ranks by severity and names a layer per finding. This note does the
other thing: it groups every finding by the logic underneath it, records the failure cases
each class produced, names the link in the frame whose *design* the class rests on, and keeps
the log of what is decided per class. Written 2026-09-07 after scoring, before any fix.

Three classes, for the three things the model does with the desk: **find, fetch, say.**

| class | what fails | reader sees | mechanical fix? |
|---|---|---|---|
| 1 — inbound (find) | the name the model writes is not the name the tool validates | a false absence, a burnt budget | yes |
| 2 — outbound (fetch) | the value a service produces is not the Fact the adapter mints | a zero as a fact, a dead route | yes |
| 3 — saying | a true figure given a role its identity does not carry | a false sentence | no — a contract question |

Classes 1 and 2 are one design decision seen from two sides. Class 3 is a different
question and is recorded here only so the map is complete.

---

## The frame, and where the two classes rest on it

The three layers between the model and the data are each defined by what they must NOT
contain:

- **tool** — a capability verb, domain-agnostic, a thin wrapper; its schema is resident.
- **service** — the code behind the verb; the model cannot see it and it has no name.
- **skill** — knowledge, read not executed; it names no tool.

Each definition is right. Together they exclude one thing from every layer: **the binding
between a name and its consumer, and between a value and its identity.** No layer owns it, so
it defaults to the agent — whose definition is *judgement*. The binding is not judgement; it is
a lookup. A lookup assigned to the judgement layer is done by the model on its own initiative,
and the run measures what that costs.

The code shows the boundary exactly. In `tools/definitions.py`, compute's `op` is an enum from
`compute_service.OPS`; describe's `expand` is an enum from `catalogue_service.EXPANDS`; the
price methods' `window` is an enum. None of those three produced a wrong-door call in 242
turns. compute's `method` and read_book's `names` are free strings, and between them they
produced 110 + 15 + 13 wrong-door calls. The difference is ownership: `op` and `expand` are
vocabularies the tool owns, so the shared constant is legal; method names are skill's, row
names are analytics', filed metrics are concept_mapping's — vocabularies the tool, by
definition, may not import. So the schema is left blank and the refusal can only say "no",
never "where".

**Class 1 is that boundary inbound. Class 2 is the same boundary outbound**: a service returns
an untyped dict, and `fact_adapters` reconstructs identity from key names. V24 §2 diagnosed
"small problems recur because identity is rebuilt at the gate from storage" and fixed it at the
gate; the same reconstruction still happens one layer down, at the adapter, and it is the
adapter's guess that X1 (silently) and X3 (loudly) show failing.

This note's claim, stated once: **the framework's design gap is in the tool layer's
definition — "thin" was read as "untyped".** A thin wrapper that types its arguments from
skill's registry and its returns from a service's declaration is still thin and still
domain-agnostic in code; the domain is data.

---

## Class 1 — inbound: the name the model reads is not the name the tool validates

Seven mechanisms. Every one costs recall or budget; none costs a wrong figure. Their shared
terminus is a false absence: when a name reaches the wrong door the model tells the reader the
desk does not hold the thing.

### 1a — three vocabularies, one slot

Run-row names (`alerts`, `limit_checks`, `issuer_exposures.MSFT.weight`), method names
(`book.analysis`, `price.beta`, `gross_margin`), domain names (`book_liquidity`,
`issuer_profitability`) are all written into the same free-string parameter, and nothing marks
which tool consumes which. The `book.` prefix on six methods reads as the run's book section.

| case | call | outcome | reader saw |
|---|---|---|---|
| Y1 (new battery) | `read_book(names=[book.analysis ×37, book.drawdown_episodes ×24, book.reconcile ×23, book.explain_episode ×20, domain names ×6])` | `unknown` + `nearest`, 110 mentions in 106 calls, **38 of 140 turns** | six false absences: *"the desk does not hold a drawdown-episode section for this portfolio"*, *"the drawdown helpers are not held on the run"* |
| P2 smoke t2 step 14 | `read_book(ref=run_aacdb498c66f, names=["book_liquidity","positions"])` | `unknown` | liquidity answered as concentration (P4) |
| P6 C01-trim-one#t2 | `compute(method=[issuer_profitability, issuer_earnings_quality, issuer_credit_and_balance_sheet, issuer_capital_allocation], params={last_n:4}, subject=[LLY,MSFT])` | `unknown_method` | one call burnt |
| C05-amzn-capital#t2 | `compute(method='capex', params={last_n:4})` | `unknown_method` (capex is a filed metric) | growth rates hedged, both criteria lost |
| W8 (V24 ×6) | `read_fundamentals(metric="cash and cash equivalents" / "total debt" / "shareholders' equity" / "capital_expenditures" / "depreciation_and_amortization")` | `metric_not_filed` | six calls burnt; real names are `cash_and_equivalents`, `capex`, `depreciation_amortization` |
| W7 | `compute(method='price.adv', params={window:'3m'})` | `invalid_params` (card says `window_days`) | one call burnt |
| X24 | 11 non-methods passed to `compute(method=…)`: filed metrics, domain names, the ops `rank` and `yoy` | `unknown_method` ×8 in 6 turns | — |

`book.drawdown_episodes` was requested 24 times through `read_book` and **0 times through
`compute`**, where it answers in one call.

### 1b — one thing, two ids

A series fact is `f_…` to the model (minted by the adapter at the tool boundary) and a
calc_ledger row id to `series_service`. `typed_calculator._resolve` translates; `_stat`
resolves, sees a `TypedSeries`, then hands `series_stat` the caller's `f_` — which
`load_series` cannot find. Introduced by the V25 `_stat` rewrite (`eed93f1`).

| case | call | outcome |
|---|---|---|
| P3 smoke t2 step 20 | `compute(op='latest', operands=['f_d3a4d95af2aa'])` | `unknown_series` |
| P9 (V21 ×3) | `pct(f_43b130725a16)`, `latest(f_f223f201c354)`, `pct(f_f223f201c354)` | `unknown_series` |
| W5 N08-whats-in-the-price#t1 | `max`/`min` over the 1y price series | answer says *"compute will not accept that series id for max/min"* and then guesses *"upper end of its range"* with no figure |
| C05-amzn-capital#t2 | `yoy` on a fact id | `unknown_series`; turn hedges |
| total | regression 18 + new battery 23 | **41**, 12+ turns; `issuer_earnings_quality` 0/8 evidence recall, 25% rubric |

The V25 compute description ("a statistic over one series …") tripled the model's attempts at
exactly this shape. Every attempt landed here. Net effect of that description change: worse.

### 1c — two intents, one call

`compute` is two verbs in one tool: arithmetic over operands (`op`) and a registry method over a
subject (`method`). The schema allows both fields; the model fills both when it means *run this
method over these subjects, then take a statistic* or *this measure over its own history*; the
refusal says "give exactly one" and names no route.

| case | call | outcome |
|---|---|---|
| X20 | `{"op":"latest","method":["price.beta"×10],"params":{"benchmark":"TLT"}}` | `op_or_method` |
| X20 | `{"op":"latest","method":"price.beta","params":{"benchmark":"SPY"},"subject":[9 tickers]}` | `op_or_method` |
| X20 | `{"op":"avg","method":"price.beta","params":{"last_n":1},"subject":[10 tickers]}` | `op_or_method` |
| X23 | `{"op":"qoq","method":"gross_margin","params":{"months":12},"subject":"AAPL"}` | held behind `not_a_quantity` |
| X23 | `{"op":"latest","method":"gross_margin","params":{"months":12},"subject":"MSFT"}` | `op_or_method` |
| P8 | `{"op":"avg","method":"net_debt_to_ebitda","subject":[8 tickers]}` | `op_or_method` |
| W6 N10-margin-debate | 17 calls, 4 gate refusals, `gross_margin` never called cleanly | turn lost: *"I could not produce an answer I can stand behind"* |
| total | **15 occurrences, 14 turns** — the refusal touching the most turns of any (X24) | `price.beta` **0 successes in 5 calls over 102 turns**; `gross_margin` 0/4; `book_market_risk` 0/8 evidence recall |

`price.beta` called cleanly returns at once (0.955 vs SPY, −0.036 vs TLT). It is the measure the
desk's own rules name as THE per-name rate and credit sensitivity.

### 1d — a refusal that says "no" and not "where"

V19 gave `evaluate_formula` a signpost (a filed metric asked as a formula → "use
read_fundamentals"). The reverse and the sibling were never built. A tool by definition does not
know skill's registry, so its refusal cannot say "this is a method".

| case | call | outcome | reader saw |
|---|---|---|---|
| X13 SERIAL_V24 N01-earnings-quality | `read_fundamentals(metric='accruals_ratio')` | `metric_not_filed` (correct: it is a formula) | *"One figure I cannot give you is accruals_ratio: the desk shows that NVDA has no filed fact under that metric"* — **false**; it resolves for all nine issuers |
| P10 (V21 ×3) | `metric='free_cash_flow'`, `'net_debt_to_ebitda'`, `'total_debt'` | `metric_not_filed` | calls burnt |
| Y1 (all 106) | `read_book(names=[a method])` | `unknown` + five nearest ROW names | the six false absences above |

### 1e — knowledge is pulled, not pushed

Skill is defined as content that is read. The channel was never designed and defaulted to pull:
level 1 of `describe` gives a domain's name and two `asked_as` phrases; the `evidence` list is
behind `expand=<domain>`. Measured: what is pushed is read; what must be pulled is not.

| evidence | measurement |
|---|---|
| domain cards opened | 1/23 (09-06), 1/31 and 0/20 (regression), **3/140** (new battery; `describe` called 165 times: book 93, fundamentals 39, filings 18, methods 7, readings 4, procedures 3) |
| turns that reached any method their own domain's `evidence` names | **15/68 = 22%** (X21); `book_market_risk` 0/8, `issuer_earnings_quality` 0/8 |
| methods never attempted in 102 turns | `accruals_ratio` (core of the 25% domain), `book.explain_episode` (the only answer to "what drove this drawdown") (X25) |
| P1 smoke t1/t2 | `describe(subject=null, expand='book')` → level 1; never opened `book_liquidity`; *"the desk does not hold a daily-volume figure for MSFT"* — false, `price.adv` is listed by name in the same payload |
| P16 C04-rates-100bp#t2 | the `per_name_factor_sensitivity` absence fact says "use price.beta with TLT"; the answer quotes it and stops at "not held" |
| W10 N04-drawdown-anatomy | *"the drawdown-episode and explain-episode rows are not held on the run surface"* — both are portfolio methods |
| `book_limits_and_triggers` 0/4 | not a failure: the domain's `evidence` names `book.analysis`, the model read the run's limit rows directly, which is the better route; that domain scores 88%. The evidence list is wrong there |

And the push channel demonstrably works: `DESK_RULES` render at every describe level, and N09
says *"the desk does not forecast"*, W4 applies the participation-rate rule so hard it
over-refuses, and one sentence added to the resident `compute` description tripled series-stat
attempts (1b).

### 1f — skill asks for what service refuses

| case | call | outcome |
|---|---|---|
| P12 C05-amzn-capital#t1 | `rank(capex, buybacks, debt_repayment)` — the `issuer_capital_allocation` compare段 says *"the ordering of the uses"* | `incomparable_quantities` (rank takes one measure across holders, V17) |

### 1g — invented ids

| case | ids | outcome |
|---|---|---|
| P11 | `port_?`, `port_1`, `run_85acaef8d4c` | `unknown_portfolio` ×5 in 4 turns; the desk-level describe lists the real ids |

### Cost of class 1, in one place
- 183 refusals in 49 of 102 turns (X24); 45 compute refusals + 24 other tool refusals ≈ 70
  calls that produced nothing, on a budget of 15 per turn.
- 10 of 102 turns exhausted the budget; worst `C06-new-name-ko#t2` 31 calls, 16 held back (X22).
- 16 false-absence claims in the new battery against 4 in the regression (Y3).
- 36 of 46 registry methods never called in the regression (P15); 15 of 46 in the new battery (Y4).

---

## Class 2 — outbound: the value a service produces is not the Fact the adapter mints

"Born whole" (9/1) is a tool-layer contract. The tool is a thin wrapper and enforces nothing;
birth actually happens in `fact_adapters`, which checks a Fact's own fields (I1 no digits in
note, I2 as_of/window, I3) and nothing about the source it came from.

### 2a — two doors, one status check

| case | trace | shipped |
|---|---|---|
| X1 C07-vol-rising#t1 | step 18 `read_book(ref=run_af342695cf2b, names=[risk_state, alerts, attribution])` on a run still RUNNING (started the same turn, read 5 s later — X2) | *"The only current run facts are that **0 has no limit checks evaluated, 0 has no checks fired**, and the alert section is empty, so there is no new evidence of a volatility breach."* — gate-verified, real ledger rows |

`catalogue_service._run` refuses `status != "completed"` (`run_not_completed`);
`run_reads_service._run_or_error`, which `read_book(run_…)` goes through, checks existence and
RLS only. Two doors into one room; one is locked. The desk's own rule — *"a risk no factor
measures is reported unmeasured, not zero"* — has no enforcement at the door.

### 2b — the adapter guesses "figure" from a payload key

| case | trace | outcome |
|---|---|---|
| X3/X4/P7/W9 | `describe(ticker, expand='filings')` on NVDA, AMZN, LLY×2, MSFT, JPM (`'Part II, Item 1A'`), KO | `UnknownUnit: no unit declared for numeric key 'Item 1A'` → `fact_adapter_error`; **11 occurrences in 7 turns**; dead on every issuer; the whole filings discovery route |

`catalogue_service._filings` adds `items_detail = {"Item 1A": 3, …}` only under `full=True`.
That is a structural property ("Item 1A has three chunks"), not a figure — one of the four
kinds of truth (计算量 / 逐字转述 / 结构属性 / 经查缺席) the 9/5 discussion said the ontology does
not distinguish. The adapter walks every numeric leaf and must mint or die; it died correctly.
No fixture covers `expand='filings'` (`tests/test_fact_adapters.py` has fundamentals and
methods only), which is why 2,133 offline tests miss it. Present since V24 over a key added in V23.

### 2c — prompt and gate disagree on a prose number

| case | what the model wrote | rendered | count |
|---|---|---|---|
| X10 C09-lly-concentration#t2 | `"…together accounted for f_92e5a6314108 of total revenues in 2025."` (a PASSAGE fact) | *"accounted for **[10-K Item 7]** of total revenues"* | 35 in 12 turns (regression) |
| Y2 (new battery) | *"long-term debt … has **[10-K Item 8]** due within one year"*, *"the 2027 bucket is in **[10-K Item 8]**"* | the amount absent from the sentence | **59 in 15 turns** |

FINDINGS called this structural and pointed at the pending "write numbers" decision. **That
was the wrong layer.** `gate.check` G3 resolves a prose number first against the ledger, then
against the cited passages (`ledger.resolve_in_passages`, tested in `test_ledger.py`); a number
that appears verbatim in a cited passage is accepted and rendered as a link to the passage. What
forbids it is `_SYSTEM`: *"You never write a number: a figure, counts included, is the FACT'S
ID"*. Two encodings of one convention, no shared constant, no symmetric test — and the model
obeys the one it reads. The fix is one sentence in the prompt; the gate does not move.

### 2d — data cover (not the framework)

| measure | resolves for (of 9) |
|---|---|
| `accruals_ratio` | 9 |
| `ebit_interest_coverage` | 8 (JPM refused as a bank — correct) |
| `free_cash_flow`, `days_inventory` | 7 |
| `total_debt`, `net_debt` | 5 |
| `gross_margin`, `ebitda` | 4 |
| `roic` | 3 |
| `debt_to_ebitda`, `net_debt_to_ebitda` | **2** (AMZN, XOM) |

On MSFT, 12 of 46 methods do not resolve; every one traces to `total_debt` `incomplete_cover`
as of 2026-03-31 and cascades (net_debt, debt_to_ebitda, net_debt_to_ebitda,
debt_to_operating_cash_flow, fcf_to_debt, invested_capital, roic). This is ingest/mapping
cover after the V9 concept split, below the frame. Every layer above it behaved correctly:
`C06-new-name-ko#t2`'s *"I can't make the exact leverage comparison … from the figures this
desk holds"* is honest. Consequence for the battery: any `issuer_credit_and_balance_sheet`
question is an honest-absence test for 7 of 9 issuers whether the author meant it or not.

---

## Class 3 — saying: identity stops at the chip (recorded; discussed separately)

Every fact carries kind, unit, window and an address (V24). The gate checks that a pointer
resolves, fits its kind, and that prose carries no unsourced figure. The words around the
pointer are outside the contract by the 2026-09-01 decision. Five reader-visible false
statements in 102 turns, all gate-verified:

| case | shipped | truth |
|---|---|---|
| X8 N06-top-five#t1 | *"the top five carry **63.1%** … the prior run's top five also sum to 63.1%"* | true top five 71.2%; the model summed AAPL, MSFT, LLY, JPM, **XOM** (9th) and omitted GOOGL (5th); no `rank` call; "prior run" = the same run summed twice. The serial replicate (X14) answered 71.2% correctly and refused the comparison honestly |
| X15 C03-smoke#t3 | *"issuer-concentration check is **already at 20.0%**"* | current 16.25%, warning 0.15, **breach threshold 0.20** |
| X15/W3 N03-liquidity#t2 | *"the exit would be about **$10.99M days**"* | market value ÷ weight = MONEY; the unit algebra allowed the row, not the sentence |
| X15/X11 N12-sector-drift#t2 | *"MSFT is about **128.3% times** LLY by weight"* | RATIO 1.283 rendered as a percent, then called "times" |
| X16 N09-no-forecast#t1 | *"revenue grew from **$65.18B** to **$65.18B**"* | `f_4dde9f980c7b@2025-12-31` on both sides; the other replicate wrote +44.7% correctly |
| X18 N04-drawdown-anatomy#t2 | a 55-session drawdown "explained" with `issuer_exposures.contribution` of one session six months later; positive numbers called "the larger drag" | `book.explain_episode(peak, trough)` called 0 times in all runs |
| X9/Y6 | superlative claimed with no ordering computed: **31/35** regression, **30/34** new battery | `rank` exists (V17) and nothing requires a superlative to rest on it |
| X12 N12-sector-drift#t1 | "has the sector shape drifted" answered from one snapshot, no run touched | a level reported as a change |
| X19 N04#t1 | *"it took **55 on port_001@2026-09-03** to reach the trough"* | renderer appends `on <subject>@<date>` to every substituted fact; COUNT printed without a unit — figures correct, sentence unreadable |

Rendering holds the identity that would make each of these visible (kind=threshold,
unit=MONEY, MULTIPLE, the series address, the window) and prints none of it beside the
model's words. That half needs no contract change. The other half — whether the gate looks at
the sentence — is the boss's decision, with three routes on the table (resident skill rule /
sentence-shape constraint / critic as measurement). Not this note's subject.

---

## Not the framework: the instrument

Same code, two runs, 5 points apart on 87 (X7). The battery starts exposure runs mid-run and
nine turns then read a run another conversation created (X26); `search_web` reads a live
internet; the judge is a model whose own docstring says it reports a distribution, never a
verdict on one run. All counts in this note are mechanical and reproducible; no rubric delta
between runs is. Condition for a comparable run: serial, a fresh completed run seeded before
the first turn, ≥2 replicates, distributions reported.

---

## Design direction (proposed, not decided)

Not a new layer. One word in the tool layer's definition: **thin ≠ untyped.**

1. **Inbound — one name table.** A view (not a fifth copy) over the four owners — skill's
   methods and domains, `resources.RUN_CHILDREN`, `concept_mapping.SUPPORTED_METRICS`,
   `compute_service.OPS` — giving each name its kind and its consumer tool. Tool schemas derive
   their enums from it where the vocabulary is finite (`method`), and every "unknown" refusal
   looks the name up in it and says which door it belongs to. The name the model reads and the
   name the tool validates become one constant. This is the 8/3 rule ("guards derive from the
   signature, never a hand-written list") applied to domain vocabulary. Model-facing ids are
   `f_` only; internal ids never appear in a tool argument; translation happens once at the
   boundary (1b is a leak of that rule, one line).
2. **Outbound — a service declares what it returns.** A return is a declaration of identity
   (kind, unit, subject, window, settled/in-flight), not a dict the adapter walks. Completeness
   is part of identity, so two doors cannot disagree on it. Structural properties are declared
   as such, never as numeric leaves.
3. **Delivery — push what is measured to work.** Each domain's `evidence` (and `this_desk`)
   into the resident describe layer; `compare`/`close`/`absent` may stay behind expand. The
   refusal is the other push channel (move 1). Fix `book_limits_and_triggers`'s evidence.

Class 1 and class 2 disappear as categories under these three, rather than case by case.
Class 3 is untouched by them — and X8 shows that opening class 1's routes without class 3's
constraint converts a loud failure into a silent one.

---

## Discussion log

### Class 1 — inbound (opened 2026-09-07)
_pending — decisions to record: whether tool may derive from the name table; `method` as a
schema enum vs free string + typed refusal; `compute`'s two verbs (forbid both / define
op+method as a pipeline / split the tool); what goes resident in describe; rank over several
measures of one subject; whether `book.*` methods are renamed._

#### Research (2026-09-07): how production agent apps do tool discovery at scale

The boss's question: describe hands the model names without "what this is, which tool takes
it, which argument" — and if every name carried a full description the context would blow up.
What does production practice do?

**The measured problem is the same everywhere.** Anthropic: "A typical multiserver setup …
can consume ~55k tokens in definitions before Claude does any work" and "Claude's ability to
pick the right tool degrades once you exceed 30–50 available tools." OpenAI: "Aim for fewer than
20 functions available at the start of a turn." RAG-MCP measured selection accuracy 43.13% →
13.62% as the catalogue grew. LiveMCPBench (70 servers, 527 tools): "Retrieval errors account
for nearly half of all failures" — the same shape as Y1 here (110 wrong-door calls, the
dominant error).

**Five production patterns, and what each discloses to the model:**

| pattern | who | mechanism | unit disclosed | numbers |
|---|---|---|---|---|
| deferred loading + search | Anthropic tool search; OpenAI `tool_search`; Claude Code MCPSearch (auto at 10% of context) | all definitions stay server-side; resident = search tool + 3–5 hot tools; search matches **names, descriptions, argument names, argument descriptions**; returns `tool_reference`, API expands to the **full schema** (+ `input_examples`) | a callable definition | 85% fewer tokens; Opus 4 49→74%, Opus 4.5 79.5→88.1%; recommended at ≥10 tools or >10k tokens |
| code as tools / filesystem | Anthropic code execution with MCP; Cloudflare Code Mode | each callable is a typed file at `servers/<service>/<fn>.ts`; agent lists and reads only what it needs; or `search_tools` with a detail level: **name only / name+description / full schema** | a typed signature whose **path is its consumer** | 150k → 2k tokens; cost: a sandbox |
| retrieval before the call | LangGraph many-tools / BigTool; RAG-MCP | embed tool descriptions, retrieve top-k per query, bind only those | a definition | RAG-MCP: >50% fewer prompt tokens, 3× accuracy |
| hierarchy / toolkits | AnyTool (category tree); MCP-Zero (active request → server → tool routing, 2,797 tools); Tool-Planner (cluster by function, plan at toolkit level) | narrow the space top-down before choosing | a category, then a definition | MCP-Zero: 98% token reduction on APIBank |
| few strong verbs + strict schema + namespaces + examples | Anthropic "writing tools" / "define tools"; OpenAI best practices | consolidate into fewer tools with an `action` parameter; prefix names by service/resource; "use enums and object structure to make invalid states unrepresentable"; strict mode = grammar-constrained sampling (OpenAI: "always enable"; enum cap 1,000 values); `input_examples` | a schema the model cannot violate | examples: 72% → 90% on complex parameters; descriptions "at least 3–4 sentences" |

**The common property.** In every pattern the thing disclosed to the model is a *callable
definition* — at minimum name + one sentence + argument names — never a bare name. Even the
cheapest level of the code-execution pattern ("name only") is a file whose path names the tool
that consumes it. Anthropic's heuristic states the test: "If a human engineer can't definitively
say which tool should be used in a given situation, an AI agent can't be expected to do better."

**The context worry is answered by *when*, not *whether*.** No production guidance shortens
descriptions to names to save context; all of them keep full descriptions and defer *loading*.
The desk did the opposite: it kept the tool count at ten (the pattern-5 half) and moved the
volume into free-string arguments whose values are disclosed as bare names in one describe —
i.e. it built only the "name only" level and skipped the "name + description + call shape"
level that every pattern treats as the minimum unit of discovery.

**Mapping to D1–D6 (recommendation, not decision):**
- the `methods` entry becomes a callable row: name, one sentence, `compute(method=…, subject=…,
  params={…})`, yields — ~60 tokens each; by subject that is 13 rows (~570 tokens) at level 1,
  46 rows (~2.4k) for the desk;
- names carry their consumer (both vendors: prefix by service/resource); `book.*` methods
  colliding with the run's `book` group is exactly the collision namespacing exists to prevent;
- `method` becomes an enum under strict mode (46 ≪ 1,000; gpt-5.4-mini supports strict) so a
  wrong-door name is unrepresentable rather than refused; `names` and `metric` stay free
  strings but the refusal returns the nearest entries from **all three** vocabularies with their
  consumer (the two-step lookup pattern), not the nearest row names only;
- domain `evidence` names methods by name, not by a paraphrase (retrieval and search index
  name + description; a paraphrase indexes nothing);
- one `input_examples`-style call per method card (the 72→90% result is for exactly the
  `window`/`window_days` and `{fact: id}`-in-a-string class of error).

Sources: Anthropic tool search docs; Anthropic "Advanced tool use"; Anthropic "Code execution
with MCP"; Anthropic "Writing effective tools for agents"; Anthropic "Define tools"; Anthropic
"Effective context engineering"; Anthropic strict tool use; OpenAI function-calling guide;
OpenAI structured-outputs limits (community announcement); LangGraph many-tools / BigTool;
RAG-MCP (arXiv 2505.03275); MCP-Zero (arXiv 2506.01056); Tool-Planner (arXiv 2406.03807);
Dynamic ReAct (arXiv 2509.20386); LiveMCPBench (arXiv 2508.01780); AnyTool (arXiv 2402.04253);
OpenAI community thread on long enum lists; getunblocked "MCP tool overload" measurements.

#### Design mapping (2026-09-07): three of the patterns, on this codebase

Measured baseline (today's tree, tiktoken o200k):

| surface | size |
|---|---|
| resident tool schemas, read core (7 tools) | 1,884 tokens; `compute` alone 593 |
| `describe(None)` / `port_001` / `run_…` / `MSFT`, level 1 | 2,159 / 1,748 / 2,886 / 2,830 tokens |
| `describe('MSFT', expand='methods')` (full cards) | 7,219 tokens; `port_001, expand='procedures'` 3,853 |
| registry methods | 46: issuer 33, price 7, run 4, portfolio 2 |
| one *callable row* per method (name, one sentence, call shape, yields) | 51 tokens avg; issuer 1,393 / price 458 / run 391 / portfolio 120 |
| `method` as an enum of all 46 names | 248 tokens |
| other vocabularies | 47 filed metrics; 161 row names on a run (7 groups); 14 domains; 16 rules |
| loop limits | 80k soft context; 15 calls/turn; tool result cap 28k chars; describe ceiling 8k chars |

**Pattern A — hierarchy / routing (AnyTool tree, MCP-Zero server→tool, Tool-Planner toolkits).**
The desk already *is* this pattern: `describe(None)` → `describe(subject)` → `expand=<domain>`;
levels = desk → subject kind → domain (`skill.PROCEDURES`) → leaf (`skill.METHODS`,
`resources.RUN_GROUPS`, `concept_mapping.SUPPORTED_METRICS`). Three departures from the
pattern: the leaf is a bare name; the domain level is not linked to leaves by name
(`Procedure.evidence` is prose, `book_limits_and_triggers` points at the wrong leaf); and the
router is the model descending, which it does in 3/140 turns.

| variant | where | model sees | cost | kills | tension |
|---|---|---|---|---|---|
| A1 callable leaf | `catalogue_service._methods(kind, full=False)` renders `{name, describes, call, yields}`; `call` computed from the name's KIND (Method→compute, row→read_book, metric→read_fundamentals) — skill stays tool-free, the binding lives in the catalogue | `book.drawdown_episodes — every peak-to-trough … — compute(method='book.drawdown_episodes', subject='port_001', params={span}) → …` | +120 port / +391 run / +1,393 issuer at level 1 | Y1's 24 `read_book(book.drawdown_episodes)`, P2, part of P1 | issuer level 1 grows past the 8k-char ceiling → pair with A2 |
| A2 domain→leaves by name | `Procedure` gains `methods: tuple[str,…]`, validated at construction against `METHODS` and the domain's subject kind (the "author must remember → constructor error" rule); level 1 lists each domain's method names; `expand=<domain>` returns that domain's callable rows | `book_liquidity: methods [price.adv, …]` | ~200 tokens at level 1; ~300 per opened domain | X21's wrong evidence list; P16/W10 absence-read-as-refusal; X25 never-attempted methods | V25's "no tool is named in skill" — methods are skill's own names, not tools; holds |
| A4 refusal routes across the tree | one `catalogue.route(name)` over the four vocabularies, called by every `unknown` refusal in compute / read_book / read_fundamentals | `book.drawdown_episodes is a portfolio METHOD: compute(method=…, subject='port_001', params={span})` | 0 resident; ~80 tokens per refusal | Y1 (110), X13 (13), P6, P10, T3/T4's dead ends | none; "one module kills the class" |

**Pattern B — retrieval before the call (LangGraph/BigTool, RAG-MCP, Anthropic BM25 search).**
Nothing question-driven exists: `describe` is subject-driven; the only retrieval is name→name
difflib (`skill.nearest`, read_book's `nearest`), one vocabulary at a time. `Procedure.triggers`
(14 × 5 phrases) is an index nothing reads.

| variant | where | model sees | cost | kills | tension |
|---|---|---|---|---|---|
| B1 `describe(subject, about=…)` | BM25 (or lexical) over one name table: name + describes + params + yields + domain triggers/evidence; ~270 entries, deterministic, no embeddings; returns top-k callable rows with kind and domain | `about='days to liquidate each name'` → `price.adv (method) …`, `book_liquidity (domain) …` | ~400 tokens per call | P1, X20 (rate sensitivity → price.beta/TLT), W8 | a parameter on describe, not an 11th tool |
| B2 loop-side push | `meta_agent.handle_message`: before the first `llm.chat` of a turn, run the same index over the user message and inject top-k rows as a system line | "the desk's index suggests …" | ~400 tokens/turn | the 3/140 pull problem, without waiting for the model to ask | a lexical step on the context path; harmless when it misses; measure on the battery before adopting |
| B3 deferred loading / dynamic enum | rebuild compute's enum per call from discovered names | — | — | — | **not worth it**: the whole vocabulary is 248 tokens; the vendors' thresholds (≥10 tools, >10k tokens) do not bind here |
| B4 refusal = retrieval | the unknown name is the query; same index as B1 | as A4 | as A4 | as A4 | none |

At this scale retrieval is for routing a *question* to a *name*, not for saving context. Load
everything (enum + callable rows); retrieve to route.

**Pattern C — few strong verbs, strict schema, namespaces, examples.**
Present: 10 verbs; enums for `op`/`expand`/`window`; `additionalProperties: false`; nullable
types; jsonschema validation before spend (`registry.invoke` → `validate_args`). Absent: `strict`
is never set in `tool_session._as_openai_tool`; `method`/`names`/`metric` are free strings; the
run group key `book` collides with the `book.*` method prefix; no examples except the desk's
`scenario` line and `read_with`. **D1 is already answered in code**: `tools/definitions.py`
imports `skill` and `_compute_for` reads `skill.METHODS[m].subject_kind` for the face guard —
the tool layer already consumes skill's table; an enum is the same import used once more.

| variant | where | model sees | cost | kills | tension |
|---|---|---|---|---|---|
| C1 enums + strict | `method`: anyOf[enum of `skill.methods_for(kinds)`, array of it, null] per face; `metric`: enum of `SUPPORTED_METRICS`; `strict: true` in `_as_openai_tool` (OpenAI: every property required + nullable; respond's block grammar `oneOf` → `anyOf`) | 46 names on every call, in the schema | +248 (method) +~200 (metric) resident | `unknown_method` (8), formula-as-metric (13: X13/P10), W8 (6), P6 (4), `not_on_this_face`; wrong-door names become unrepresentable, not refused | `names` cannot be an enum (161 dynamic labels) → A4 covers it |
| C2 namespaces | cheap: rename the run group key `book` (one string in `resources._DECLARED_GROUPS`); full: methods named by subject kind — `run.analysis`, `portfolio.drawdown_episodes`, `issuer.gross_margin` — so the name states its `subject` | — | 0 | the `book`/`book.*` collision | full rename touches `calc_ledger` provenance (method names stored on rows) → alias or migration; do the cheap one now |
| C3 examples | OpenAI has no `input_examples`; the callable row *is* the example; one example block in respond's description for `{fact: id}`-in-a-string (13 in V24) | — | ~100 tokens | W7 (`window`/`window_days`), part of `pointer_written_as_text` | none |
| C4 don't make the model fill what is known | callable rows carry the concrete id (`subject='port_001'`, `ref='run_…'`) | — | 0 | P11 invented ids | "never guess an id" stays |
| C5 the two verbs (D3) | (a) strict anyOf branches `{op, operands}` \| `{method, subject, params}` make op+method unrepresentable — two calls, silently; (b) define op+method as a pipeline: set-stat/rank + method + subject list = method per subject then the stat; series op + method + one subject + `last_n` = the series then the op; (c) split into two tools | — | 0 | `op_or_method` (15/14 turns), `price.beta` 0/5, `gross_margin` 0/4 | (b) composes V25's own two features; (a) hides the route; (c) breaks "ten" |

**Recommended combination (revised after the self-audit in TREE_SPEC.md):** C1 + A1 + A2 +
A4/B4 + B1; B2 not built (measure first); B3 no; C2 cheap now, full rename with an alias later;
C5: (a) structural exclusivity plus compute's one macro sentence on composition — (b)'s two
enumerated combinations were a case rule; (b) only if two-call composition measurably fails. Resident cost ≈ +450 tokens;
describe level 1 ≈ +120 (portfolio) / +391 (run) / issuer via A2 (+200, rows behind the domain).
Unchanged by any of this: class 2 (outbound) and class 3 (saying) — A1/B1 make the routes
reachable; nothing here makes the model rank (X8).

#### Pattern A, measured: what the tree lacks (2026-09-07, all 244 turns of the six battery files)

A correction first: earlier notes (and FINDINGS P1) say the model "never opened the domain
(`expand=<domain>`)". **A single analyst domain cannot be opened.** `EXPANDS` is six data-domain
values (`fundamentals, methods, procedures, book, filings, readings`); `expand=procedures` opens
every domain of the subject kind at once (3,853 tokens for a portfolio, 5,068 for an issuer);
`expand=methods` opens every card (7,219 for MSFT). The tool description and `how_to_read` both
promise "expand=<domain> opens one domain's detail". `unknown_expand` fired 0 times because the
enum forbids the attempt — the model reaches for `book` instead.

| defect | code fact | battery signature |
|---|---|---|
| 1. the root does not descend and does not say so | `describe()` → `_desk(db)`; `expand` is ignored at the desk | 114 of 308 describe calls are `describe(subject=None, expand='book')`; 105 of 244 turns open with it; the payload is the bare root; 0 refusals. In 67 of those 105 turns the second call is `read_book` on a run or portfolio by guessed names — the level that lists names (`describe(run_…)`) is skipped because the model believes it has already opened "the book" |
| 2. the promised step is missing | no per-domain expand; level 2 is "everything" | `expand=procedures` 7 times, `expand=methods` 9 times in 308 calls |
| 3. one leaf type is finished, the other is not | run rows: group → `answers` → names/patterns → `read_with` → `units`; methods: bare names | wrong-door names: read_book got 91 method names + 9 domain names; compute got 34 filed-metric names + 6 domains + 4 ops; read_fundamentals got ~38 method names + ~25 human-language names |
| 4. the address does not carry its level | `book.*` spans two subject kinds (run: analysis/reconcile/sell/buy; portfolio: drawdown_episodes/explain_episode); issuer formulas have no prefix; a run's figure name is advertised at the desk root beside the portfolio (`market_value_name: … on run_…`) | 47 read_book failures carry no method name: figures asked on `port_`, `positions` asked on `run_`, sections on an invented run id — a name valid on one ref kind used on another |
| 5. three partitions, one link | leaves are partitioned by data domain (tools/expands), by subject kind (where methods hang), by analyst domain (procedures); only subject kind → methods is a link; domain → methods is prose (`evidence` ≠ `describes`); data domain → methods does not exist (`expand='book'` shows rows, not book methods) | `book_limits_and_triggers` points at the wrong leaf; X21 22% evidence recall |
| 6. no hot set, no routing step | 16 rules resident (they work); 0 methods resident; question → domain → leaf is the model's unassisted reading | 3/140 domain cards; `price.adv`/`price.beta` absent from every level-1 payload as anything but a name |
| 7. failure does not re-enter the tree | each door's refusal returns `nearest` from its own branch (row labels / method names / `available` metrics) | 16 false absences in the new battery, 6 from one name |
| 8. overloaded words | `book` = expand value, run group key, method prefix, domain prefix; `domain` = data domain and analyst domain in the same `how_to_read` sentence | — |

The rows branch shows the pattern works here: it has a question per group, the names under it,
the call beside it, and its failures are "asked on the wrong ref", never "did not know what it
was". The methods branch has none of those four things.

What "done well" means, in the tree's own terms (adds A0 to the A-variants above):
**A0** the root routes `expand` (to the latest run's book, or refuses `expand_not_at_desk`) and a
single domain is an `expand` value; **A1** every leaf is a callable row; **A2** domain → leaves by
name, constructor-checked; **A4** every refusal routes across the tree; a hot set (the subject's
own methods as callable rows) is resident; `book`/`domain` un-overloaded.

#### Enhancement design for the tree (proposed 2026-09-07, for discussion) — level-by-level spec in `TREE_SPEC.md`

Criterion (boss, 2026-09-07): the tree returns facts and addresses and never resolves intent on the model's behalf — a root that routes `expand='book'` to a run would hide the wrong call instead of teaching the address (the no-fallback rule). `route()` returns the correct call and never forwards it.

Principle: every payload the tree returns answers three questions in its own fields — *where am
I* (`level`), *how do I open the next level* (`next`: concrete calls), *how do I call what is
listed here* (`call` on every leaf). Skill stays tool-free; the catalogue computes `call` from a
name's KIND, and one name table is the shared constant behind the enums, the refusals and the
search.

| level | today | enhanced | cost |
|---|---|---|---|
| L0 resident | 10 schemas (read core 1,884 tok), `_SYSTEM` | `method` enum per face (248), `metric` enum (~200), `strict: true`, one legend paragraph in `_SYSTEM` (the tree's shape + which tool eats which name), one clarifying line per read tool | ≈ +700 |
| L1 root `describe()` | portfolios, issuers, 5 data domains, methods by kind (bare), 14 procedures (question + 2 phrasings), rules, not_held, cannot | + `next` (concrete `describe(port_001)`, `describe('MSFT')`, `describe(run_…)`); each domain carries `open: describe(<subject>, expand='<domain>')` and its method names; `expand` at the root is **unrepresentable** (describe's schema: `{subject: null, expand: null}` | `{subject: string, expand: enum}`; under strict it cannot be written, without strict the registry refuses it with the two-step address). The root never resolves intent: `open` uses a placeholder subject (`describe(<port_…>, expand='book_liquidity')`); concrete ids appear only at the subject level, where they are facts | 2.2k → ~2.4k |
| L2 subject | portfolio: sections + read_with, runs, methods (bare), 7 procedures; run: groups + read_with + units, methods (bare); issuer: fundamentals/filings/prices summaries, methods (bare), 7 procedures | the subject's own methods as **callable rows** (the hot set); domains with `methods: [names]` + `open`; `next`; a run's figure names appear ONLY under the run (the desk/portfolio point at the run) | port 1.75k → ~2.4k; run 2.9k → ~3.4k; issuer 2.8k → ~3.5–4.2k |
| L3 one node | `expand=procedures` = every domain (3.9k/5.1k); `expand=methods` = every card (7.2k) | `expand=<domain>` opens ONE domain: the card + its methods as rows with params and an example call + the rows/metrics it reads; `EXPANDS` = data domains + `PROCEDURES` names, derived | ~1–1.5k per domain |
| leaf | a bare string | `{name, is, does, call, yields}`; `is` ∈ {issuer method, price method, run method, portfolio method, run figure, portfolio section, filed line, domain, op} — `is` names the consumer | 51 tok/row |
| refusal | `nearest` from one branch | `route(name)` → `{name, is, call}` or nearest across all vocabularies with their `is`; used by read_book, compute, read_fundamentals | ~80 tok/refusal |
| search | none | `describe(subject, about='…')`: BM25 over the name table (name, does, params, yields, domain triggers/evidence) → top-k rows with `is` and domain | ~400 tok/call |

Code locations: `catalogue_service` (`_desk` routing + `next`; `_methods` → rows; `_procedures` →
names + `open`; new `_domain()`; `EXPANDS` derived; new `name_table()`, `route()`, `search()`;
`describe` built per face like `_compute_for`); `skill.Procedure.methods` (constructor-checked);
`resources._DECLARED_GROUPS` (rename the `book` group key); `tools/definitions.py` (enums derived
from `skill.methods_for(kinds)` / `SUPPORTED_METRICS`; refusals call `route`; descriptions);
`tool_session._as_openai_tool` (`strict` + schema normalisation: all properties required,
nullable, respond's `oneOf`→`anyOf`; which keywords gpt-5.4-mini's strict accepts is to be
tested); `meta_agent._SYSTEM` (legend). Guards: Procedure.methods ⊆ METHODS with matching
subject kind; every `call` string in a payload parses and validates against its tool's schema
(symmetric test); every name in the table has exactly one `is`; `EXPANDS` ⊇ PROCEDURES;
DEFAULT_CEILING re-pinned per level by the live test.

Order: name table + route + enums → callable rows + next + domain open → root schema (expand needs a subject) → strict
→ `about=` → tests/ceiling → battery (serial, seeded run, two replicates). No new DESK_RULES in this batch: rules stay definitions.
Open: rename scope (group key only vs methods by subject kind with aliases); strict feasibility
on gpt-5.4-mini; issuer L2 density (33 rows vs names under domains); D3.

**Built 2026-09-07** as the one-page plan in TREE_SPEC.md (MODULE_NOTES M27): name table, rows with is/does/call, domains as expand values, root refuses expand, enums, routed refusals. Offline 2145 green. Battery not yet re-run.

### Class 2 — outbound
Discussed 2026-09-08 under the four-role rule; fix plan by role boundary in `docs/IMPLEMENTATION_PLAN_V28.md` (with the three remaining class-1 items). **Built 2026-09-08** (M28): A1 series over values, A2 shapes in the schema, B1 comparability from identity, C1 one run door, C2 declared units, D1 one prose rule. Offline 2191 green.

### Class 3 — saying
_not yet discussed; gate-contract decision._
