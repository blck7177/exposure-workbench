# V30 — The analysis is a program, the answer is claims (proposed 2026-09-09, not built)

Written from the 2026-09-09 architecture review (artifact "Exposure Workbench 架构复审").
Rule this plan is written under (boss, 2026-09-08): in one conversation **the LLM provides
intelligence, skill provides domain knowledge, tools are orthogonal and let the LLM execute
what it intends, validation ensures correctness and traceability.** Every item below is stated
first as which role gets its work back, then as the contract, then as code, then as the guard.

Status: **approved 2026-09-09 (boss)** — D1 expression tree, D2 all nine relations, D3 **digits allowed in prose** (G3 = every digit accounts to a node value/identity or the user's question; unsourced → refused; the resolve_number/identity lookups are KEPT, not deleted), D4 yes, D5 **brief path noted, migrated later** (submit_brief keeps the V24 grammar and gate until then; old answer/gate code stays for that path), D6 push behind a flag, both arms measured, D7 keep MCP. Execution started the same day, Phase 0 first. No commit yet. The other session's V29 commits
(`37e9787`, `431ad4c`) and its uncommitted `analytics/resources.py` are untouched.

---

## §0 The decision this plan executes

The review's finding, in the four-role frame:

| role | what it is doing today that is not its work |
|---|---|
| LLM | compiling its analysis into a sequence of JSON calls joined by ids it copies from payloads (`f_…`, `run_…:name`, `f_…@period`), one operation per round trip; median 7 round trips and 67k prompt tokens a turn, ~2 respond attempts, 111 refusal codes that teach spelling |
| tool | exposing the typed algebra one operator at a time instead of as a language; carrying budget, batch-hold, `ref:name` and `@period` syntax as patches on that protocol; minting Facts by walking payloads and guessing units from key names |
| validation | checking pointers (provenance, layout, digits in prose) and, by the 9/1 contract, not the ROLE a sentence gives a true figure — which is where every reader-visible false statement in 242 turns lived (X8, X15, X16, X18; "620.9% days"; `100.0%=1.0`) |
| skill | written as prose the model must translate into calls; 3/140 cards opened before V27, and after V27 the cards open but the translation still costs the turn |
| (instrument) | LLM-judged rubric, ±5/87 on identical code, no gold answers, no frozen book, no model comparison |

The decision: **the unit of work between the model and the desk becomes a program; the unit
of the answer becomes a claim.** The core (analytics, typed_calculator, Fact, ledger, RLS,
fail-loud) is unchanged and is what the program executes over.

What this plan does NOT decide: the model (§8 D4), whether the brief path migrates in the
same batch (§8 D5), the exact claim relation set (§8 D2).

## §1 Measured today (2026-09-09, live DB and V29 traces)

| surface | now |
|---|---|
| user messages | 1,939; 1,916 from the boss's account (battery); ~23 external, last 08-21 |
| steps per assistant message (10 d) | p50 14.5, p90 26; respond attempts 2.11; gate exhausted 30/1,079 |
| V29 per turn (140) | round trips median 7 (p90 12); prompt tokens summed median 67k (p90 157k); 9 s (p90 16 s) |
| resident context | system 484 tok; 10 schemas 3,985 tok (compute 918, respond 850); desk rules +610 per describe |
| refusal vocabulary | 111 codes in src; top six in 10 d: expand_needs_a_subject 349, unsourced_figure 268, malformed_answer 203, unverified_quote 151, not_on_ledger 136, unknown_portfolio 131 |
| gate-verified false statements | 5 in 102 turns (V26), 2 more in V29, plus `100.0%=1.0` (id and value both written) |
| instrument | same code twice: 59 vs 54 / 87; battery starts runs on the live book; scheduler moves "latest" mid-run |
| tests | 1,487 functions, 28.6k lines (= src); 53 files read source/AST; 27 dead live tests |

## §2 The target: four objects between the model and the desk

```
question ──► LLM writes { program, claims, prose }
                  │ program
                  ▼
             executor  ── each node: one calc_ledger row, one Fact ──► result table (values + identity)
                  │                                                        │
                  └────────────────── refusals per node ◄──────────────────┘
                  ▼ claims + prose
             gate: G1 every claim's value is a node of THIS program
                   G2 the claim's relation fits the node's identity (type check)
                   G3 prose carries no digits
                  ▼
             renderer: claim → sentence fragment with its chip; prose around it
```

### §2.1 The program (tool boundary, gives execution back to the tool)

**Contract.** The LLM writes one program per quantitative intent. A program is a list of
bindings; a binding is a name and an expression; an expression is a primitive applied to
names and literals. Names are the program's own; no id from any payload is ever written by
the model. The executor resolves every name once, types every value, runs every node
through the existing algebra, and returns a result table. A node that refuses yields an
Absence value; nodes depending on it refuse with the chain named. Nothing is partially
returned: the table holds every node, settled or refused.

**Shape.** A JSON expression tree, not Python — no sandbox, provider-legal schema
(object at top level, no oneOf/anyOf/not; V28-R's lesson), `strict` possible.

```json
{"let": [
  ["w",      {"fn": "column",  "of": {"fn": "run", "portfolio": "port_001", "which": "latest"}, "table": "issuer_exposures", "col": "weight"}],
  ["top5",   {"fn": "sum",     "of": {"fn": "top", "of": "$w", "n": 5, "direction": "highest"}}],
  ["w_prev", {"fn": "column",  "of": {"fn": "run", "portfolio": "port_001", "which": "prev"},   "table": "issuer_exposures", "col": "weight"}],
  ["delta",  {"fn": "sub",     "a": "$top5", "b": {"fn": "sum", "of": {"fn": "top", "of": "$w_prev", "n": 5, "direction": "highest"}}}]
 ],
 "return": ["top5", "delta"]}
```

**Primitives** (all exist as services today; the language adds only composition):

| family | primitives | executor today |
|---|---|---|
| read | `fundamentals(ticker, metric, months\|start,end\|at\|last_n)`, `prices(ticker, window)`, `run(portfolio, which=latest\|prev\|<id>)`, `column(run, table, col)`, `section(run, name)` | fundamentals_service, price_analytics, run_reads (`completed_run`), quantities |
| method | `method(name, subject, params)` — the 46 registry methods | compute_service._run_method |
| scalar ops | `add sub mul div scale` (scalar×scalar, vector×scalar broadcast) | typed_calculator.calculate / scale / _broadcast |
| set ops | `sum avg min max std rank top` over a vector or a set | typed_calculator.rank / aggregate / _fold |
| series ops | `yoy qoq cagr latest pct at(series, period)` | series_service.stat_over, series_ops |
| scenario | `sell(run, sales)`, `buy(run, buys)` | scenario_service |

A **vector** is new in name only: a run column keyed by label (`issuer_exposures.weight`
over tickers) — what `quantities` already produces, given a type. `top(v, n)` is `rank` then
a slice; it exists so "top five" is a node, not the model's choice of five ids.

**Refusals.** Exactly the algebra's own (R1–R3, units, books, floors, scenario's five) plus
two of the language: `unknown_primitive` and `type_mismatch` (an arg of the wrong kind).
Every refusal names the binding it fell on. The 111-code vocabulary collapses to the
algebra's (~25) + these two; the spelling codes (§3) go with the protocol.

**Code.** `services/program_service.py` (parse → type → evaluate; ~400 lines, all dispatch
to existing services); `tools/definitions.py`: one tool `run(program)` replacing describe /
read_fundamentals / read_prices / read_book / compute; `fact_adapters` for `run`: none — the
executor produces Facts directly from typed nodes (I1–I3 by construction, no payload walk).

**Guard.** (a) symmetric: every primitive in the schema has an executor case and a fixture;
(b) the 140 V26 questions each have an "ideal program" that executes and equals its gold
value (Phase A's deliverable, and the battery's gold); (c) the live provider accepts the
`run` schema (V28-R guard, extended).

### §2.2 The result table (tool → LLM, and tool → validation)

**A binding name is a variable, never a measure.** Today `as_quantity` lets the model mint
a row under a name that asserts a relation the operands do not stand in — V29 §6.2:
`days_at_100pct_adv` was book market value ÷ MSFT market value (6.21×, no ADV in the turn),
shipped as "620.9% days"; the review's AWS case (Q1 ÷ TTM named `aws_share`) is the same
defect. In V30 the measure of a derived node is DERIVED from its operation and operands
(`portfolio_market_value ÷ issuer_exposures.MSFT.market_value`, unit RATIO) by the
calculator's own `_derived_name`; the program's `$name` is recorded as `node`, shown to the
model as its handle, and never printed beside the figure. The renderer prints the derived
measure and unit. A "days" figure can then only exist as MONEY ÷ MONEY_PER_DAY = COUNT, which
is the algebra's answer, not the model's word. `as_quantity` is removed from the language.

Each returned node is a Fact as V24 defines it (id, kind, subject, measure, unit, value|
points|vector, as_of, window, params, sources) plus `node` (its binding name) and `deps`.
Vectors are one Fact with `entries: [[label, value], …]`. Absences are Absence Facts with
the chain. The model reads it as the `facts` block does today; the ledger records it on the
step exactly as today. What is removed: `note` (the payload with figures replaced by ids) —
there is no payload; the program's own names are the note.

### §2.3 Claims and prose (LLM → validation; gives "saying" a type)

**Contract.** The answer is `{claims: [...], prose: [...]}`. A claim states one relation
over program nodes. Prose is paragraphs of text in which `{c1}` marks where a claim is
rendered; prose carries **no digits** (I1 applied to the answer; D3 decides the one
exception). A passage quotation is a claim of relation `quote`.

```json
{"claims": [
   {"id": "c1", "relation": "level",  "of": "$top5"},
   {"id": "c2", "relation": "change", "of": "$top5", "against": "$top5_prev"},
   {"id": "c3", "relation": "rank",   "of": "$ranked", "n": 5},
   {"id": "c4", "relation": "absent", "of": "$w_prev"},
   {"id": "c5", "relation": "quote",  "passage": "$p1", "span": "accounted for 56% of total revenues"}
 ],
 "prose": ["The top five names carry {c1} of the book; against the prior run that is {c2}. …"]}
```

Relations (D2): `level`, `change`, `ratio`, `rank`, `room` (distance to a tier), `absent`,
`quote`, `series` (a chart), `table` (rows of nodes). Each relation's typing rule is in §2.4.

### §2.4 The gate (validation, unchanged in principle: deterministic, no LLM, lookups only)

| check | rule | replaces / catches |
|---|---|---|
| G1 provenance | every `$name` in claims is a node of this turn's program(s); every `quote.passage` is a passage Fact of this session | not_on_ledger; cross-run mixing |
| G2 type | `level`: node is scalar and its measure is not a tier column (`*_level`, `limit_value`, `breach_*`, `warning_*` — from `resources`) · `change`: `of` and `against` share measure, subject, unit and differ in period, or `of` is a series-op node · `ratio`: node is a `div` node or a registry method of family ratio/multiple · `rank`: node is a `rank`/`top` node · `room`: `of` is a tier column and `against` the check's current value, same check · `absent`: node is an Absence · `quote`: span verbatim in passage · `series`: node is a series · `table`: every cell a scalar node | X8 (superlative without rank), X15 (tier read as level), X16 (same point twice), X18 (window mismatch: contribution of one session vs an episode — `change`/`ratio` require the window the relation names), "$10.99M days" (unit vs relation), `100.0%=1.0` (no digits in prose) |
| G3 prose | no digit token in prose (except D3); every `{cN}` resolves to a claim; every claim is rendered at least once | unsourced_figure, unverified_quote, id_in_prose, name_in_prose, pointer_written_as_text, pointer_not_separated, most of malformed_answer |

The renderer (services/answer.rendered → unchanged output shape: runs of strings and
`{fact}` objects, so apps/web needs no change) writes each claim as its fragment: `level` →
chip; `change` → "from A (period) to B (period), +x%"; `rank` → the ordered labels; `room` →
"x points below the warning tier"; `absent` → the absence sentence; `quote` → the span with
its passage mark. Units, precision, dates all come from the Fact, never from the model.

### §2.5 Skill delivery (skill's work stays skill's; the shape becomes copyable)

- **Symbol table**: today's `name_table` + catalogue, delivered once per turn as the
  program's vocabulary (methods with params and yields, filed lines, run columns, ops),
  ~2.5k tokens; per-subject narrowing is a later optimisation.
- **Domain snippets**: each of the 14 Procedures gains `programs: tuple[str, …]` — three to
  five short programs in the language, e.g. `book_liquidity`:
  `days = div(column(run, issuer_exposures, market_value), scale(method(price.adv, names, {window_days:20}).dollars, 0.25))`.
  A snippet is knowledge in the form the model can reuse; it names no tool (the language is
  not a tool). Guard: every snippet parses, types and executes on the fixture (symmetric).
- **Push**: before the first completion of a turn, a deterministic lexical match of the
  user's message against `Procedure.triggers` selects ≤2 domains and injects their
  snippets + `desk` sentences (~300 tokens). Measured, not assumed (Phase C acceptance).
  `describe` as a navigation tool is removed; `expand_needs_a_subject` (349 in 10 d) goes with it.

### §2.6 What remains a tool

`run(program)`, `read_filings(ticker, query|item)`, `search_web`, `start`, `respond`
(claims + prose), `think`. Six on the meta face; the research face is the same less
nothing (read_book's reason to be meta-only is carried by `run`'s face-scoped primitive
set, as `_compute_for(kinds)` does today). MCP transport unchanged; budget: one `run` per
message is charged once (V23's per-message unit), and the 15-slot pool, the batch hold and
`is_pool_empty` are deleted.

## §3 Removed by construction

| removed | why it no longer has an occasion |
|---|---|
| refusal codes: op_or_method, unknown_series, unknown_operand, not_a_series, series_only, operands, params, subject_required, unknown_name, expand_needs_a_subject, unknown_expand, domain_not_for_subject, query_or_item (compute side), unsourced_figure, unverified_quote, id_in_prose, name_in_prose, pointer_written_as_text, pointer_not_separated, kind_does_not_fit, unknown_point, not_standalone (→ G2), untyped_operand (nodes are typed at birth) | no addresses, no ids in prose, no payload walk |
| `ref:name` and `f_…@period` operand syntax; `Shapes`; `agents/batch.py`; `BUDGET_FREE_CLASSES` pool logic; `_BUDGET_FREE_TOOLS` mirrors | the protocol they patched is gone |
| `fact_adapters._harvest` and per-tool adapters for describe/read_*/compute; `UNIT_BY_KEY`; `PARAM_KEYS`; `MEASURE_TABLE` | the executor is the only producer; units come from node types |
| `catalogue_service` levels, `EXPANDS`, `_domain`, `next`/`open`/`call` rendering; `name_table.route/nearest` | the symbol table is delivered, not navigated |
| `answer.tokens_in`, `TOKEN`, `POINTER`, `WRAPPED`, `GLUED`, `ledger.resolve_number/resolve_identity/resolve_in_passages`, money-scale matching | prose has no digits to resolve |
| guards that pin the above (est. 300–400 tests) | the seams they pinned are gone |

Kept: everything under `analytics/`, `typed_calculator`, `series_service.stat_over`,
`formula_service`, `price_analytics_service`, `scenario_service`, `run_reads_service.completed_run`,
`facts.py`, `ledger.py` (by_id only), `registry.invoke` (validate → charge → run → record),
`tool_session`, RLS, quota, `withheld`.

## §4 Role boundaries after V30

| role | owns | may not |
|---|---|---|
| LLM | which domain, which subjects, which comparison; the program; the claims; the argument in prose | write an id, a number, a unit, a date it did not get from a node; name a tool inside the program |
| skill | symbol table; domain snippets; desk rules; readings; trigger words | execute anything; name a tool |
| tool | `run`: parse/type/execute, every node a ledger row, every result a Fact; `read_filings`/`search_web`/`start`; `respond` | judge domain (what is comparable is the algebra's, via `_comparison_axis`); guess a unit |
| service | the executors behind the primitives (unchanged) | be visible to the model |
| validation | G1/G2/G3; the algebra's refusals; the program text as the replayable record | read the model's words for meaning |
| user report | renderer: claim → fragment with identity; chips; drawer | invent a label, a precision or a date |

## §5 Phases

**Phase 0 — the instrument (before any product code).**
1. A frozen fixture database (`infra/fixtures/battery_2026-09.sql.gz`): restored before every
   battery; `start` denied on the battery face; the scheduler paused for the run.
2. Gold values for every quantitative turn of V21/V24/V26: computed by the desk's own
   services on the fixture, stored beside the question (`tests/battery/gold_v26.json`).
   A turn passes `figures_correct` when every rendered figure equals a gold figure within
   half a ulp of the written precision — the V3 criterion, now deterministic.
3. The LLM judge kept for `so_what`, `follows_on`, `honest_absence` only; ≥3 replicates;
   report distributions and per-criterion intervals, never one number.
4. Two mechanical counters split from quality: **spelling refusals** (any refusal about
   how a call was written) and **algebra refusals** (R1–R3, units, floors).
5. One run of the current code with a stronger model on the same fixture (D4).
Acceptance: two replicates of identical code agree on `figures_correct` exactly and on
judged criteria within the reported interval; the model-comparison row exists.

**Phase A — the language and the executor (offline).**
`program_service` over existing services; the 140 ideal programs written and executed
(this is also the gold's derivation for those turns); every primitive with a fixture;
provider-acceptance live test for the `run` schema. Nothing on the model path yet.
Acceptance: 140/140 ideal programs execute; each equals gold; symmetric primitive test green.

**Phase B — the cutover commit.** `run` on the meta face; `respond` takes claims + prose;
gate G1–G3; renderer from claims; old tools, adapters, answer grammar removed in the same
commit (DP3: no half-switch). Three live rounds on four questions, as V24 did.
Acceptance: the five X-cases, constructed by hand as claims, are refused by G2 with the
named rule; zero digits in accepted prose; apps/web renders with no change; battery
mechanical: round trips median ≤3, respond attempts ≤1.3, `=raw`/`[10-K Item N]`-as-figure
artifacts = 0.

**Phase C — skill as snippets, pushed.** `Procedure.programs`; symbol table delivery;
trigger push. Acceptance: every snippet executes on the fixture; push precision/recall on
the 140 questions measured and reported; domain-evidence recall (X21's 22%) re-measured.

**Phase D — deletion.** §3's list; refusal codes ≤ 30; dead live tests removed; test count
reported before/after.

**Phase E — replay and wording.** V21/V24/V26 on the fixture, two replicates, distributions;
model-facing wording (run description, claim relation descriptions, refusal texts) to the
boss before commit (the standing discipline).

## §6 What is measured, before and after

| metric | today | target after B | after C |
|---|---|---|---|
| round trips / turn (median) | 7 | ≤3 | ≤3 |
| prompt tokens / turn (median) | 67k | ≤25k | ≤25k |
| respond attempts / turn | 2.0 | ≤1.3 | ≤1.2 |
| spelling refusals / turn | 0.54 | 0 (class removed) | 0 |
| gate-verified false statements (X-class) / 100 turns | 5 | 0 for the four typed relations | 0 |
| `figures_correct` (deterministic) | not measured | reported | reported |
| domain evidence recall | 22% | — | measured |
| refusal codes in src | 111 | ~30 | ~30 |

## §7 Guards (few, structural)

1. Language ⇄ executor symmetry (every primitive has a case and a fixture; no case without a primitive).
2. Every ideal program and every domain snippet executes on the fixture.
3. The live provider accepts every schema on both faces (V28-R, kept).
4. Accepted prose contains no digit token (a property test over the stored corpus).
5. The five X-cases as claim fixtures, refused with their G2 rule name.
6. Fixture restore before battery; battery face has no `start`.

## §8 Decisions for the boss

- **D1 carrier of the program**: JSON expression tree (recommended: provider-legal, strict-able, no sandbox) vs a restricted Python subset (more expressive, needs a sandbox and a parser). 46 methods + ~20 ops compose fine as a tree.
- **D2 claim relations**: the nine in §2.3, or a smaller first set (level, change, ratio, rank, room, absent, quote). Recommended: all nine; `series` and `table` are the two layouts V24 already has.
- **D3 digits in prose**: forbid entirely, or allow the user's own figures (`100bp`) verbatim. Recommended: allow, as a `from_question` claim, so the renderer marks it.
- **D4 model comparison**: run once in Phase 0 with a stronger model on the same fixture (cost: one battery). Recommended yes — without it "architecture gap" and "model gap" stay confounded.
- **D5 brief path**: migrate `submit_brief` to claims in Phase B (same gate) or hold. Recommended same batch: one grammar, one gate is the standing rule.
- **D6 push**: build the trigger push in Phase C or measure pull first (V27's card-opening rate is now 127/140, so pull works; the question is whether push improves recall). Recommended: build behind a flag and measure both arms in the same battery.
- **D7 MCP**: keep the resident face (one `run` tool over MCP) or fold to in-process. Recommended keep; nothing in this plan depends on transport.

## §9 Risks

- A rewrite of the model-facing layer (~5k lines): V23's 44→10 was the same size and closed in a day, but this touches the answer grammar; the renderer's output shape is preserved deliberately so apps/web is untouched.
- Programmatic calling helped 11 of 14 models in the cited study, not all; the mini model's benefit is Phase 0's measurement, not an assumption.
- G2 will refuse some answers that pass today (false rejects, as VeriFin reports); intended — visible failure over invisible error.
- Expression trees are verbose for the model; if Phase B shows the model mis-nesting, D1 is revisited with a restricted Python subset.

## §10 Out of scope

New measures (valuation multiples, peers, benchmark constituents), VaR/stress release, ingest cover (`total_debt` on 4 of 9), the daily report gate, production ops (Clerk prod instance, spend cap, rate limit).
