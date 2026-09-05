# V24 — the fact carries its identity: four steps, one gate, no rebuild

Status: **decided, not built** (2026-09-05). §0–§7 are the case and the
decisions; §8 onward is the build. Written from the code as it stands after
V23-R (commit `8050eaa`); every count was read from the code in this
session, not recalled. The plan is a basis, not an authority — the code is.
Decisions taken 2026-09-05: §6.1 do the redraw; §6.2 prose digits resolve
by lookup or refuse; §6.3 Facts are stored BOTH on the step and in a table.

## §0 The decision this plan records

The boss's framing, 2026-09-05, after the three-run battery
(docs/spikes/V23_COVERAGE.md §5):

> The problem should be simple: the agent calls a tool, the tool returns a
> result, the agent uses the result to analyse, the gate checks. Four steps.

The code has those four steps. What it also has, inside each step, is a
layer that RECONSTRUCTS what an earlier step already knew — and every one
of the small failures the batteries have been finding since V14 lives in a
reconstruction. This plan removes the reconstructions rather than teaching
them another case.

## §1 What one turn actually does today (read from the code)

```
① model calls a tool ──MCP──▶ tools/registry.invoke
     validate args → reserve budget → run the service fn (its OWN result shape)
     → table.declare(): walk the result for id-shaped strings + the registered scope
     → table.build(): re-read those rows from the DB; quantities.of_ref() NAMES
       every number (<table>.<row>.<col> | head@period | op.key.label …);
       over 16k chars → drop run scopes off the tail, then whole series entries
     → result["table"] = the slice        ◀ the model receives the raw payload AND
                                            the slice: one fact, two encodings
     → record_step(evidence_refs = the declaration, narrowed to what fit)

② model writes respond(blocks): 6 block types; a figure is a slot {ref, name};
   text may carry no digit (9 exempt classes) and no compound name the table holds

③ gate — services/resolver.resolve():
     table.load(): re-read EVERY completed step's declaration, re-query, re-name
     → validate_shape: the text rule (5 regexes, 9 exempt digit classes, a
       serialised-slot detector, a name-as-prose detector)
     → not_on_table → unknown_name → unverified_quote
     → unsupported_assertion (block type ↔ row kind, via three kind vocabularies)
     → rendered(): fill values, derive table headers from names, trend summaries

④ outside the gate: services/prose_critic — a second model judges whether the
   sentence calls the figure what it is. Cannot refuse.
```

Measured surface of the gate path:

| what | count | where |
|---|---|---|
| lines on the gate path | ~2,600 | answer_blocks, resolver, table, quantities, resources, display_names, display_conventions, arg_validation, batch |
| namer branches | 9 `_from_*` | services/quantities.py (calc, ranking, scenario, fact, alert, run, position, chunk, source) |
| unit fallbacks for one calc row | 3 | `_calc_unit`: column → params blob → legacy op table |
| exempt digit classes in prose | 9 | answer_blocks `_NOT_A_FIGURE` |
| kind vocabularies | 3 | quantities KIND_*, table `_PREFIX_TYPE`/KIND_TASK, answer_blocks *_KINDS |
| block types | 6 | paragraph, metric_table, chart, trend, absence, action |
| places a new kind of truth must be taught | 6 | calc_kind, *_KINDS, resolver `wanted`, block schema, validate_shape branch, renderer |
| channels carrying one figure to the model | 2 | the service payload and `result["table"]` |
| sets of "what may be pointed at" | 2 | the transcript (model's) and the rebuilt table (gate's) |

Each module, read alone, keeps the 9/1 contract: a lookup, no judgement.
What they look up is a table rebuilt from storage by a program that has to
be taught every new row shape — so the error class was not removed, it
moved from the prompt into the namer and the exemption list.

## §2 Why the small problems keep coming (root cause, not a list)

One decision — **a figure's identity is dropped where it is produced and
rebuilt at the door** — and its consequences, which the batteries met one
at a time:

1. **Identity is inferred from storage.** A tool computes a number; later
   `quantities.of_ref` reads the row back and guesses name and unit from
   operation prefix, `params.result_type`, `_CALC_RESULT_KEYS`, the
   resources column tables. Every new producer needed a namer branch: rank
   (V17 `_from_ranking`), scenario (V22 `_from_scenario`), counts (V8/V20
   `_RUN_COUNTS`), collinearity (V11-F projection). This is the "built on the
   issuer side, not on the book side" shape: the namer knows issuer rows and
   learns each book row separately; a row it was not taught is a small bug
   (a count that was not a count; a label the model wrote; an as-of that
   cannot be cited; a figure inside a verified quotation that cannot be
   written).
2. **Two encodings of one fact reach the model.** The payload says `weight`,
   the slice says `issuer_exposures.MSFT.weight`. The model writes whichever
   it read. 123 of 196 V15 refusals were names the model was never shown;
   `name_written_as_text` and `slot_written_as_string` (V23-R) are the same
   seam.
3. **The model's citable set and the gate's are built from different
   sources.** The model's comes from the transcript; the gate's from the
   declaration ledger, rebuilt. Truncation drops, scope-less runs, projected
   coefficients and a refusal's echoed ids are in the first and not the
   second — `not_on_table` six times in C03#t3.
4. **The gate polices prose, not only pointers.** Because prose may carry a
   digit, the gate scans for digits; because it scans, it exempts dates,
   10-K, Q4, H200, "30-day", "95% VaR" — nine classes, each added after a
   battery tripped on it. It is a rule list on the LLM path, grown inside the
   gate instead of the prompt. It is also the ONE check on the path that is
   lexical rather than a lookup.
5. **Kind is declared by block type.** trend/absence/action/chart each pin
   one row kind; a new kind of truth is six edits (table above).
6. **Three absences, three mechanisms.** `not_reported` mints an `absence.*`
   calc row and can be pointed at; `not_held` and `cannot` are static dicts
   in the catalogue and cannot. The honest sentence has nothing to point at,
   so a neighbouring true figure is substituted (C04, C13).

## §3 The target: a fact carries its identity, end to end

One rule: **a fact is a typed value object, built once at the tool
boundary, carried unchanged, and never rebuilt.**

```
Fact = {
  id,                       # minted per fact (not per storage row)
  kind,                     # scalar | series | passage | absence | task
  subject,                  # MSFT | port_… | run_… | the desk
  measure,                  # what it is: net_margin, weight, adj_close, "Item 7 passage"
  value | points | text,    # by kind
  unit, as_of, window?,     # identity the reader is shown
  standalone: bool,         # false for a collinear coefficient — may be cited, not shown alone
  sources: [...],           # fact_/chunk_/calc_/run_ ids it rests on (the evidence drawer's path)
}
```

The four steps, with nothing rebuilt:

1. **Tool → `{facts: [Fact…], note}`.** One shape for every tool. Each
   service's output is turned into Facts by an adapter AT the tool boundary
   — the only place identity is decided. The adapters use the same
   declarations the namer uses today (`resources.Column` unit/display,
   `display_names`), at write time instead of read time. The model is shown
   the COMPACT form (§9): columns declared once per result, one row per
   fact, result-wide fields lifted. Payload caps count facts, never cut one
   in half, and say how many were held back and how to ask for them.
2. **Session ledger = the Facts this session has shown, by id.** Stored where
   declarations are stored today: `agent_steps.evidence_refs` (JSONB), whose
   content changes from `[{type, id, scope}]` to `[Fact…]`. No new table. The
   JSON the model read and the JSON the gate loads are the same object, so
   "what was shown is what is on the table" holds by construction, not by
   narrowing scopes until they agree.
3. **Model writes argument and pointers.** Two layouts: `paragraph` (text and
   `{fact: id}` in reading order) and `table` (cells are ids). trend, absence
   and action stop being block types: each is a paragraph pointing at a
   fact of kind series / absence / task. `chart` is a layout over a series
   id. Six block types → two layouts plus chart.
4. **Gate = three lookups.** (a) every id in the answer is in this session's
   ledger; (b) the layout admits the fact's kind (a cell takes a scalar, a
   chart takes a series, `standalone: false` may not stand in a cell or
   alone); (c) **every digit token in the prose resolves against the ledger**
   — to a fact's value (exact, at the written precision, or unit-scaled), to
   a fact's identity field (`as_of`, `window`, period, a method parameter, a
   rank), or to the text of a passage the block cites — and a token that
   resolves to nothing refuses the answer as `unsourced_figure` (decision
   §6.2). The quotation check (V5) stays as a lookup against passage facts.
   A resolved token is rendered as a link to what it resolved to (one fact,
   or the list of facts that share the value, each with its identity); no
   digit reaches the reader without a source behind it.
   Rendering shows each fact's identity — measure · subject · as-of · unit ·
   source — and the click-through to the evidence drawer that already exists
   (`AnswerBlocks.Figure` → `/api/evidence/{id}`). The critic disappears: the
   question it asked ("did the sentence call the figure what it is?") is
   answered by display.

Absence becomes one mechanism: `not_reported`, `not_held` and `cannot` are
all facts of kind `absence` that a tool returns, so the honest sentence
always has something to point at.

## §4 What this removes by construction, and what it does not

Removed:

| failure class | why it cannot recur |
|---|---|
| `unknown_name`, label ambiguity | there are no names, only ids the model was shown |
| name written as prose | there are no compound names to write |
| label beside a figure is the model's; critic disagreements | identity is displayed from the fact |
| a count / an as-of / a figure in a verified quotation cannot be cited | fields of a Fact or a passage fact |
| truncation drops an id the model still holds | caps are per fact; shown == ledgered |
| model's citable set ≠ gate's | one object, one store |
| a new kind of truth is six edits | it is a `kind` value and a renderer case |
| three absence mechanisms | one kind |
| namer branches per producer | adapter per tool, at the boundary, tested against the tool's own output |

Not removed (and nothing architectural removes them):

- the model choosing a fact that does not support its argument — identity
  on display makes it visible, not impossible;
- catalogue quality: salience order (`describe()` lists 7 portfolios in
  storage order, the real book seventh), the cross-run series (C03#t3), the
  `honest_absence` battery criterion;
- quota, budget, the MCP hop, the worker — untouched.

Those move from "teach the namer, add a block type, add a kind" to "add a
tool that returns Facts".

## §5 Size of the redraw (to be measured before phase A)

To be counted, not estimated, before anything is built:

1. the distance from each of the 10 tools' service output to `{facts}` —
   which adapters are a mapping and which need the service to say more
   (`as_of`, `window`, `subject`);
2. the evidence-drawer resolver (`/api/evidence/{id}`) against fact ids
   minted per fact rather than per row — whether a Fact's `sources` is enough
   for the drawer, or the ledger needs to store the Fact for the drawer too;
3. `apps/web/app/components/analyst/AnswerBlocks.tsx` (466 lines): what
   changes when six block types become two layouts and a slot becomes a fact;
4. the test surface: which of the ~1,430 tests read block types, slot names or
   the table slice (the V23 reconnaissance method — list every reference
   point first, then change once).

## §6 Decisions for the boss

1. **Do the redraw** (this plan) or clear the battery list in order
   (topic status box, next ②).
2. **The digit rule in prose — DECIDED 2026-09-05.** The boss's condition:
   a digit in prose must be traceable, and an untraceable one must not reach
   the reader — it is either a figure that should have been computed and
   `compute` was not called, or a figure with no source, and neither is
   allowed. So the rule is neither (a) nor (b) as first posed: it is a
   LOOKUP. Every digit token in accepted prose is resolved against the
   session ledger (§7 gives the resolution order and the measured coverage);
   what resolves is linked, what does not refuses the answer. The nine
   lexical exemption classes go: a date is a fact's `as_of`, a window or a
   confidence level is a method parameter the fact carries, a period label
   is a series point's period, a form name or a product designator is in the
   passage the block cites — each a field lookup, none a regex over prose.
   What the model must do when refused is stated in the refusal: compute it,
   cite the passage that states it, or drop it.
3. **Storage of the Fact — DECIDED 2026-09-05: both.** The step carries the
   Facts it showed (`agent_steps.evidence_refs`, the ledger the gate loads —
   what was shown is what is checked, one JSON object), AND a `facts` table
   keyed by id holds every Fact ever minted, so the evidence drawer, a brief
   and a later session resolve `f_…` without finding the step. Written in
   the same transaction as the step; the table is the index, the step is the
   record.

## §7 Measured: what digits prose actually carried, and whether each had a source

Boss's decision on §6.2: **(b)**, with a condition — a digit that appears in
prose must still be traceable; the question is not how to refuse those cases
but how to give them a source. So every refused `respond` in the live DB
(200 steps, 64 with `digits_in_text`, 2026-08-31 → 09-05) was replayed
through `validate_shape`, and every digit token was matched against the
SESSION'S OWN TABLE as `table.load` builds it (scratchpad `digits_replay*.py`).

| what the digit was | n | traceable? how |
|---|---|---|
| a slot serialised into a string | 175 | yes — it IS a pointer; parse it |
| an evidence id written into prose | 47 | yes — a pointer; render as a link |
| equals ONE ledger figure exactly | 25 | yes — value lookup, unique |
| equals MANY ledger figures (mostly one quantity under two names: `issuer_exposures.MSFT.weight` = `limit_checks.issuer_concentration:MSFT.current_value`) | 43 | yes, to a candidate list |
| a ledger figure at the precision the model wrote (1.50 for 1.4968…; 16.3% for 0.16342) | 26 | yes — match at written precision (10 unique, 16 many) |
| a ledger figure rescaled ("$38.1bn", "2.4739 billion") | ~15 | yes — match with unit scaling |
| a figure inside a passage the block cites ("82 percent", "56 percent") | 16 | yes — link to the passage; the quote check already proves it |
| a parameter, not a fact ("95% 1日 VaR", "30日", "12-1", "ranked 4th") | ~25 | not a fact; needs no source. The Chinese "95% 1日 VaR" missed the English-shaped exemption — the exemption list breaks per language |
| head arithmetic or recall ("fell from 225.47 to 205.10, a decline of about 9.03"; "3 active alerts out of 27") | ~30 | **no — nothing on the ledger produced it.** Only `compute` can give it a source |

After V23-R the residue is: ids in prose 8, passage figures 10 (the 82%/56%
case), ambiguous value 2 — every one of them linkable under the rows above.

**What this says.** A number the model writes in prose is, ~90% of the
time, a number it saw this session — and the session ledger is finite and
known. So a digit in prose is resolved by LOOKUP against the ledger, in the
gate (decision §6.2: what does not resolve is refused, not shown):

    for each digit token in the prose:
        an id                                    → the fact / row it names
        equals one ledger fact's value
          (exact | at written precision | unit-scaled ×1e3/1e6/1e9 with its suffix)
                                                 → that fact
        equals several facts' values             → all of them (each shows its identity)
        equals a fact's identity field
          (as_of, period, window, confidence, rank ordinal, method parameter)
                                                 → that fact's field
        substring of a passage the block cites   → the passage
        else                                     → REFUSED: unsourced_figure
                                                   "compute it, cite the passage that
                                                    states it, or drop it"

Rendering links every resolved token to what it resolved to. The V14
objection ("0.06 is TLT's weight AND a stress warning level") is answered by
display, not by guessing: a value shared by several facts links to all of
them with each one's identity. The one class that cannot resolve — the
model's own arithmetic ("fell from 225.47 to 205.10, a decline of about
9.03") — is exactly the class `compute` exists for, and the refusal says so.

Against the replayed data: every row of the table above except the last two
resolves; the "parameter" row resolves through identity fields once a Fact
carries them (today "95% 1日 VaR" fails only because the exemption is an
English regex); the "head arithmetic" row is refused, which is the decision.

The transforms the lookup may apply are a closed set (exact, written
precision, three unit scales with their suffixes) and are the same
`display_conventions.reader_value` the renderer already uses — a value
matched under a transform the renderer would not print is not a match.


## §8 The build

Order of work, each phase green on its own (offline suite + the live
twelve-question round). One cutover commit (phase C) switches what the model
sees and what the gate checks together, because the two sides of that
contract cannot be on different versions for a single turn. Everything
before it adds; everything after it removes.

### Phase 0 — measure before building (no product code)

| measure | how | decides |
|---|---|---|
| facts per tool result on the live desk: `describe(MSFT)`, `describe(run)`, `describe()` , `read_book(run, all names)`, `read_prices(1y)`, `compute(panel)`, `read_filings(item='7')` | a scratch script calling the service fns and counting numeric leaves | `FACTS_PER_RESULT`, `SERIES_POINTS_INLINE`, `PASSAGE_CHARS` (§9) |
| characters of a Fact list vs today's `table` slice for the same result | serialise both | whether the 16k ceiling holds or moves |
| every stored accepted answer (agent_messages.meta.blocks, 1,388 accepted responds) replayed under gate rule G3 | the §7 scripts extended with identity-field tokens | which identity fields a Fact must carry for prose that passes today to keep passing (dates, periods, windows, confidence, ranks, form names) — extended by FIELD, never by regex |
| the reference list: every file that reads a block type, a slot name, `result["table"]`, `evidence_refs`, `quantities.*`, `resolver.*`, `answer_blocks.*` | grep, as V23's reconnaissance did | the phase E deletion list and the test files to rewrite (today: 23 files / 158 references to quantities; 10 / 53 to the resolver; 12 / 36 to refusal names; 5 / 44 to block types) |

Done when: the four numbers are in this document's §9 and the reference
list is a checked-in file under `docs/spikes/V24_REFERENCES.md`.

### Phase A — the Fact and its producers

New `services/facts.py`:

```python
@dataclass(frozen=True)
class Fact:
    id: str                    # f_<12 hex>, minted per fact (utils/ids.new_fact_ref_id)
    kind: str                  # scalar | series | passage | absence | task
    subject: str | None        # MSFT | port_… | run_… | None for the desk
    measure: str               # net_margin | issuer_exposures.weight | adj_close | "Item 7" | not_reported
    unit: str | None           # RATIO | MONEY | COUNT | MULTIPLE | MONEY_PER_SHARE | None
    value: float | None        # scalar
    points: tuple[tuple[str, float], ...] | None   # series: (period, value)
    text: str | None           # passage text, absence statement, task state
    as_of: str | None
    window: dict | None        # {"start","end"} | {"months": 12} | {"days": 30} | {"name": "1y"}
    params: dict               # confidence, benchmark, method params, rank ordinal…
    standalone: bool           # False for a collinear coefficient (V11-F) — citable, not shown alone
    sources: tuple[str, ...]   # fact_/calc_/chunk_/src_/run_/alert_/task_ ids — the drawer's path
    group: str                 # the M2 question key (resources.GROUP_QUESTIONS), kept
```

Two serialisations, one function each: `for_model(fact)` (value at
`reader_value` precision, identity fields, no `sources` beyond the first
id) and `for_record(fact)` (everything, full precision). The model-facing
form is what goes on the step; the record form is what goes in the table.

New `services/fact_adapters.py` — one adapter per tool, `(result: dict) ->
(facts: list[Fact], note: dict)`. The adapter knows its tool's payload shape
and turns every figure in it into a Fact using what the namer used at read
time (`resources.Column` units and displays, `display_names`,
`calc_kind`'s prefixes), now at write time. `note` is the payload with the
fact-bearing fields REMOVED — the refusal `error`/`detail`, the `basis`
sentence, `available` name lists, `held_on`, `truncated`; never a value.

| tool | facts it emits | note it keeps |
|---|---|---|
| `describe` | every figure the catalogue prints: counts, latest values, ranges' ends, `held_in` weights, book market value | the map: names, methods, procedures, absences (`not_held`/`cannot` become `absence` facts with `text`), how_to_read |
| `read_fundamentals` | flow → 1 scalar (window, terms as sources); balance sheet → 1 scalar per metric (as_of); series → 1 series fact (points) plus none per point; `metric_not_filed` → 1 absence fact | `available`, `detail`, `derivation` |
| `read_filings` | search → 1 passage fact per hit (text, sources=[chunk_id], as_of = filing date); item → 1 passage fact (text capped at `PASSAGE_CHARS`, `truncated` flagged, source = section) | query, item code, citation urls |
| `read_prices` | series → 1 series fact; single session → 2 scalars (close, adj_close) | window name |
| `read_book` | run/scenario by name → 1 scalar per name (subject from the row label, as_of the run's); sections → each figure in `alerts`/`attribution`/`risk_state`/`positions`/`limits`/`freshness`/`runs`; task → 1 task fact (text = state) | section prose, `unknown` names, detail |
| `compute` | op → 1 scalar (`calc_id` in sources, `periods` → window); rank → 1 scalar per entry with `params.rank`; regress/beta → the named coefficients as scalars, `standalone` from the row; series stat → scalar or series; method → as the executor's payload says (panel → one scalar per line, absences per absent line; scenario → each before/after figure with `params.scenario`); refusals → absence facts where the service minted one | `basis`, `definition`, `authority`, `note`, refusal detail |
| `search_web` | 1 passage fact per source (text = snippet, sources=[src_id], as_of = published) | query, days |
| `start` | 1 task fact | kind, reason |
| `think`, `respond`, `submit_brief` | none | — |

`Tool.facts: Callable` replaces `Tool.evidence`; `register()` refuses a tool
that declares neither `facts=` nor `NO_FACTS` (the same refusal that today
guards `evidence`).

**Invariant I1, pinned by `tests/test_fact_adapters.py`:** for every tool and
every fixture payload (success, each refusal), `numeric_leaves(note) == []`
— no number reaches the model outside a Fact. No allowlist. A count of
observations is a Fact (`measure="observations"`, unit COUNT); a score is a
Fact or it is dropped from the note.

**Invariant I2:** every Fact has `as_of` or `window` unless its kind is
`task`; pinned per adapter.

Done when: the adapters exist for all nine tools, I1 and I2 pass on
fixtures captured from the live desk (phase 0's calls, stored under
`tests/fixtures/v24_payloads/`), and `services/quantities.py` is not
imported by any adapter (the adapters read `resources`/`display_names`
directly — the namer stays alive only for the old gate until phase E).

**Phase A done, 2026-09-05.** `services/facts.py`, `services/fact_adapters.py`,
`tests/test_fact_adapters.py` (246 cases over 47 fixtures: I1, I2, unit,
id/note agreement, model-form round trip, the caps). The adapters are one
walker over five payload shapes plus a per-tool context, not nine programs.
What I3 found on the first run, fixed at the SOURCE (a service now says what
it always knew): `get_flow`, both series reads and the balance sheet carry
`unit_class` (the sheet judged per balance by `units.fact_unit`, `UNKNOWN`
stated rather than binned); `evaluate_formula` and the panel carry the last
step's `periods` (or its declared basis); `window_return` carries unit,
window, as_of; `rank` carries `as_of` per entry and for the ordering;
`describe` carries `catalogue_as_of`; an issuer's alert rows carry the
alert's date; `read_book` by name returns the figures' values in the payload
(it returned names only — the old slice carried the values). One measured
surprise: the first run's model form was over 16k for book.analysis and the
cap silently held back its `positions` — caught by the count test, which now
pins that no phase-0 fixture is held back. Offline suite after phase A:
1,832 + 246.

### Phase B — the ledger, the table, the drawer

1. `infra/migrations/v24_facts.sql` (additive, idempotent, mirrored in
   `infra/init.sql` and `db/models.Fact`):

```sql
CREATE TABLE IF NOT EXISTS facts (
  id          VARCHAR(64) PRIMARY KEY,
  session_id  VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  step_id     VARCHAR(64),
  message_id  VARCHAR(64),
  kind        VARCHAR(16) NOT NULL,
  subject     VARCHAR(64),
  measure     TEXT NOT NULL,
  unit        VARCHAR(24),
  value       DOUBLE PRECISION,
  points      JSONB,
  text        TEXT,
  as_of       DATE,
  "window"    JSONB,
  params      JSONB NOT NULL DEFAULT '{}',
  standalone  BOOLEAN NOT NULL DEFAULT TRUE,
  sources     JSONB NOT NULL DEFAULT '[]',
  "group"     VARCHAR(32),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session_id);
ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON facts;
CREATE POLICY tenant ON facts USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = facts.session_id AND s.owner_id = current_setting('app.user_id', true)))
                          WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = facts.session_id AND s.owner_id = current_setting('app.user_id', true)));
```

   Same tenant rule as `agent_steps`. Public-demo sessions resolve the way
   their steps do today; nothing new to decide.

2. `registry.invoke` step 4 becomes: `facts, note = tool.facts(result)`;
   cap (§9) with `held_back = {count, how}`; `record_step(evidence_refs=
   [for_model(f) …])` and `db.add(Fact row …)` for each, one transaction
   with the step; the tool result returned to the model is
   `{"facts": [for_model(f) …], "note": note, "held_back"?: …}`.
   **Until phase C the old `table` slice is still attached beside it** so the
   old gate keeps working on the same commit — the one deliberate
   two-encoding interval, removed in C.

3. New `services/ledger.py`: `load(db, session_id) -> Ledger` reads
   `evidence_refs` of the session's completed steps and parses Fact dicts —
   no per-ref query, no naming, no narrowing. The step stores the RECORD
   form (`for_record`, complete, one object per fact — a step is not
   token-bound); the model is shown `block_for_model` of the same facts. The
   two agree by id, and the ledger indexes the record form, so a value shared
   by the block (lifted sources) is on every fact the gate reads. Entries that are not Facts
   (pre-V24 declarations) are ignored. Indices built once per load:
   `by_id`; `by_value` (keys: full value rounded to the unit's
   `MODEL_DECIMALS`, and the `display()` string); `identity_tokens` (see
   G3); `passages` (kind == passage: id → text).

4. `evidence_resolver_service`: `f_` resolves from the `facts` table to the
   envelope `{type: "fact", id, label: "<measure> · <subject> · <as_of|window> · <unit>", body: for_record(fact), upstream: sources as typed refs}`.
   `/evidence/labels` follows for free. `utils/ids.new_fact_ref_id`
   (`f_`) and the frontend `ID_BODY` regex learn the prefix.

Done when: a live turn writes facts rows and step JSON that agree
(`tests/test_ledger_live.py` compares them), and the drawer opens an `f_`
id from a stored answer.

### Phase C — the grammar and the gate (the cutover commit)

New `services/answer.py` (replaces `answer_blocks.py`) — the grammar:

```
paragraph  {type, runs: [str | {fact: id}], cites?: [passage fact ids]}
table      {type, title?, rows: [[fact id, …], …]}
chart      {type, kind: bar|line|waterfall, fact: series fact id}
```

Three block types. trend, absence and action are paragraphs pointing at a
series / absence / task fact; the renderer shows each kind in its own form
(the V19 series line under a series chip; "not reported" beside an absence
chip; "started" beside a task chip). `metric_table` rows are ids only; the
header and row labels are derived from the facts' `measure` and `subject`
(V19's rule, now reading fields instead of parsing names).

New `services/gate.py` (replaces `resolver.py`) — three lookups against the
loaded ledger, in this order, each refusal naming block, token and fix:

| check | refusal | lookup |
|---|---|---|
| **G1 ids** — every id in runs, cells, chart, cites is `in ledger.by_id` | `not_on_ledger` | set membership |
| **G2 kinds** — a cell's fact is `scalar` and `standalone`; a chart's is `series`; `cites` are `passage`; an inline `standalone: false` fact | `kind_does_not_fit` / `not_standalone` (with the fact's own reason) | field read |
| **G3 prose** — (a) every digit token in a string run resolves: an `f_` id → that fact; equals a fact's value exactly, at the written precision, or under one of the three money scales with its suffix → that fact (or the set sharing the value); equals an identity token → that fact's field; substring of a passage the block cites → the passage; else refuse. (b) a compound name the ledger holds written as prose (V23-R's rule, reading `measure` strings). (c) a quoted span of ≥4 words is verbatim in a cited passage (V5, unchanged) | `unsourced_figure` / `name_in_prose` / `unverified_quote` | dictionary lookups; the digit-run regex only FINDS tokens, it decides nothing |

`identity_tokens` of a Fact: `as_of` whole and its year; each series
point's period whole and its year; `window` values as written (`12`,
`30`, `1y`); `params` values as written and with `%` (`0.95` → `95`,
`95%`); `params.rank` ordinal (`4`, `4th`); digit runs in `measure`
(`momentum_12_1` → `12`, `1`). Phase 0's replay says which of these the
stored answers actually need; a class not needed is not added.

`accepted(blocks, verdict)` fills every `{fact: id}` with `for_model(fact)`
plus `display`, and splits each string run at its resolved tokens into
`str | {link: [fact ids] | passage id, as_written}` pieces — so a prose
digit reaches the reader already carrying what it resolved to, and the
client draws links without a regex. `text` (prose only) is kept beside
`blocks` as today.

`respond` and `submit_brief` (`tools/meta_tools.py`, `tools/research_tools.py`)
call `gate.check` and `gate.accepted`; `RESPOND_SCHEMA` and
`SUBMIT_BRIEF_SCHEMA` carry the three-block grammar. `_SYSTEM` says the new
contract in the same breath it says the old one today: a figure is a fact id
from a `facts` list; a number you worked out yourself has no id — `compute`
gives it one.

The same commit removes `result["table"]` from `invoke` and `_load_history`
gains nothing (history is unchanged; a session that spans the cutover simply
has no ledger for its earlier steps — see §11).

Done when: the offline suite is green with the new gate; the live twelve
questions from V23 §3 run with zero `not_on_ledger` caused by a shown id;
the §7 replay of the 200 refused responds under G3 gives the table §7
predicts (every row resolves except head arithmetic).

**Phase C built, 2026-09-05 (offline green; live rounds are phase F, after
the containers are rebuilt).** `services/answer.py` (three blocks, the token
finder, the renderer whose table header and labels come from the facts),
`services/gate.py` (G1/G2/G3 as lookups on the ledger; eight named refusals
and no digit class), `respond` and `submit_brief` on the gate, the wrapper
returning `facts` + `note` and recording only facts, `_SYSTEM` and the MCP
instructions restated, the research pack reading the ledger. Tests:
`test_answer_grammar.py`, `test_gate.py` (one case per refusal and per §7
class, the Chinese "95% 1日 VaR" included), `test_tool_registry.py` rewritten
around facts, `test_submit_gate.py` on a hand-built ledger; the old grammar
tests removed. **Scope note found while cutting over:** `services/quantities.py`
is not only the gate's namer — it is the operand grammar of `compute`
(`run_…:issuer_exposures.MSFT.weight`) and the source of `read_book` by name
and `describe(run)`'s name list. It stays as the run-children namer (driven
by `resources.py`); what phase E removes is its gate-facing role (`table.py`,
`resolver.py`, `answer_blocks.py`, `prose_critic.py`). Letting `compute` take
fact ids as operands (`f_…`, resolved through the facts table) is the way to
retire the `ref:name` grammar later; registered as a phase-F residual.

### Phase D — the renderer

`apps/web/app/components/analyst/AnswerBlocks.tsx`:

- `FactChip` replaces `Figure`: shows `display(value, unit)`; hover shows
  measure · subject · as_of/window · unit · source count; click opens the
  drawer on `f_…`. Series chips render the V19 series line; absence and
  task chips their labels.
- `Prose` renders the split runs: text, chips, and `{link, as_written}`
  pieces as the written text underlined, click → the fact, or a small
  chooser when several facts share the value (each with its identity).
- `table` derives header/labels from chip fields; `chart` unchanged.
- The pre-V24 block types stay renderable (as `columns`/string cells did
  after V19): stored answers are records.
- `Dock.tsx`, `issuer/[ticker]/page.tsx` (the brief) need no change beyond
  the type import; `lib/display.ts` unchanged (same fixture).

Done when: a V24 answer and a V19 answer from the live DB both render, and
the chooser appears on a value shared by two facts.

### Phase E — remove the reconstruction

Deleted, with their tests: `services/quantities.py` (the namer),
`services/table.py`, `services/resolver.py`, `services/answer_blocks.py`,
`services/prose_critic.py`, `scripts/critic.py`, `Tool.evidence` /
`Evidence` / `NOT_EVIDENCE`, `_TOOL_SPECS` remnants, the nine `_NOT_A_FIGURE`
classes, `answer_blocks._ID_TOKEN`, `test_quantities.py`,
`test_price_quantities.py`, `test_table.py`, `test_table_meaning.py`,
`test_one_resolver.py`, `test_v21_critic.py`, `test_v15_table_live.py`.

Rewritten: `test_output_grammar.py` (three blocks; G3 cases from §7's
classes — one per row, including "95% 1日 VaR" in Chinese), `test_gate_matches.py`,
`test_meta_agent_gate.py`, `test_submit_gate.py`, `test_evidence_labels.py`,
`test_v23_catalogue_and_compute.py` (adapter cases beside each compute
case), `test_report_gate.py` untouched (the daily report's V3 gate is a
separate path and out of scope — noted, not hidden).

Kept: `analytics/resources.py` and `display_names.py` (the adapters'
declarations), `display_conventions.py`, `numeric_verification.py` (report
path only).

Done when: `grep -rn "quantities\|answer_blocks\|resolver\." src apps tests`
returns only the report path and this document's history; the offline
count is recorded in §12.

**Phase E done, 2026-09-05.** Removed: `table.py`, `resolver.py`,
`answer_blocks.py`, `prose_critic.py`, `scripts/critic.py`, `Tool.evidence` /
`Evidence` / `NOT_EVIDENCE` and every `evidence=` registration, and their
tests (`test_table`, `test_table_meaning`, `test_v21_critic`,
`test_v15_table_live`, the declaration tests in `test_tool_registry`,
`test_symmetry`, `test_portfolio_snapshot`). `numeric_verification` (the
daily report's V3 gate) now imports the quotation check from `gate.py`.
`quantities.py` stays as the run-children namer (see phase C's scope note).
Which tools produce facts is `fact_adapters.ADAPTERS` by name, pinned by
`test_every_tool_on_a_face_has_a_fact_adapter`. Offline: 1,994 passed.

### Phase F — live rounds and the battery

1. The V23 §3 twelve questions, three rounds, each round fixing the
   catalogue or an adapter — never the gate. Residuals to the topic status
   box as V23 did.
2. The 13-conversation battery (`scripts/conversation_battery.py`) against
   V23-R, side by side in `docs/spikes/V24_COVERAGE.md`: deterministic
   columns (verified figures now = chips + resolved prose links; refusals by
   name; turns lost) and `so_what`.
3. `honest_absence` added to `tests/battery/criteria_conversations_v21.json`
   (the criterion the boss named 9/5: an answer that says the desk does not
   hold a split, pointing at an absence fact, scores above a substituted
   figure).
4. `scripts/exit_metrics.py` counts `unsourced_figure` refusals separately:
   that number is the model's arithmetic habit, and it should fall as
   `compute` is reached for it.

### Phase G — documents

`MODULE_NOTES.md` M26 (the Fact, the ledger, the gate — replacing M2/M11
paragraphs that describe the namer and the table), `ARCHITECTURE_AS_BUILT.md`
(the four steps as built, with the two invariants), `TARGET_ARCHITECTURE.md`
(a note that the evidence-trail module is the ledger), this plan's status
line, the topic log. The `_SYSTEM` text and the tool descriptions that
change go to the boss for wording before the commit that carries them
(standing instruction).

## §9 Ceilings and the model form — set from phase 0 (measured 2026-09-05)

**Phase 0 is done.** Three measurements on the live desk (`run_b791e7985dcd`,
`port_001`, MSFT; every call in one rolled-back transaction; payloads saved
as adapter fixtures under `tests/fixtures/v24_payloads/`):

**(1) Facts per result and their size, three candidate model forms.**
`verbose` = one object per fact with every field named; `compact` = the
columns declared once per result and one row per fact; `compact60` = the
same with a series showing 60 points inline.

| call | payload today | facts | verbose | compact | compact60 |
|---|---|---|---|---|---|
| describe() | 6,609 | 11 | 2,303 | 863 | 863 |
| describe(MSFT) | 8,630 | 8 | 1,695 | 681 | 681 |
| describe(run) | 14,296 | 1 | 195 | 175 | 175 |
| read_fundamentals sheet | 2,013 | 17 | 3,980 | 1,688 | 1,688 |
| read_filings search k=5 | 11,034 | 15 | 3,292 | 1,284 | 1,284 |
| read_prices 1y | 16,703 | 2 (1 series) | 6,467 | 6,338 | 1,703 |
| read_book run sections | 7,330 | 114 | 26,490 | 10,424 | 10,424 |
| read_book port 5 sections | 6,083 | 68 | 15,462 | 5,928 | 5,928 |
| compute issuer.panel | 15,050 | 23 | 4,998 | 1,854 | 1,854 |
| compute book.analysis | 7,811 | 146 | 31,661 | 11,051 | 11,051 |
| compute book.sell | 6,016 | 101 | 21,771 | 7,551 | 7,551 |
| the whole run by name (161 quantities) | 11,344 (today's slice) | 161 | 37,321 | 14,581 | 14,581 |

The verbose form is 2.5–3.4× today's slice and does not fit; the compact
form is at or under it everywhere. **So the model form is the compact one**
(§3 amended): a result's `facts` block declares its columns once and
carries one row per fact. The record form (the `facts` table and the step's
`evidence_refs`, `for_record`) stays one full object per fact.

**Corrected after phase A** (the estimate above priced a row without its
`params`, `window` and `sources`; the built form, measured over the same
fixtures): book.analysis 146 facts = 25,390 chars, run sections 114 = 16,477,
book.buy 105 = 15,621, Item 7 = 12,697, five passages = 10,128. Every fact
of a result shares its `sources` (the run) in these cases, so the block
states them once and the rows carry `[]` — 38 characters a row — and the
ceiling is set where the largest measured result fits whole:

| name | value | why |
|---|---|---|
| `FACTS_CHAR_LIMIT` | 24,000 | book.analysis, the largest result, shown whole with shared sources lifted; `held_back` above it |
| `FACTS_PER_RESULT` | 200 | the largest measured result is 146; over it, `held_back` names the rest and the call that reads them by name |
| `SERIES_POINTS_INLINE` | 60 | first, last, min, max always; evenly thinned between; 1y prices 254 points → 60; the record keeps every point |
| `PASSAGE_CHARS` | 12,000 | Item 7 is 51k; a passage fact shows a capped text with `truncated` and its section id for the drawer |
| `TOOL_RESULT_LIMIT` | 28,000 | the `note` cap, unchanged — and the note is now the payload with its figures replaced by fact ids, so it is a third to a half of what it was |

**(2) The reference list** is checked in: `docs/spikes/V24_REFERENCES.md`
— 159 file×pattern hits; by surface: the namer 41 files, `Evidence()` /
`evidence_refs` 31, refusal names 19, `answer_blocks` 19, the slice 17,
the resolver 17, block types 11, the critic 4.

**(3) Every accepted block answer (229) replayed under G3.** 347 digit
tokens in their prose. Tokens whole (an id is one token, a date is one
token) and resolved in G3's order against the session's own table plus the
identity fields its rows would carry as Facts:

| resolved by | tokens |
|---|---|
| an identity field: a calc row's `as_of`/window date 158, the run's `as_of` 26, a year of one of those 25, a fact's period end 16, a fiscal year 8, a numeric method parameter 8, a series point's period 4, a passage's period/form 3 | **254** |
| an evidence id (becomes a link) | 60 |
| a ledger value, exact or at display precision | 16 |
| unresolved | **17** |

The 17: eight ISO dates that ARE on a related row but not in a field the
replay gathered — a drawdown episode's peak/trough/recovery dates, an
issuer's latest report period as `describe` prints it; seven window
parameters written as words ("30-day", "1y", "3y", "52-week", "VaR 95");
two confidence levels ("95%"). Each is a field of the Fact that carries
the figure (`window`, `params.confidence`, an episode fact's dates), none
is a pattern over prose. **No token in 229 accepted answers needs a
lexical exemption**, which is what §6.2 assumed and is now measured.

Identity fields a Fact carries, from this: `as_of`; `window` (`{name}` |
`{days}` | `{months}` | `{start, end}`); `period` for a series point; a
fact's `fiscal_year`/`fiscal_quarter` and its filing's `form` (in `params`
for a filed figure); `params.confidence`, `params.benchmark`; an episode
fact's `peak`, `trough`, `recovery` dates in `params`. G3's
`identity_tokens(fact)` reads exactly these.

## §10 What the model sees — one turn, after the cutover

```
tool result   {"facts": [{"id": "f_3a…", "kind": "scalar", "subject": "MSFT",
                          "measure": "issuer_exposures.weight", "unit": "RATIO",
                          "value": 0.1634, "as_of": "2026-08-31", "group": "concentration",
                          "source": "run_1d6e…"}, …],
               "note": {"run_id": "run_1d6e…", "as_of": "2026-08-31"}}

respond       {"blocks": [{"type": "paragraph",
                           "runs": ["MSFT is the largest position at ", {"fact": "f_3a…"},
                                    " against a warning level of ", {"fact": "f_3b…"}, "."]},
                          {"type": "table", "rows": [["f_3a…", "f_3b…"], ["f_4a…", "f_4b…"]]}]}

accepted      runs filled with the facts' model form + display; a prose digit
              the model wrote anyway ("16.3%") arrives as
              {"link": ["f_3a…"], "as_written": "16.3%"} or the turn was refused
```

## §11 Cutover and what is left behind

- **Sessions open across the cutover.** Their earlier steps hold
  declarations, not Facts; the ledger ignores them. The first V24 turn in
  such a session reads afresh; a pointer at an old id is `not_on_ledger`
  with the standard fix. Sessions are short and the desk is single-user in
  practice; no migration of old declarations (that would be the namer
  running one last time — the thing being removed).
- **Stored answers** (`agent_messages.meta.blocks`, `issuer_briefs.blocks`)
  render as they were; nothing is rewritten.
- **The daily report** (`report_agent`, `report_verification`,
  `numeric_verification`) keeps its V3 gate. Out of scope; recorded.
- **MCP clients outside the loops** see the new result shape on the same
  faces; the MCP_PLAN's contract ("what a loop sees is a tools list and a
  call verb") is unchanged.
- **Deploy**: api / mcp / worker / web rebuilt together (the result shape
  crosses the mcp↔api boundary); `v24_facts.sql` applied to the live DB
  before the rebuild, as `v23_budget_per_message.sql` was.

## §12 What is measured, before and after

| | V23-R (now) | V24 (built, before the live rounds) |
|---|---|---|
| lines on the gate path | ~2,600 (answer_blocks, resolver, table, quantities, resources, display_names, display_conventions, arg_validation, batch) | 1,585 (facts 175, fact_adapters 620, ledger 250, gate 240, answer 300) — `quantities.py` no longer on it |
| lexical rules in the gate | 5 regexes, 9 exempt classes | 1 token finder (in answer.py), 0 exempt classes; the gate compiles whitespace and quote marks only |
| kind vocabularies | 3 | 1 (`Fact.kind`) |
| block types | 6 | 3 |
| places a new kind of truth is taught | 6 | 2 (an adapter branch, a renderer case) |
| encodings of one figure to the model | 2 | 1 |
| offline tests | 1,832 | 1,994 |
| battery: verified figures / refusals / turns lost / so_what | 325 / 14 / 2 / 10 | (measured, F.2) |
| `unsourced_figure` per 31 turns | — | (measured, F.4) |
| §7 replay: refused responds that would now resolve | — | (measured, F) |

## §13 Risks named

1. **Fact volume.** A run is 235 quantities; `describe(run)` today shows
   them by name in 7k characters; as Facts with identity they are larger.
   Phase 0 measures; the answer is caps with `held_back`, never a fact cut.
2. **Identity-token drift.** G3's field lookups can grow into a list the
   way the exemptions did. The guard is procedural: a token class is added
   only when phase 0's replay or a live round shows an accepted-today
   sentence that needs it, and it is a field on the Fact, not a pattern
   over prose.
3. **Ambiguous value links.** A value shared by many facts links to all;
   if the list is long (a threshold on every check row), the chooser is
   noisy. Mitigation is in the adapter: a threshold that is one policy
   figure is one Fact with several subjects in `params`, not one Fact per
   row.
4. **The model writing prose digits more, not less**, now that they can
   pass. F.4 measures it; the refusal text and `_SYSTEM` say the id form is
   the one that always passes.
5. **The daily report path** keeps the old gate; two gates exist until it
   is moved. Recorded in §11, not solved here.
