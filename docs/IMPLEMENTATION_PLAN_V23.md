# V23 — the catalogue, one compute, and the skill that says how to read

Status: **proposed** (2026-09-04), not built. Written from the code as it
stands after V22 (commit `5422fa4`); every count below was measured, not
recalled, and the plan is a basis, not an authority — the code is.

## §0 The decision this plan executes

The boss's division of labour, settled 2026-09-04 after the conversation
battery (docs/spikes/V21_CONVERSATIONS.md) and the V22 discussion:

> Get the catalogue right, then hand "what to look at, what to compare, what
> to say" to agent intelligence plus skill.

Three kinds of decision, and where each belongs:

| decision | example | belongs to |
|---|---|---|
| what is true of the world | overlapping flows do not add; EBIT starts from net income; a weight is a share of ITS book | `compute`'s type rules and the method registry — unchanged |
| what to look at, what to compare, what a figure means | which measure answers a demand shock first; which window; whether to close on the held weight | **the agent, informed by the catalogue and by skill** |
| how to say it | a figure is a slot; a quotation is verbatim; a ref is on the table | the gate — unchanged (six invariants, 9/1 contract) |

Today the middle row is scattered over four places that were never designed
to hold it: 44 tool descriptions (31,003 characters of description and
schema on the meta face — ten times the system prompt's 3,072), the prompt,
thirteen tools that pre-decide what to look at (panels), and constants in
code (`integration._RISK_SENSE`). Every "use this for…" sentence is a
judgement taken from the agent, and every battery finding added another —
the rule-patch shape the desk's own philosophy rejects, migrated from the
prompt into the descriptions.

What the battery says about the agent's own judgement (V21_CONVERSATIONS
§11, re-read for this plan): where the catalogue was visible it chose well
(C02#t2 picked gross margin, inventory and operating cash flow for "which
risk shows up first", then died on grammar; the first live V22 turn chose
`hypothetical_book` on the first call; the trim question was answered by a
route nobody designed). Where it failed — substituting a true figure for the
asked one (C04, C13), fabricating a run id, resending an identical refused
answer — the cause was a missing catalogue entry ("this quantity is not
held"), a missing reading ("what does 0.23× mean for an energy issuer") or a
refusal that did not teach. None of those is fixed by another tool.

## §1 What is built today (measured)

| surface | now | note |
|---|---|---|
| tools on the meta face | 44 (research 25; READ_CORE 23) | 20 read a row, 5 are arithmetic primitives, **13 are methods promoted to tools**, 4 delegate, 2 reflect/exit |
| ways to read one run | 7 | snapshot, describe_run, read_quantities, get_risk_state, get_attribution, list_run_alerts, get_portfolio_analysis |
| price tools | 9 (`price_analytics_service._TOOL_SPECS`) | 2 read a series, 7 are one statistic each |
| method data | formulas.py 32 (10 families); semantics.py 29 metric notes + 6 worked examples; containment 11 edges; methods.py 8 sentences; withheld.py | **three shapes for one concept**: a formula is data run by `calculate`; a price statistic is a tool; headroom and net beta are a panel service |
| catalogue payloads | describe_issuer(MSFT) 14,928 chars (37 metrics × {metric, periods, latest}, 32 formulas, fiscal calendar); describe_run 7,746 (189 names in 7 groups, factored); get_portfolio_snapshot 11,479 | three formats, three calls, 34k characters to see what the desk holds |
| model-visible rule surface | 31,003 chars descriptions+schemas; 3,072 `_SYSTEM` | |
| the gate | 6 invariants (`services/resolver.py`) | unchanged by this plan |
| limiters | turn 15 calls, session 40, external search 5, context 80k, batch hold, quota | six mechanisms on one dimension |
| absences the desk can state | one kind: a tool refused (`absence.*` rows) | "not held as a figure" and "no method on this desk" have no row and cannot be cited — substitution follows |

## §2 The target: five domains × five verbs, ten tools

The orthogonal axis is data domain × verb, not question. Every tool sits in
exactly one cell; no cell has two.

| verb \ domain | issuer figures | issuer text | prices | book | desk & web |
|---|---|---|---|---|---|
| **describe** | `describe(subject)` — one tool across all domains | | | | |
| **read** | `read_fundamentals` | `read_filings` | `read_prices` | `read_book` | `search_web` (read_book also reads briefs, tasks, ledger rows by name) |
| **compute** | `compute(method \| op, operands, params)` — one tool, the ledger's only write | | | | |
| **start** | `start(kind, subject)` — readiness, research run, exposure run | | | | |
| **respond** | `respond`, `think` — unchanged | | | | |

Ten tools: describe, read_fundamentals, read_filings, read_prices,
read_book, search_web, compute, start, respond, think. The research face is
the same set less read_book.

**One grammar for read, compute and cite.** Every figure the desk holds has a
name under a ref (V15); V22 made `ref:name` an operand. Here it is also what
`read_book` selects by and what a slot cites by: the model learns one
spelling. `read_*` and `compute` accept lists (ten issuers, ten names) so a
"by name" question is one call — which is what retires the budget's
per-call unit (§5).

### §2.1 describe(subject)

`subject` is a ticker, a portfolio id, a run id, a scenario row id, or
absent (the desk itself). One format for all five. The default layer is
existence, counts, date ranges, what is missing, and the NAMES of the
methods that apply — not their definitions; `expand=<domain>` returns a
domain's detail (the 37 metrics with kind and windows; the run's names
factored as today). Ceiling for the default layer: 8,000 characters, pinned
by a live test on every subject kind (describe_issuer's 12KB ceiling is the
precedent).

    describe("MSFT")
      identity      ticker, CIK, sector, investigable, in_book: weight 16.3% on run_… (2026-09-03)
      fundamentals  37 metrics 2019-Q1..2026-Q1, FY ends Jun; 22 flow / 15 instant
                    not_held: segment and product revenue, geography (prose only, Item 7)
                    methods: 32 named, 29 computable, 3 not (missing D&A …)
      filings       10-K 2025, 10-Q ×3; items indexed 1, 1A, 7, 7A; 412 passages
      prices        2019-01-02..2026-09-03 daily adj_close; splits: none
      book          position $1,785,420; checks: issuer_concentration 15% / 20%; alert: warning
      desk          brief 2026-08-19; ledger rows about MSFT this session: 4
      cannot        per-name factor sensitivity (book-level regression only); VaR/ES/stress withheld

Three kinds of absence, all as data, none as sentences:

| kind | today | in the catalogue |
|---|---|---|
| the issuer did not file it | `absence.*` rows from a refused read | unchanged |
| the desk does not hold this kind of figure | invisible (0 dimensional facts of 73,861; segment figures only in prose) | `not_held` per domain, with where it IS (prose, `read_filings`) — derived from the concept map's coverage, not written by hand |
| the desk has no method for it | `_FACE_CAPABILITIES.cannot`, four hand-written lines, returned by describe_run only | `cannot`, derived from the method registry's subject kinds + withheld.py; citable, so an absence block can say "no method" without a tool having refused |

The third row is what stops C04's contributions-as-rate-sensitivity and
C13's capex-intensity-as-segment-mix at the source: the honest sentence has
evidence to point at.

### §2.2 compute

The four operators, `rank`, the series statistics and the regression stay
as ops. Everything else the 13 promoted tools did becomes a METHOD in one
registry (§3) that `compute` executes:

| today's tool | becomes |
|---|---|
| evaluate_formula, get_fundamental_panel | `compute(method=<formula>, subject=ticker)`; a family or a list of methods in one call is the panel |
| get_rolling_volatility, get_beta, get_momentum_12_1, get_distance_from_52w_high, get_adv, get_drawdown, get_market_stats | price methods (`price.volatility`, `price.beta`, …) over `read_prices`' series; `_TOOL_SPECS`' nine entries are already data and move as they are |
| get_portfolio_analysis (headroom, net beta), reconcile_move, get_drawdown_episodes, explain_episode | book methods (`book.headroom`, `book.net_exposure`, `book.reconcile`, `book.drawdown_episodes`) over a run; `_RISK_SENSE` moves into the registry as the data it is |
| hypothetical_book | `book.sell` (and `book.buy`, the half V22 did not build — C06#t3) |

`compute` validates `params` against the method's own declared schema
(`arg_validation`, as today, per method instead of per tool); an unknown
method name answers with the nearest names (V21_CONVERSATIONS §5, item 8).
The typed calculator's refusals — R1–R3, units, the V22 base rules — are
untouched: they are the world's structure and stay in the one place that
computes.

### §2.3 What happens to the rest

| today | target |
|---|---|
| describe_issuer, describe_run, get_portfolio_snapshot | describe |
| get_flow, get_balance_sheet, get_balance_series | read_fundamentals (window \| instant \| series is a parameter, as get_flow's already is) |
| search_filing_passages, get_filing_section | read_filings (query \| item) |
| get_price, get_price_series | read_prices |
| read_quantities, get_portfolio_positions, list_risk_limits, get_risk_state, get_attribution, list_run_alerts, list_alerts, get_run_freshness, read_issuer_brief, get_task_status | read_book(ref, names) — positions, limits, alerts, freshness, a brief's sections and a task's state are names under their refs |
| ensure_company_ready, start_issuer_research, start_exposure_run | start(kind, subject) |
| search_external_research | search_web |

Evidence declarations go from 32 hand-written `Evidence(...)` in
definitions.py (plus the price specs' own) to one per tool, derived from the
domain: a read of domain D puts D's ids on the table; compute puts calc_
ids; start puts task ids; search_web puts src_ ids. `test_symmetry`'s "every
prefix has a source" pin stays.

## §3 Skill: one registry, three kinds of entry

Everything the agent is handed about HOW to look is data, reached through
`describe`, never through the prompt. Three kinds:

**Methods** (the 32 formulas + 9 price specs + book methods + scenarios,
one shape): `name`, `subject_kind` (issuer | price | book), `inputs`,
`procedure` (an expression over inputs, or a named pure function in
`analytics/`), `unit_class`, `authority` (citation + url, as formulas.py
already carries), `fails_when` (the `not_for_financials` /
`denominator_must_be_positive` fields generalised), `params_schema`.
Formula.py's fourteen fields are the starting point; the price specs gain
`authority` and `fails_when` (they have neither today); `_RISK_SENSE`
becomes a method's data.

**Readings** (new — what a figure means, for the agent's judgement, never a
threshold in a computation):

    debt_to_ebitda:
      compare_within: sector; the issuer's own prior periods
      reads: gross and net conventions differ by the cash; energy and utilities are read net
      meaningless_when: EBITDA ≤ 0; a financial issuer (see fails_when)
      typical: <range, with authority and date>   ← DECISION 1 (§6)
      authority: …

The zero-threshold rule of 2026-08-24 (`test_no_formula_carries_a_threshold`)
stands: a threshold never enters a computation. A reading enters the agent's
sentence, with its authority named, as a formula's definition does today.

**Procedures** (new — what a competent analyst does for a kind of question):

    capital_allocation (subject: issuer):
      gather   OCF, capex, buybacks, dividends, debt repayment — last 4 windows
      compute  each as a share of OCF; FCF; capex growth against revenue growth
      compare  the shares' ordering; the spread of the two growth rates; the issuer's own prior year
      close    which use dominates; whether it is accelerating; what it does to FCF; if held, the position's weight
      absent   any of the five not filed → say which; do not substitute
      authority: CFA Financial Analysis Techniques (2026); SEC C&DI 102.07 for FCF

A procedure is a registry row, not a rule: the agent may follow it or not,
and `describe(subject)` lists the procedures that apply to that subject
kind. The first batch is the thirteen angles of the conversation battery
(cut a name, bear case from filings, diligence sweep, rates scenario,
capital allocation, a name outside the book, wrong premise, revenue
concentration, news to position, trigger levels, thesis check, volatility
attribution, peer comparison), because the battery is what will measure
them. Each carries an authority the way a formula does.

## §4 What the agent is handed, and what the prompt becomes

A turn: `describe(subject)` → the agent decides what to look at and compare
→ `read_*` / `compute` → `respond`. The prompt shrinks to the contract
(every figure is a tool's; nothing invented; unavailable is said with its
reason; finish with respond) — the target is a third of today's 3,072
characters — and each tool's description to one line, because "when to use
it" is no longer the description's job. Acceptance: descriptions + schemas
on the meta face under 6,000 characters (today 31,003).

The gate does not change. The one addition beside it, carried from
V21_CONVERSATIONS §9 and the V22 discussion: a `comparison` block — two
slots and a relation (greater / smaller / faster / spread) — whose truth the
desk computes from the two resolved values, the way V19 computes a trend's
direction. It gives an analysis sentence a checkable form; it is a lookup,
not a judgement, and it is the only new thing the gate learns.

## §5 Budget

Six limiters become two: the context ceiling (80k, unchanged) and ONE
evidence budget per turn, charged **per assistant message** rather than per
call (DECISION 2, §6). With `read_*` and `compute` taking lists, a
ten-issuer question is two or three messages. The batch hold (V21 S1) keeps
its predicate. The session pool and the external-search pool stay as the
two money-shaped limits they are.

## §6 Decisions for the boss

1. **Readings may carry a typical range** (with authority and date) — or
   readings stay qualitative (compare-within, meaningless-when, conventions)
   and the agent reasons from the issuer's own history and peers only.
   Recommendation: allow, under the formula citation discipline.
2. **The evidence budget's unit**: per assistant message (recommended), or
   per subject (a ten-issuer compute costs ten).
3. **Cutover**: one cut with the battery as the net (recommended), or the
   old 44 beside the new 10 for a batch. Two catalogues in front of the
   model at once is the state V22's first live turn already showed is
   confusing.
4. **The comparison block**: in this batch or after the catalogue lands.

## §7 Phases and acceptance

Order by dependency; each phase is one commit series with its own coverage
note, as every batch has been.

| phase | builds | acceptance |
|---|---|---|
| **A. one method registry** | formulas + `_TOOL_SPECS` + book methods + `_RISK_SENSE` + scenarios in one shape; `compute` executes it; `evaluate_formula`, the seven price tools, `get_portfolio_analysis`'s derived quantities, `reconcile_move`, the two episode tools and `hypothetical_book` become methods | every figure the 13 tools produced is produced by `compute` with the same value and the same ledger type (parity, offline and live on `run_b791e7985dcd`); the registry has no entry without `authority` and `fails_when`; `test_no_formula_carries_a_threshold` extends to the whole registry |
| **B. describe(subject)** | the five-domain catalogue with three kinds of absence and the applicable methods and procedures; `not_held` derived from the concept map's coverage; `cannot` derived from registry subject kinds + withheld | one format for ticker / portfolio / run / scenario / desk; default layer ≤ 8k on every live subject; every `cannot` line is citable by an absence block (a row, not a sentence) |
| **C. ten tools** | the five reads, `start`, `search_web`; faces rebuilt; evidence declarations derived per domain; descriptions one line each; the prompt cut to the contract; budget per message | 44 → 10 on the meta face; description surface < 6,000 chars; every id prefix still has a source; the four battery drivers (`agent_battery`, `conversation_battery`, `rubric_battery`, `exit_metrics`) and the Activity panel read the new names |
| **D. readings and procedures** | 32 readings; 13 procedures; `describe` lists them per subject | every entry has an authority; no numeric threshold reaches `compute` (pinned) |
| **E. the comparison block** (if DECISION 4 says now) | schema, resolver check, rendering | a false relation between two true figures is refused by the gate; the true one renders with the desk's own computed relation beside the model's word |
| **F. measure** | the conversation battery re-run on the deployed stack | the rubric's `ranking` 3/10, `so_what` 3/15, `grounded_claims` 16/22 move; the refusal mix (32 grammar / 14 evidence) moves; substitution cases (C04#t1, C13) answer with a cited absence instead of a substituted figure |

Phase A can start without any decision in §6. B needs none. C needs
decision 2 and 3. D needs decision 1. E needs 4.

## §8 Out of scope, on purpose

- The gate's six invariants and the lexical text layer (`_NOT_A_FIGURE`,
  frozen 9/1) — untouched.
- The daily report's deterministic recipe (`services/recipe.py`) — no agent
  there, no change.
- Dimensional facts (segment, product, geography as figures) — the catalogue
  will SAY they are not held; ingesting them from each filing's XBRL instance
  is its own batch.
- The critic (V21 S5) — stays outside the gate and offline; the comparison
  block covers the part of its job that is a lookup.
- Multi-tenant, deployment, quota — untouched.

## §9 Risks, stated

- **describe's payload.** The one real engineering risk. Factoring
  (pattern × labels) carried describe_run from 18k to 7.7k; the same must
  hold across five domains, or the catalogue becomes what the 44
  descriptions are today. The 8k ceiling is a live test, not a hope.
- **Moving methods is not renaming tools.** A price spec that arrives in the
  registry without `authority` and `fails_when` is a tool with a new name;
  the registry's constructor refuses it (the "author must remember" rule:
  construction-time error).
- **One cut.** Every script that reads `agent_steps.tool_name` (six of them)
  and the Activity panel change names in the same commit as the faces; the
  battery is re-run before the rebuild, not after.
- **More freedom, more substitution** — unless B's `cannot` and `not_held`
  land before C. That ordering is the plan's one hard constraint.
