# V31 — What the desk knows is data in one place, and the research face runs programs (proposed 2026-09-09, not built)

Written from the two live defects `docs/ARCHITECTURE_AND_TESTING_2026-09-09.md` §4 verified against
the production database with the deployed source. Rule this plan is written under (boss, 2026-09-08):
**the LLM provides intelligence, skill provides domain knowledge, tools are orthogonal and let the LLM
execute what it intends, validation ensures correctness and traceability.** Every item is stated first
as which role gets its work back, then as the contract, then as code, then as the guard.

Status: **proposed**. Nothing here is built. V30 (`8bee083`..`b78e15e`) is on the branch and not
deployed; production is `e6c290b`. Decisions for the boss are in §8.

---

## §0 The decision this plan executes

Both defects have one shape: **something the desk knew was not in the place that needed it.**

| | the desk knew | where it was | who needed it and did not have it |
|---|---|---|---|
| stale line as the present | NVDA's `revenue` and `total_revenues` are one line under two tags: the retired tag stops 2022-01-30, the overlap year agrees to the dollar (26,914 = 26,914) | `formulas.Formula.alternatives`, readable only by `evaluate_formula` | the catalogue (drew a map with no per-metric coverage), `get_flow` (settled "the latest twelve months" on the retired line), the series grid (anchored on it) |
| one key kills a call | `quality_flags` is diagnostics, not figures | `typed_calculator` line 293, which excludes it from figures on the resolver side | the adapter, which walks every number and raises `UnknownUnit` on the first key it cannot name — discarding the whole result |

The decision: **(1) supersession between metric lines is a table derived from evidence at ingest, read
by every consumer through one function, and the catalogue states per-metric coverage wherever it
differs from the issuer's; (2) the research face stops walking payloads — it runs programs and files
its brief as claims, and the payload-walking adapters, `compute`, and the batch dispatch are deleted.**
The second is V30's Phase D and D5, which were deferred until the brief moved; this plan moves it.

The four roles, restated for this plan:

| role | gets back |
|---|---|
| LLM | asks for `revenue` and gets the top line, with the tag it came from on the page; never learns two names for one quantity, never loses a computed result to a key it did not write |
| skill | nothing changes; a domain program that reads `revenue` keeps reading `revenue` |
| tool | the catalogue tells the truth per metric; the research face has one way to compute (`run`) and no adapter that guesses what a number is |
| validation | the brief goes through the same claims gate as the chat answer — one grammar, one gate (the standing rule V30 §8 D5 deferred) |

---

## §1 Measured (2026-09-09)

| surface | now |
|---|---|
| `get_flow('NVDA','revenue', months=12)` on production, deployed source | 26.9bn through 2022-01-30; `total_revenues` 303.0bn through 2026-07-26 |
| same, GOOGL | 359.7bn through 2025-03-31 against 445.9bn through 2026-06-30 |
| `describe('NVDA')` | 22.5 KB; per-metric coverage nowhere; `2022-01-30` does not occur |
| `evaluate_formula('GOOGL','net_margin')` | correct on both trees — substitutes and says so (`substituted_inputs`) |
| `compute` → `UnknownUnit: 'unmatched_periods'` | 3 of 191 baseline turns; the whole result discarded each time |
| where `unmatched_periods` is written | `typed_calculator` series ops, under `quality_flags` |
| adapter tables that name keys | `UNIT_BY_KEY`, `POLYMORPHIC_KEYS`, `PASSTHROUGH_KEYS`, `PARAM_KEYS`, `DROP_KEYS` — `quality_flags` in none |
| `fact_adapters.py` / `registry.py` / `definitions.py` | 754 / 319 / 605 lines |
| refusal codes in src | 121 (V30 §6 target ≤ 30) |
| research face | describe, read_fundamentals, read_filings, read_prices, compute, think, run, search_web, submit_brief; the prompt tells the model "compute takes lists of methods" |
| brief | six sections of V24 blocks (`IssuerBrief.blocks`), gated by the V24 pointer gate; read back by `read_book(tk, names=['brief'])` as prose |
| brief battery | none exists |

---

## §2 The objects

### 2.1 `metric_lineage` — supersession as evidence

One row per (issuer, retired line, continuing line). Derived, never authored.

```
metric_lineage
  company_id            text  FK companies
  from_metric           text        -- the line that stopped        e.g. revenue
  to_metric             text        -- the line that continues      e.g. total_revenues
  from_last_period_end  date        -- 2022-01-30
  switched_at           date        -- first period_end of to_metric after from_last_period_end
  overlap_periods       int         -- periods (start,end) reported under BOTH tags
  overlap_max_rel_diff  numeric     -- max |from − to| / |to| over the overlap
  agrees                bool        -- overlap_periods ≥ 1 and overlap_max_rel_diff ≤ LINEAGE_TOL
  mapping_version       text        -- concept_mapping.MAPPING_VERSION the row was derived under
  derived_at            timestamptz
  primary key (company_id, from_metric, to_metric)
```

**The rule that writes a row** (`services/lineage_service.derive(db, company_id)`): for each candidate
pair `(A, B)` in `concept_mapping.SUPERSESSION_CANDIDATES` — the one home for "these two names can be
one line", moved out of `Formula.alternatives` — take the undimensioned facts of each; if B's last
period is not later than A's, no row; else compute the overlap and write the row. `agrees` is a
computed column of the evidence, not an opinion. **Three cases, and only one of them is lineage:**

| case | data | what the desk says |
|---|---|---|
| only B exists (JPM: `total_revenues` 12 periods, no `revenue`) | no A | not lineage; a formula that needs `revenue` substitutes B and writes it on the page, as today |
| A stopped, B continues, overlap agrees (NVDA, GOOGL) | row with `agrees = true` | **lineage**: a latest-anchored read of A follows B and says so |
| A stopped, B continues, overlap disagrees or is empty | row with `agrees = false` / `overlap_periods = 0` | not followed: refuse `line_superseded`, name B (today's branch behaviour) |
| both continue and differ (XOM: 5.2% apart) | B not later than A | no row; two quantities, as `concept_mapping` says |

`LINEAGE_TOL` is §8 L1. Derivation runs at the end of `ingest_financial_facts` for that issuer (the
readiness workflow already commits after every step) and once over the corpus by
`scripts/derive_lineage.py --apply`, the `remap_concepts.py` shape: the rule lives in
`lineage_service` and nowhere else, and the script only calls it.

### 2.2 One reader: `lineage_service.continuation(db, ticker, metric) -> Lineage | None`

Every consumer that today asks "is there another name for this" asks this instead:

| consumer | today | after |
|---|---|---|
| `fundamentals_service.get_flow` (latest-anchored: `months` without start/end, or `last_n`) | settles on the retired line (deployed) / refuses `line_superseded` (branch) | `agrees` → reads B's window; the result and the calc row carry `line: total_revenues, requested: revenue, via: lineage(switched_at)`; the Fact's measure IS `total_revenues`. Not `agrees` → refuse and name. Dated `start`/`end` → reads A as filed, always |
| `fundamentals_service._flow_series` | same | the series is B's; same `via` |
| `formula_service._anchor_window`, `_operand`, series grid | try each `Formula.alternatives` name in turn | lineage first; `Formula.alternatives` second and counted (§6) |
| `absence_service.superseded_by`, `_metric_absence` | reads `Formula.alternatives` | reads `SUPERSESSION_CANDIDATES`; the absence statement names the continuation and whether it agrees |
| `program_service._p_fundamentals`, `read_fundamentals` | call `get_flow` | unchanged code, inherit |

**Why following an agreeing lineage is not a fallback.** A fallback is "A is missing, quietly give B".
This is "the desk recorded, from the filings themselves, that A and B are one line; asked for A on a
window A never covered, it reads B and writes on the page which tag the figure came from". The
substitution is on the page (`substituted_inputs` set the precedent in V11), and the quantity is never
renamed: the Fact says `total_revenues`.

### 2.3 The catalogue states coverage where it differs

`catalogue_service._fundamentals` keeps `names` and the issuer's `latest_period_end`, and adds
`lines`: one entry per metric whose last period is earlier than the issuer's —

```
"lines": {
  "revenue": {"ends": "2022-01-30", "continues_as": "total_revenues", "since": "2023-01-29", "agrees": true},
  "depreciation_amortization": {"ends": "2023-09-30"}
}
```

Every name on the map then carries a true coverage statement by construction: the issuer date is the
default, and every exception is listed. No entry for a metric that reaches the issuer's latest period,
so the payload grows only where there is something to say. Model-facing wording (the key names and the
`how_to_read` sentence that explains them) goes to the boss with §7 Phase E.

### 2.4 The research face runs programs and files claims

**Face.** `describe, run, read_filings, search_web, think, submit_brief`. Removed: `read_fundamentals`,
`read_prices`, `compute`. `run` is already bound to issuer kinds on this face (V30 Phase B); every
issuer measure, price statistic, series and arithmetic the prompt sends to `compute` today is a
program (`docs/PROGRAM_LANGUAGE.md`; the 23 domain snippets already execute on the fixture).

**Brief.** `submit_brief` takes the six sections, each `{claims, prose}` in exactly `claims.ANSWER_SCHEMA`
— the grammar `respond` takes. One gate: `claims.check` per section; a refusal names the section and the
claim, as today's names the section and the block. The renderer (`claims.accepted`) produces the V24
block shape, stored in `IssuerBrief.blocks` as now, so the web brief page and `read_book(tk,
names=['brief'])` are untouched; the claims are stored beside it (§8 B1) so a brief's figures are
traceable to nodes, not only to ids.

**Prompt.** `research_session._SYSTEM` rewritten for programs and claims — the same shape as
`meta_agent._SYSTEM`, issuer-scoped. Model-facing; to the boss before commit.

### 2.5 What is removed by construction

| removed | why it can go |
|---|---|
| `fact_adapters.harvest / _harvest / _unit_for` and the five key tables | no tool on either face returns a payload that has to be walked for figures: `run` births Facts from typed nodes; `describe` births absences from two named blocks; `read_filings` births passages; `read_book` returns the brief's prose |
| `compute`, `read_fundamentals`, `read_prices` and their adapters | replaced by `run` on the research face; already off the meta face |
| `registry.Shapes`, the batch dispatch, `_BUDGET_FREE_TOOLS` special-casing of compute | shapes existed to refuse `compute`'s op/method forms before the budget; a program has one shape |
| the V24 answer grammar and pointer gate kept for the brief (`answer.py` blocks-from-ids path, `gate._core` for briefs) | one grammar, one gate |
| refusal codes that named `compute`'s forms: `op_or_method`, `query_or_item`, `unknown_series`, `not_a_series`, `series_only`, `operands`, `params`, `unsupported_op`, `untyped_series`, … | the forms no longer exist |
| `Formula.alternatives` | after §6 shows every substitution has a lineage row (§8 L3) |
| `fundamentals_service._superseded_line`'s refusal for agreeing lineages | it becomes the follow path; the refusal stays for non-agreeing ones |

Estimated: `fact_adapters.py` 754 → ~200 lines (describe, filings, brief prose); refusal codes 121 → ≤ 40;
the 27 dead V23 live tests go in the same batch.

---

## §3 What each role does after V31

| role | on the research face | on the meta face |
|---|---|---|
| LLM | writes a program per question in the brief's evidence gathering; writes six sections of claims + prose | unchanged from V30 |
| skill | the issuer domains' programs, already delivered; the brief's section prompts | unchanged |
| tool | `run`, `describe` with `lines`, `read_filings`, `search_web` | `describe` with `lines`; `run` inherits lineage through `get_flow` |
| validation | `claims.check` per section; G1 provenance to nodes, G2 relation typing, G3 digits accounted | unchanged |
| data | `metric_lineage` derived at ingest, read through one function | same |

---

## §4 Hotfix for the live site (before any of §2, from `e6c290b`)

Two exposures are live and small. A hotfix branch from the deployed commit, built and deployed from a
pinned worktree with `-p exposure-workbench` (docs/PRODUCTION.md), never from the main tree:

1. **`get_flow` refuses a latest-anchored read of a superseded line and names the continuation**
   (branch commit `8bee083`, `fundamentals_service._superseded_line` + the formula series grid). One
   extra round trip on NVDA/GOOGL revenue questions instead of a figure eleven times too small.
2. **Catalogue `lines`** (§2.3) so the map stops lying by omission. Small; model-facing key names go to
   the boss with the hotfix.
3. **`quality_flags` is a passthrough block, and an unknown key fails on the key, not the call.**
   `PASSTHROUGH_KEYS += {"quality_flags"}` is the contract the resolver already states (`typed_calculator`
   line 293). And `_unit_for` raising on a numeric leaf becomes: the leaf stays in the note marked
   `untyped`, is not promoted to a Fact, and the declared figures survive. Nothing is guessed; nothing
   computed is thrown away.

Acceptance: the production check in §1 rerun on the deployed image shows `line_superseded` for
NVDA/GOOGL and the unchanged AAPL figure; `describe('NVDA')` carries `lines.revenue`; a replay of the
three XOM turns' `compute` calls returns their figures with `unmatched_periods` in the note.

---

## §5 Phases

**Phase 0 — hotfix (§4).** Cherry-pick onto a worktree at `e6c290b`; offline suite green there;
deploy on the boss's word. Acceptance as §4.

**Phase 1 — lineage as data.** `infra/migrations/v31_metric_lineage.sql`; `concept_mapping.
SUPERSESSION_CANDIDATES`; `lineage_service.derive / continuation`; the readiness hook;
`scripts/derive_lineage.py`; consumers per §2.2; catalogue `lines`. Run the derivation over the
corpus and print the table: every row with `agrees`, `overlap_periods`, `overlap_max_rel_diff`.
Acceptance: `get_flow('NVDA','revenue', months=12)` settles on `total_revenues` through 2026-07-26 with
`via` on the result and the calc row; a dated read of 2021-02-01..2022-01-30 still returns `revenue`;
`evaluate_formula_series('NVDA','days_sales_outstanding', last_n=5)` runs to 2026; XOM has no row and
its two lines stay two; the V26 fixture battery shows zero `line_superseded` refusals on issuers with
an agreeing row.

**Phase 2 — the brief on claims.** `SUBMIT_BRIEF_SCHEMA` = six × `claims.ANSWER_SCHEMA`; `_submit_brief`
gates each section with `claims.check`, renders with `claims.accepted`, stores blocks + claims;
`research_session._SYSTEM` rewritten; the research face registry drops the three tools. A brief battery
that does not exist today: the seven prepared issuers on `exposure_gold`, two replicates, `--fixture`,
gold figures from the issuer domain programs already in `tests/battery/programs_v26`. Acceptance: every
brief accepted within the budget; `fact_adapter_error` = 0 by construction; figures_present per brief
against the issuer gold reported beside the V30 chat number for the same issuer.

**Phase 3 — deletion.** §2.5's list in one commit (DP3: no half-switch); test count and src lines
before/after; refusal codes counted.

**Phase 4 — replay and wording.** V26 on the fixture, two replicates (the only powered set); the brief
battery, two replicates; every model-facing string (catalogue `lines` and `how_to_read`, the research
prompt, `submit_brief`'s description, the lineage sentence in `get_flow`'s result) in a wording review
to the boss before commit.

---

## §6 What is measured

| metric | today | target |
|---|---|---|
| `line_superseded` refusals / turn on issuers with an agreeing lineage | 0 on the deployed site because it reports the stale figure instead; on the branch, one per such question | 0, with the figure |
| stale-line figures reachable by a direct read | NVDA, GOOGL | 0 (property test over every issuer: no latest-anchored read returns a window ending before the issuer's latest period without `via` or a refusal) |
| catalogue names whose coverage is not stated | all | 0 (every name reaches the issuer date or appears in `lines`) |
| formula substitutions with no lineage row | not counted | counted in Phase 1; drives §8 L3 |
| `fact_adapter_error` / 100 research turns | 3 / 191 baseline turns | 0 by construction |
| research face tools | 9 | 6 |
| refusal codes in src | 121 | ≤ 40 |
| `fact_adapters.py` lines | 754 | ~200 |
| brief: gate attempts per brief, tokens per brief, figures_present vs issuer gold | not measured | measured, two replicates |
| V26 chat battery (regression check) | C3 numbers in `ARCHITECTURE_AND_TESTING_2026-09-09.md` §3 | within replicate spread on every addressing metric |

---

## §7 Guards (structural, few)

1. **One home for supersession.** A test asserts `Formula.alternatives` is empty (after L3) and that
   `SUPERSESSION_CANDIDATES` is the only place two metric names are related.
2. **Lineage is evidence.** The derivation is a pure function of the facts table; a fixture with the
   NVDA overlap derives `agrees = true`, the same fixture with one overlap value perturbed past the
   tolerance derives `agrees = false`, and a fixture with no overlap derives `overlap_periods = 0`.
3. **No stale window without a word.** Property test over every prepared issuer and every flow metric:
   a latest-anchored `get_flow` either ends at the issuer's latest period, or carries `via`, or refuses.
4. **The map is complete.** For every issuer, every name in `describe().fundamentals.names` either
   reaches `latest_period_end` or has an entry in `lines`.
5. **No adapter walks for figures.** AST guard: no module outside `fact_adapters.describe / read_filings /
   read_book` may call a harvest function, and `fact_adapters` has no `UNIT_BY_KEY`.
6. **One grammar.** `SUBMIT_BRIEF_SCHEMA` sections are `claims.ANSWER_SCHEMA` by identity, not by copy.
7. **Every program on the research face executes on the fixture** (V30 guard 2, extended to the brief
   battery's programs).

---

## §8 Decisions for the boss

- **L1 — lineage tolerance and the no-overlap case.** `overlap_max_rel_diff ≤ 0.5%` counts as
  agreement (NVDA is exactly 0); an overlap of zero periods is not followed. Recommended as stated: the
  desk follows only what the filings themselves confirm.
- **L2 — never rename the quantity.** When a read of `revenue` follows lineage, the Fact is
  `total_revenues` and the result says why. The alternative — presenting it as `revenue` — is simpler
  for the model and wrong for the reader. Recommended: never rename.
- **L3 — delete `Formula.alternatives`** once Phase 1's count shows every substitution has a lineage
  row or is the "only B exists" case (which needs no lineage: the formula's own missing-input path
  substitutes and writes it on the page). Recommended: delete in Phase 3 if the count is zero;
  otherwise the remaining cases are listed here as data defects.
- **B1 — store claims beside blocks** on `IssuerBrief` (a JSONB column, no change to `blocks`).
  Recommended yes: it is what makes a brief's figure traceable to the program node that produced it.
- **B2 — the brief battery's size.** Seven issuers × two replicates ≈ 14 briefs per round, ~30 turns
  each. Recommended as the floor; it is the first instrument the research face has ever had.
- **H1 — hotfix timing.** §4 can ship today from `e6c290b`; it touches production and needs the boss's
  word, and its two model-facing strings (`lines` keys, the refusal sentence) need the boss's read.
- **D12** (from V30) is superseded by §2.1: unification at ingest was the coarse form of this; lineage
  as evidence keeps both lines and records their relation instead of merging them.
- **D13** (subject-free domain view) is unchanged and still open.
