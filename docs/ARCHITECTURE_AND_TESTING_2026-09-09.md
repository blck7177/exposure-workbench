# V30 — architecture findings and the measurement behind them

2026-09-09. Written after the V30 program language and claims gate were built and measured against a
baseline pinned at `e6c290b`. Every number here was produced today and is reproducible from the files
named beside it. Framed the way this desk frames every analysis: first **who did work that was not
theirs** (the four roles), then **where it sits** (the seven layers).

Deployed code is `e6c290b`. Everything V30 in this commit is on the branch and NOT on the live site.

---

## 0. The result in one paragraph

Replacing per-call addressing with one program per question, and pointer-checking with typed claims,
buys a third fewer tool calls, two thirds fewer wrong-address refusals, no unit-algebra refusals at all,
and half the double-figure artifacts a reader can see. It does not change correctness. The cost lands on
the answer gate: more attempts per answer, twice as many turns that run out of them. Three defects the
measurement surfaced are in the code that is live right now, and are described in §4.

---

## 1. Four roles: who did work that was not theirs

**tool — three boundaries crossed, and they are the expensive ones.**

1. **The catalogue answers a question it does not hold the data for.** `describe('NVDA')` lists
   `revenue` among the issuer's metrics and states one `latest_period_end` for the issuer. It carries no
   per-metric coverage at all: the string `2022-01-30` does not occur anywhere in its 22.5 KB of output,
   although that is where NVDA's `revenue` line stops. `list_available_metrics` has the per-metric period
   count and last period; the catalogue flattens it to a list of names. The model is handed a map that is
   wrong by omission, and every step it takes afterwards is a correct step from a false premise.
2. **The adapter decides what a number is, by its key name.** `UnknownUnit: compute: no unit declared
   for numeric key 'unmatched_periods' (subject XOM)`. The producer — `typed_calculator` — knows that
   value is a count of periods that did not align. The adapter has to find the name in `UNIT_BY_KEY`, and
   when it is not there the whole tool call is thrown away, including the figures that did compute. This
   is the tool doing the service's job, and it fails closed on the entire call rather than on the one key.
3. **`get_flow` answers a question it cannot answer honestly.** "The latest twelve months" still has an
   answer on a line that stopped reporting four years ago, so it returned one.

**validation — one boundary crossed, introduced and narrowed the same day.** The claims gate, asked
whether a refusal can back a statement of absence, classified refusal codes itself and put "the desk did
not understand the address" (a guessed `port_1`) in the same class as "the desk understood and does not
hold it" (`unknown_name`: this run has no `quantity` column, and here is what it does have). That is
validation judging what a tool's refusal meant. It cost five honest statements in 36 turns before it was
narrowed to addresses, argument shapes and type errors.

**agent/LLM — one boundary crossed.** The model reported its own program's type errors to the reader as
absences of data. Fourteen of the 23 absence claims the gate still refuses in C3 are `type_mismatch`.
The gate holds, so no reader saw them; the work to do is on the tool side, making the type error harder
to write.

**skill — no boundary crossed, one omission.** The earnings-quality domain offered only `last_n` history
programs, so a question about the present was answered from an annual series. Fixed by opening both
snippets with the trailing-twelve-month readings before the history.

---

## 2. Seven layers

| layer | position | cause | fix | effect |
|---|---|---|---|---|
| agent / LLM | absence claims over refused program nodes | a refused node reads like a missing figure | none in code; the gate refuses and names the relation that fits | 23 refusals in C3, none reached a reader |
| MCP | — | unchanged in V30 (kept, decision D7) | — | — |
| tool | `describe` flattens per-metric coverage | the issuer view was built as a name list with one issuer date | per-metric coverage on the catalogue, or the ingest unification in D12 | **not yet fixed; live** (§4.1) |
| tool | `fact_adapters.UNIT_BY_KEY` | the unit is looked up by key name, not read from the producer | the V30 executor births Facts from typed nodes and has no name table; `compute` is off the meta face | class removed on the V30 meta face; **live on `compute`** (§4.2) |
| tool | `run(program)` replaces per-call addressing | one question was many addressed calls, each a chance to mis-address | the expression tree (D1) | tool calls p50 6 → 4; wrong-address refusals 1.21/1.31 → 0.45 per turn |
| service | `get_flow` on a superseded line | the line that stopped is still derivable | refuse `line_superseded`, name the continuing line; a dated read still works | **fixed on the branch, not live** |
| service | `evaluate_formula_series` grid | anchored on the first candidate with any facts | anchor on the candidate reaching the latest period | days-measure series now run to 2026 instead of 2022 |
| service | `calc_service.window_return` | recorded no basis, so the typed resolver could not date it | record `basis.interval` | eleven undated holding returns in one C3 turn, now dated |
| skill | `Procedure.programs` | history without the present reading | TTM readings first, then history | model-facing, in `V30_WORDING_REVIEW.md` |
| validation | claims gate: relations are typed | the old gate checked that a pointer existed, not what the sentence claimed of it | nine relations, each with its own refusal that names the relation that fits | algebra refusals 0.04/0.08 → 0; double-figure artifacts 12/11 → 5 |
| validation | absence provenance | see §1 | narrowed to address, argument and type errors; a factless absence goes in prose | 5 honest statements recovered, measured by replay, not yet by a round |
| user report | one-point series rendered as its label | the summary needed two points | render the single point | "accounts receivable rose accounts receivable yoy" no longer possible |

---

## 3. The measurement

**Design.** Baseline served from a worktree pinned at `e6c290b`, so the face under measurement is not
the working tree. Fixture databases frozen (`exposure_battery`, `exposure_gold`). One model throughout,
`gpt-5.4-mini`. Rounds: R1–R3 baseline replicates, B1/C1/C2/C3 the V30 arms.

**The powered comparison — V26, 140 turns, 707 must-figures.** This is the only set that can separate
the arms; V24 has 23 must-figures and V21 has 21.

| | baseline R2 | baseline R3 | V30 C3 |
|---|---|---|---|
| tool calls p50 | 6 | 6 | **4** |
| round trips p50 | 8 | 8 | **6** |
| prompt tokens p50 | 67.6k | 68.0k | 66.5k |
| prompt tokens mean | 86.4k | 86.5k | 91.9k |
| wrong-address refusals / turn | 1.21 | 1.31 | **0.45** |
| unit-algebra refusals / turn | 0.04 | 0.08 | **0** |
| double-figure artifacts | 12 | 11 | **5** |
| must-figure recall | 29.6% | 22.8% | 31.0% |
| respond attempts / turn | 2.07 | 2.08 | **2.70** |
| turns that exhausted the gate | 3 | 3 | **6** |

**What can be claimed.** The addressing results: their replicate noise is near zero, so a change of this
size is real. V30 costs a third fewer calls and two thirds fewer call errors, and removes unit-algebra
errors entirely.

**What cannot.** Correctness. Paired at the turn level, C3 against the better baseline is 26 turns better,
26 worse, 57 tied — while two runs of the SAME baseline code disagree on 45 turns. It is a dead heat.

**Where the cost went.** The gate. Respond attempts rise and gate-exhausted turns double; all three extra
exhausted turns end on the absence rule described in §1. Mean prompt tokens per turn are 6% HIGHER on
V30 even though the median is lower, because the retries have a long tail (p90 170.9k against 167.1k).
V30 saves calls, not tokens.

**Two instrument findings, which matter more than any single round.**

1. `figures_present` is all-or-nothing and saturates. On V24 the same baseline code scored 43.5% and
   60.9% on two replicates, so nothing measured on V24 or V21 can discriminate. An earlier conclusion
   that "figures_present fell in C2" was withdrawn as noise. `scripts/v30_figure_recall.py` reports the
   graded share instead.
2. **The effective sample is the turn, not the figure.** Must-figures inside one turn come from one
   computed chain and are not independent. Split by question family, the liquidity family looked 20
   points better under V30 — until the baseline was split into its own replicates and read 48.1% against
   12.3%. More gold per turn does not buy power; more replicates do.

**Cost of the measurement itself.** 74.5M prompt tokens against 1.14M completion — 65 to 1. Two thirds
of it was running one 140-turn set four times; 17% was a round discarded for predating the pinned
worktree. Nothing in the client records `cached_tokens`, so whether prompt caching is being hit is
unknown and unmeasured.

---

## 4. What is live right now

Production runs `e6c290b`. The V30 branch is not deployed. These three are in the deployed code and were
verified today against the production database with the deployed source.

**4.1 A stale line reported as the present.** Verified reading the production database with `e6c290b`:

    NVDA   revenue        -> 26.9bn through 2022-01-30
           total_revenues -> 303.0bn through 2026-07-26
    GOOGL  revenue        -> 359.7bn through 2025-03-31
           total_revenues -> 445.9bn through 2026-06-30
    AAPL   revenue        -> 451.4bn through 2026-03-28   (unaffected)

A user asking for NVDA's revenue, its growth, or any series built on it can be shown a figure eleven
times too small and four and a half years old, with no warning. The scalar formula path is NOT affected:
`evaluate_formula` already substitutes the continuing line and says so in its definition string, verified
on both trees. The exposure is the direct read and the series grid. Fixed on this branch, not deployed.

**4.2 A whole tool call lost to one unlisted key.** `compute` raises `UnknownUnit` on
`unmatched_periods` and the wrapper returns `fact_adapter_error`, discarding every figure in that
result. Three occurrences in 191 baseline turns today. Not fixed anywhere: `unmatched_periods` is
produced by `typed_calculator` and is in no adapter table. On the V30 meta face the class cannot occur,
because the executor births Facts from typed nodes, but `compute` is still on the research face.

**4.3 The V29 gate contract.** The reader-visible role errors recorded in `docs/spikes/v29/FINDINGS.md`
are unchanged in the deployed gate, which checks where a figure came from and not what the sentence
claims of it. V30's claims gate is the answer and is not deployed.

---

## 5. Open, and whose call it is

- **Model-facing wording** — `docs/spikes/v30/V30_WORDING_REVIEW.md` is committed unread. It is every
  sentence V30 added or changed that a model sees.
- **D12** — unify `revenue` and `total_revenues` at ingest, so the desk has one top line per issuer with
  the reported tag recorded per period. Recommended; it removes §4.1 at the root rather than refusing.
- **D13** — whether `describe(expand=<domain>)` with no subject should return the domain's knowledge
  with placeholders instead of refusing. It cost 23 extra calls in C3's first 40 turns, and it reverses
  part of the V27 decision.
- **D8–D11**, and the V29 gate contract, unchanged.
- **Next round.** C4 on v26 first: it is the only powered set, and it measures the four fixes made after
  C3's face loaded. Blocked on API credit, twice exhausted today.
