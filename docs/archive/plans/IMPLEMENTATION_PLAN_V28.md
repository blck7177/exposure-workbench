# V28 — Giving the work back to its role (2026-09-08: built the same day, MODULE_NOTES M28; local, uncommitted)

The rule this plan is written under (boss, 2026-09-08): in one conversation **the LLM provides
intelligence, skill provides domain knowledge, tools are orthogonal and let the LLM execute what
it intends, validation ensures correctness and traceability.** Every fix below is stated first as
*which role gets its work back*, then as the contract that makes the boundary hold, then as code,
then as the guard that keeps it held. Analysis: `docs/spikes/v26/ROOT_CAUSES.md` (classes 1 and 2);
the seven remaining items are all failures of one boundary of the tool — with the LLM, with skill,
with validation — plus one boundary between validation and the LLM.

Out of scope, deliberately: class 3 (a sentence giving a true figure the wrong role — a decision
about validation's own boundary, not a fix); data cover (`total_debt` on 4 of 9 issuers — ingest,
no role misbehaves); the battery harness (a measurement condition, listed under Verification).

---

## A. The tool's boundary with the LLM — the LLM expresses intent, never implementation

### A1. Series statistics over any series the LLM holds (`unknown_series`, 41 in 244 turns)

**Give the work back to the tool.** `compute` promised one verb over any figure; underneath, a
series statistic is a V10 service that takes a *ledger id* and re-loads it, so a series the
resolver already produced from a fact id is refused as unknown. The LLM's intent was right; the
tool did not execute it.

**Contract.** An operand the LLM writes is resolved once, at the boundary, into a typed value;
every op operates on the resolved value; no op re-loads by id.

**Code.** `series_service`: split `series_stat` into `load_series` (kept, for direct callers) and
`stat_over(db, points, rtype, source_id, op, invoked_by)` — the body after loading, unchanged.
`compute_service._stat`: pass the `TypedSeries` (`points`, `unit_class`, `quantity`, `source_id`)
to `stat_over`; the ledger row's provenance is the resolved `source_id`, as today.

**Guard.** A test computes `max`/`yoy` over a series *fact id* (fixture) and gets a row; a source
guard pins that `compute_service` hands `series_service` a resolved value, never `operands[…]`.

**Effect.** LLM: the earnings-quality and price-context routes open (both run on "a measure over
its history"). Validation: unchanged — the stat row rests on the same source id. Kills W5/P3/P9.

### A2. Two shapes the LLM cannot mix (`op_or_method`, 15 refusals in 14 turns; `query_or_item`)

**Give the work back to the tool.** `op` and `method` are two implementations of "compute this";
the tool made the LLM remember that they may not co-occur, and charged a budget slot to say so
(the registry validates the schema, reserves budget, *then* runs the fn where the rule lives).

**Contract.** A tool's signature states its shapes; an invalid combination is unwritable, and what
the schema can decide is decided before any spend. Composition is not a shape: results are facts,
so "a method over a list, then a statistic" is two calls (compute's description now says so).

**Code.** `definitions.py`: compute's schema gains `oneOf` — `{required: [op, operands]}` |
`{required: [method, subject]}` — with `not: {required: [op, method]}`; read_filings the same for
`query` | `item`. `arg_validation._unpack`: when both branches fail because both keys are present,
the problem names the two shapes. The service-level refusals stay as backstops for direct callers.

**Guard.** `validate_args` refuses `{op, method}` and `{query, item}` before spend (test); the
schema-honesty suite already walks every branch.

**Effect.** LLM: the 15 slots are not spent; whether it then makes the two calls is the battery's
question (price.beta 0/5 today). Validation: unchanged.

---

## B. The tool's boundary with skill — the tool enforces mechanics, skill holds judgement

### B1. What is comparable is the unit algebra's, and a row is named by what varies (P12)

**Give the work back to skill and the unit algebra.** `rank` (and the set statistics) refuse
operands whose *measure name* differs (`incomparable_quantities`), because the op names its rows
by subject and assumed subject is the only axis. "Whether capex, buybacks and dividends may be
ordered" is domain judgement — skill says yes, over the same window — and the tool overruled it
with a rule that was really a labelling convenience.

**Contract.** The tool admits an ordering or a set statistic over typed scalars of one unit class
and one window basis; it refuses mixed units, mixed windows, duplicates and rows nothing tells
apart. The row's labels come from whichever identity field varies — subject, measure, or period —
which the V24 identity already carries.

**Code.** `typed_calculator.rank` and `_fold`: replace the `quantities_seen` refusal with a
window-basis check (instant/interval equal within the snap tolerance); `_label_of` picks the
varying axis; the ranking row's `quantity` is `as_quantity` or `rank.<axis>` when measures differ.
`incomparable_quantities` remains only for mixed windows, renamed to say so.

**Guard.** `rank(capex, buybacks, dividends_paid of MSFT, same window)` orders with measure labels;
`rank(capex MSFT vs AAPL)` unchanged; a mixed-window rank is refused. Skill's
`issuer_capital_allocation.compare` stays as written.

**Effect.** Skill and tool agree; the LLM can execute the compare skill told it to. Validation:
the row is a ledger row as before.

---

## C. The tool's boundary with validation — the tool births whole facts, validation checks pointers

### C1. A run is read through one door, and an in-flight run is task state (X1/X2)

**Give the work back to the tool.** A read tool's output is a complete fact or a refusal. A run
that is still running produced zeros that the adapter minted and the gate (correctly) verified:
nothing owned "settled". Twelve places load a run by id; three check its status — and the twelfth
was added on 2026-09-07 with the directory change, without the check.

**Contract.** Every reader of a run gets it from one loader that returns the run or a refusal
naming its status and the task door; an in-flight run is not readable as figures anywhere.

**Code.** `run_reads_service.completed_run(db, run_id)` → `ExposureRun` | `run_not_completed
{status, read: "read_book('task_…')"}` | `unknown_run`. Callers: `catalogue._run`, `catalogue._domain`,
`run_reads_service` reads, `typed_calculator` (`run_…:name` operands, lines 310/325),
`scenario_service`, `integration_service`, `evidence_resolver_service`. Writers and the task
reporter (`exposure_run_service`, `job_status_service`) are the allowlist. `start`'s description
says a started run is readable when completed.

**Guard.** An AST test: no `select(ExposureRun).where(ExposureRun.id ==` outside the loader and
the allowlist (same shape as the agents-may-not-call-invoke guard). The X1 reproduction: read_book
on a running run returns the refusal and mints no facts.

**Effect.** LLM: told to wait and where to look. User report: never an in-flight zero. Validation:
unchanged.

### C2. The catalogue says which of its numbers are facts (X3/X4, `expand='filings'` dead)

**Give the work back to the tool's output contract.** `describe` is the knowledge door — its
output is a map — but every tool output goes through "each number is a fact", so a section count
(`Item 1A: 3`) met the adapter's "a figure needs a unit" and the route died. Neither side was
wrong; the boundary between map and fact inside one payload was never drawn.

**Contract.** A catalogue payload declares its figure fields and their units, as run payloads
already do (`units`); the adapter mints facts from declared figures only and treats the rest as
map. Structural counts are map unless declared.

**Code.** `catalogue_service`: each level's payload carries `units` for the counts it means as
facts (positions, alerts, filings counts, price sessions); `_filings(full)`'s `items_detail`
undeclared → map. `fact_adapters.describe`: read the payload's `units` before `UNIT_BY_KEY`, mint
nothing undeclared, never raise on an undeclared leaf of a catalogue payload.

**Guard.** Fixtures derived from `EXPANDS` × subject kinds — a new expand value without a fixture
fails the suite; the X3 fixture (`describe_issuer_expand_filings`) green.

**Effect.** LLM: the filings discovery route back (the domain scoring 67%). Validation: unchanged.

---

## D. Validation's boundary with the LLM — one statement of what is correct

### D1. The prose-number rule is validation's sentence, given to the LLM verbatim (X10/Y2, 59 marks)

**Give the work back to validation.** The gate links a prose number that a cited passage states;
`_SYSTEM` tells the LLM it may never write a number. The LLM held a second, stricter rule and,
having no id for a figure that lives only in prose, wrote the passage's id where the number goes.

**Contract.** What the LLM is told about figures in prose is the gate's own statement, imported,
not paraphrased.

**Code.** `gate.PROSE_RULE` (one constant); `_SYSTEM` and `respond`'s description and the MCP
instructions interpolate it; the `unsourced_figure` refusal's `_FIX` is derived from it.

**Guard.** A symmetric test: `_SYSTEM` contains `gate.PROSE_RULE` verbatim.

**Effect.** LLM: writes the filing's figure and cites the passage; user report: a number with a
passage link instead of `[10-K Item 7]`. Validation: unchanged. Wording to the boss before commit.

---

## Order, and what each step unblocks

| step | item | turns it touched in V26 | why here |
|---|---|---|---|
| 1 | C1 one loader | X1 critical; every future reader | safety first; the class recurred yesterday |
| 2 | A1 series over values | 41 refusals, 12+ turns | largest mechanical loss; earnings quality 0/8 |
| 3 | A2 shapes in the schema | 15 refusals, 14 turns | pre-spend refusal; then measure two-call composition |
| 4 | C2 map vs facts | 11 refusals, 7 turns | a dead route |
| 5 | B1 comparability | P12 | skill/tool agreement |
| 6 | D1 one rule text | 59 marks, 15 turns | wording review needed |

Then: rebuild the four images, and re-run the battery under the instrument conditions
(serial; a fresh completed run seeded before the first turn; two replicates; distributions, not a
single score). The directory change (M27) is measured in the same run.

## What this plan does not touch

Class 3 (role errors, superlatives without `rank`) — validation's own boundary, the boss's
decision. Data cover — ingest. The `_LINKS` domain→method choices and every model-facing sentence
above — wording review before commit.
