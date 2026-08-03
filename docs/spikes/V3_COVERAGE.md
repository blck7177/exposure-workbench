# V3 — Harness Coverage (Verify / Context / Memory / Evals)

Final acceptance for the work that takes a multi-user demo to something whose
answers a finance desk can act on. Companion to
[V2_COVERAGE.md](V2_COVERAGE.md), which covered multi-user and production, and
[P9_COVERAGE.md](P9_COVERAGE.md), which covered the single-user MVP.

Every figure below is measured against the live stack and the real corpus —
the agent messages and issuer briefs this system has actually produced — not
against fixtures.

## Totals

| | V3 | after V3-R |
|---|---|---|
| Offline tests | 278 (`pytest -m "not live"`) — 215 entering V3 | **313** |
| Live tests | 89 — 70 entering V3 | **98** |
| Commits | 16, on `issuer-intelligence` | +7 |
| Diff | 48 files, +3,590 / −81 | +28 files, +1,215 / −82 |
| New columns | 5, one migration (`infra/migrations/v3_harness.sql`) | — |
| New agent tools | 4 (face 16 → 20) | — |
| Citable evidence prefixes | 6 | **7** (`pos_`) |

V3-R is the adversarial review's answer, not a second feature phase: it adds no
capability and decides whether what V3 built is real. See
[the section below](#adversarial-review-and-what-answering-it-cost).

## The problem V3 was for

The citation gate proved an id was real and said nothing about the number
standing next to it. Three more paths let unverified text reach a user, the
prompt was never measured, and four kinds of durable artefact — briefs, run
status, full holdings, two thirds of the calculation algebra — existed in the
database with no tool able to read them.

---

## A — Verify

### A0-1 A reply that states a number must cite

Zero citations used to skip validation entirely. Two of seven assistant
messages in the live database carry numbers today; both would have passed
untouched. Enforcement is in the gate, not the schema, because a required
`citations` field would also block the number-free replies (greetings,
clarifying questions) that are legitimately uncited.

### A0-2 Two ungated exits, not one

The plan named the raw-content substitution on the final turn. The commoner
path — the loop ending with no accepted `respond`, emitting "(no response
produced)" — was not named anywhere. Both now converge on one refusal carrying
`{"gate": "exhausted"}` in `agent_messages.meta`, rendered as a refusal by the
UI rather than as an answer.

The marker had to be a column. Encoding it in `role` would have been free and
would have broken the *next* turn of any session that ever failed a gate:
`_load_history` feeds `role` verbatim into the provider's messages array.

### A0-3 Two different holes in the trail

**Asymmetry.** Harvest recognised nine prefixes, the gate resolves six. The
live trail carries **23 `co_` refs and one `rrun_` ref** that could be
retrieved and never cited. Harvest is now exactly the gate's set, asserted as
`harvest == gate == resolver`.

**The fabricated-id loop.** `respond`'s rejection echoes the ids it just
refused under `problems[].id`, and the gate call *completes* — so the harvester
wrote invented ids into the trail, where they passed the trail check on the
retry and were copied into the run's evidence pack. A gate's output is never
harvested now.

Neither closes the `{type,id}` dict branch or the `calc_id` key branch. The
live trail proves it: a malformed `alertb41eec529430`, minted before V1 fixed
the alert prefix, is in `agent_steps.evidence_refs` right now via the dict
branch. Carried forward deliberately (see Known limits).

### A0-4 Seven settings declared, documented, never read

Two were named by the plan (`submit_brief_retries`, `respond_retries` — in
settings for two phases, asserted by a test, written up in MODULE_NOTES as an
implemented retry budget, read by nothing). Writing the structural guard found
five more, including an Anthropic key and model behind README's "Report Agent |
OpenAI / Anthropic (switchable)" — plumbed through compose and `.env.example`,
so an operator could set the key, restart, and watch nothing happen.

### A1 A number must match a value the cited evidence holds

Three properties, each replacing something the plan specified that measurement
rejected:

| Property | What the plan said | Why it changed |
|---|---|---|
| Unit classes | a five-way scaling family | one live `risk_alerts` row carries `current_value` 0.158, `limit_value` 0.15 and `utilization` 0.792 together, so the family accepts "at 15.8% of its limit" when the answer is 79.2% |
| Half an ulp of the written precision | `rtol=0.005` | too tight (0.04061908 written as the correct "4.1%" is 0.94% off → refused) *and* too loose ("$82.886B" opens a ±$414M window → a corrupted last digit accepted) |
| Nine exemption categories | four | a four-category set produced 8 guaranteed false rejections in seven live answers ("H200", "the S&P 500", "42.4% over the last 1 year") |

Resolution is a table asserted equal to the gate's prefix set. Two entries were
missing from the plan's design and both would have failed loudly: `run_`, which
resolves through `exposure_metrics` / `issuer_exposures` / `sector_exposures` /
`factor_attributions` because **`exposure_runs` has no numeric column at all**,
and `chunk_`/`src_`, which have no columns and take a prose route.

**The extractor was built against the corpus, and the corpus found four bugs no
invented example would have:**

| Bug | Consequence |
|---|---|
| scale alternation was case-sensitive | `$81.615B` read as eighty-one **dollars** — a claim about $81.6B verified against 81.6, with nothing anywhere looking wrong |
| the designator exemption swallowed the claim beside it | `AAPL 15.8%` has the same shape as `Microsoft 365`; **two of three real issuer weights** in a live answer were exempted, so any number after a ticker would have been accepted |
| the year pattern refused any year followed by a full stop | i.e. every year ending a sentence; two live brief blocks tripped it |
| a surface could end on the sentence's comma | the model quoted back a number it never wrote |

**A1c — the derived Q4.** A quarterly series computes Q4 = annual − Q1 − Q2 −
Q3, a value equal to no row: it carries four fact ids and each holds a different
number. Quoting it correctly and citing it correctly was unverifiable *by
construction*. Confirmed on the exact figure — MSFT FY2025 Q4 revenue is
**$76.441B**, which is what a live brief states; with the series ledgered it
verifies, citing only its four input facts it still fails.

---

## B — Context

**B0.** The count includes the tool schemas, which go to the provider on every
request and appear nowhere in `messages`: a bare system prompt plus schemas is
already **~2,300 tokens**. The peak within the turn is what is recorded, since
messages grow with every tool result.

`tiktoken` was an *inherited* dependency and fetches its BPE table over the
network on first use. Measured inside the running API container: **1.77s**, into
an ephemeral `/tmp`, with `TIKTOKEN_CACHE_DIR` unset — a request-path dependency
on outbound internet after every container start. Now declared, and baked into
the image at build time.

**B1.** 413 before the charge — a turn the server will not run must not cost a
quota unit. Two things pinned by test: the position in the sequence
(401 → 404 → 409 → **413** → 429), and the *absence* of `release_turn`. The
check sits inside the gate transaction, so raising rolls the claim back and
that rollback **is** the release; an explicit release would open a second
connection onto the row lock the first still holds, and it swallows every
exception, so the symptom would be a request hanging for ever with nothing
logged.

**B2.** The regime is carried by the row, not branched on in `reserve()`. Live
research sessions spend **32, 26 and 25** tool calls inside one session and
never claim a turn, so a per-turn counter shared with chat would kill every
issuer research run partway through. `session.tool_budget or default` also read
a stored 0 as "unset" — the one value you would reach for to switch a runaway
session off was the only value that did nothing.

**B3 (summarisation) is not built.** The plan made it conditional on B0's data
and the data says no: a full turn measures in the low thousands of tokens
against an 80,000 limit. Building compaction now would be a guess wearing an
implementation.

---

## C — Memory

Four tools closing four gaps of the same shape — work this system does, stored
durably, that no tool could reach.

| Tool | The gap |
|---|---|
| `read_issuer_brief` | the agent could spend a research quota unit commissioning a brief and had no way to read one |
| `get_task_status` | delegation returned an id that was a dead end |
| `get_portfolio_positions` | the snapshot carries the largest few names; quantity and asset_class it does not carry at all |
| `compute_combine` | `sub` was unreachable from every face, so free cash flow — this project's own worked example since M3 — could not be computed |

`brief_id` is returned as a plain string field, never as `{"type","id"}`: the
wrapper would harvest it, and it would pass the trail check and fail DB
existence with a misleading `unresolved_in_db`. A brief is a conclusion drawn
from evidence; citing one is a loop.

`get_task_status` carries the phase's one dangerous line. `Task.owner_user_id
== None` compiles to `IS NULL` and matches every ownerless seed task, so the
absence of a user is refused **before** the query rather than allowed to become
a filter matching the wrong rows.

Two corrections the live data forced: the demo book's newest position snapshot
is **2026-07-23** while its newest completed run is **2026-07-27**, so both
dates are reported rather than collapsed into one "as of"; and the plan's
acceptance ("ask for the 11th holding") was unsatisfiable, since `port_001` has
exactly ten holdings against a ten-name cap.

---

## D — Evals

### D1 Retrieval, measured for the first time

MODULE_NOTES M5 has said "检索质量实测后再议" since P3. The re-arguing never
happened because there was no number.

| Metric | Value |
|---|---|
| Queries | 24 (8 issuers × 3 intents) |
| recall@5 | **1.000** |
| precision@5 | **0.792** |
| precision@10 | **0.708** |

The first run's most useful output was not the score. **recall@5 came back
1.000 on all 24 queries** — not retrieval being perfect, but the metric being
too easy on a corpus where seven of every ten returned passages already sit in
the right item. A saturated metric cannot detect the regression it exists to
detect, so precision@k is what the regression test guards and recall@5 is kept
as a floor check.

Labels are SEC item codes, never chunk ids, which are regenerated by every
re-ingest. The chunker constants are pinned by a test because chunk boundaries
decide which item a passage reports.

### D2 Faithfulness of what has already been said

| | Chat | Briefs |
|---|---|---|
| Numbers stated | 29 → **32** after V3-R | 66 |
| Unverified | **1** | 14 |
| Citations checked | 22 → **25** | 244 |
| Citations that no longer resolve | **0** | **0** |
| Number-bearing answers with no citation | **0** | n/a |

Chat measured **0 of 20** when the numeric check first shipped, against the
plan's bar of 2 in 20. It is 1 of 29 now — 1 of 32 after V3-R's three acceptance
turns, all of which verify — and the one is a correct refusal that the V3
acceptance run itself produced (see Live acceptance below). The brief figures do
not move under V3-R: every extractor change in that phase was re-measured
against this corpus and none of them changed a single number, which for a set of
changes that only ever NARROW the extractor is the result to want.

The 14 brief refusals are enumerated, not averaged:

- **4** are the derived-Q4 class, closed by A1c for anything written afterwards
  but not retrofittable onto stored text;
- **1** is the rule working as designed — a brief writes 32.2% where the
  operating margin is 32.2753%, i.e. truncation rather than rounding, and the
  rule is that the true value must *round* to what was written;
- **9** are true catches: a `$58.3B` net income in a block citing revenue,
  gross profit and operating income but never net income; prior-year comparison
  figures cited to the current-year rows; and a "25% import tariff" whose two
  cited chunks contain neither "tariff" nor "H200" (see Live acceptance — that
  one was found by the gate refusing an answer, not by reading the brief).

It replays the stored corpus rather than generating fresh answers on purpose:
an answer produced after A1 has by construction already passed A1, so it can
only score 100%. No LLM judge — reaching for one before the deterministic
checks are exhausted means grading our own homework with a second, less
reliable copy of the thing being graded.

---

## Live acceptance — against the rebuilt stack, not the test suite

All four containers rebuilt and restarted on V3 code, migration already applied.

**The tiktoken bake works.** First `get_encoding` in a freshly started container:
**0.435s**, against **1.77s** measured before the bake, and with no network fetch
at all — the BPE table is now an image layer rather than something downloaded
into a container's `/tmp` after every restart.

**A real chat turn, end to end.** *"What is the demo portfolio total market value
and its largest issuer weight?"* answered in **4.9s** with
`$10,406,776` and `16.2%`, citing `run_0b2d88d81dc0`, and `meta.prompt_tokens`
5121. It passing at all is the acceptance: those numbers had to be resolved
through `exposure_metrics` and `issuer_exposures`, because the run row itself
holds no numbers, and a citation that resolved to nothing would have refused a
correct answer.

**A0-3 in production.** The `respond` step in that turn's trace recorded
`evidence_refs = 0`. Before V3 the gate's own output was harvested, so the
citations it was validating came back into the trail through it.

**B2 in production.** The session was created with `turn_tool_budget = 15` and
`tool_budget = 40`, and finished the turn at `turn_tools_used = 2`,
`tools_used = 2` — the enforced counter and the lifetime counter, both real.

**B1 in production, all three properties at once.** With
`CONTEXT_SOFT_LIMIT_TOKENS` lowered to 2000, the next turn on that session
returned **413** with `projected_tokens: 5127`; `usage_daily.used` for
`chat_turn` stayed at **1** across the refusal, so it was not charged; and
`agent_sessions.turn_started_at` came back **NULL** — the lease released by the
transaction rollback, with no `release_turn` call anywhere on that path.

**The acceptance run found a defect the tests could not.** Asked to summarise the
NVDA brief, the agent read it, was refused three times, and gave up with an
apology. Two things came out of that:

The refusal offered two ways forward — re-cite, or recompute — and neither can
conjure evidence that was never there. It now offers a third: leave the figure
out and answer with what is supportable. Re-run with that one sentence changed,
the same question produced a full, correctly cited summary in two attempts, and
the agent **dropped the `$58.3B` net income figure by itself** — the true catch
the brief had been carrying.

That answer then exposed a **false accept in the prose route**. It restated the
brief's claim that H200 shipments face "a 25% import tariff", citing two chunks
that contain neither "tariff" nor "H200" — and it passed, because the route
matched bare digits and "25" happens to occur in one of them (nine of that
chunk's seventeen digit keys are two characters or shorter). The route now
matches the number *as written*: a percent claim needs a percent in the passage.
The first attempt at a fix was a minimum digit length, and re-measuring rejected
it — it refused six legitimate figures like "revenue grew 17%" quoted straight
out of a filing. Written-form matching closes the hole and keeps those: brief
refusals went 13 → 19 under the length rule, and 13 → 14 under this one, the
extra one being the tariff claim itself.

Both temporary settings (the lowered limit, and the blanked `azp` needed to use
a browserless token) were restored afterwards and re-verified: the limit is back
to 80,000 and a token without an `azp` claim is refused again.

## 拍板点 1, re-argued on the measurement

The user approved **full-strict** numeric matching (a number must have come
from a tool) before the numbers existed. They now do, and the decision holds:
chat false-rejection is **0 of 20**, well inside the 2-in-20 bar, and of the 13
brief refusals only one (32.2% vs 32.2753%) is arguably harsh — and that one is
truncation, which is the behaviour the rule was chosen for. No exemption for
approximate forms is warranted on this evidence.

---

## V3-R live acceptance — the rebuilt stack, after the review fixes

API and worker images rebuilt on V3-R code and restarted; the migration's new
`pos_` backfill applied and re-applied (it matches nothing the second time).
Three turns through the real chat route, each chosen because it was impossible
or wrong before:

**A share count, cited to the holding.** *"How many shares of AAPL does the demo
portfolio hold?"* → **"holds 5,000 shares of AAPL (`pos_bb75f719df7a`)"**,
citing `pos_bb75f719df7a`, in **5.5s**. C3's own acceptance query, unanswerable
until this phase: the quantity had no citable id, so the gate refused the honest
answer. That the API accepted a `pos_` citation at all is also the proof that
the container is running the new code.

**A negative number, stated with its sign.** *"Which issuer had the worst daily
return in the latest run?"* → **"NVDA … at -4.994198%"**, citing
`run_01bf110e5e15`, in **1.5s**. Measured against that run's evidence both ways:
as written it verifies; read the way the pre-R1 extractor read it (as positive
4.994198%) it is **REFUSED**. This exact correct answer was impossible to state
yesterday.

**A refusal that stayed a refusal.** *"…and which factor contributed most
negatively to return?"* → the agent answered the drawdown (5.673757%, cited) and
said plainly that the factor breakdown **was not in the snapshot it fetched**
rather than producing a number. The tool surface genuinely has no factor
attribution reader; the gate's job here was to make inventing one impossible,
and the honest half-answer is what that looks like from the user's side.

The trail-poisoning sequence is asserted as a live test rather than a chat turn
— it needs the model to call two specific tools in one order, which is not
something to leave to a sampled turn.

`CLERK_AUTHORIZED_PARTIES` was blanked for the run (Backend-API tokens carry no
`azp`) and **restored and re-verified afterwards**: an azp-less token is refused
again with `bad_azp`.

## Adversarial review, and what answering it cost

Six dimensions were commissioned over the V3 diff. **Five were delivered; the
sixth — concurrency and budget interaction — was stopped on instruction**, so
the review's own coverage is 5/6 and the gap is named here rather than absorbed.

Every finding was **reproduced by hand before being believed**, and doing that
corrected one of them: the `think` echo poisons the trail only when the whole
thought IS an id, while a thought that merely begins with one writes a different
defect — an unresolvable, sentence-length "id" — into the audit trail. Both are
closed by the same rule, but the reproduction is what got the description right.

What survived reproduction: **2 blockers, 4 majors, 3 minors, and 5 defects in
the tests and documents** rather than in the system. All are fixed in V3-R
except those listed as deliberately not done, at the end.

### Blockers

**The sign axis did not exist.** `extract_numbers("-$81.615B")` returned
POSITIVE 81,615,000,000: the literal pattern begins at a digit, so a matched `-`
reached the surface and never the value. A sign flip therefore verified CLEAN
against the evidence it inverts — the one corruption a finance desk punishes
hardest — and, simultaneously, every negative in the database was uncitable:
**117 of 127 factor contributions**, 32 of 175 issuer daily returns, 4 of 18
portfolio P&L rows. A correct claim of "-0.98%" was compared against +0.0098 and
matched nothing.

**A tool that echoes its argument was evidence.** Harvest decided what counts as
evidence from a tool's class and status, when the property the trail needs is
that the value came back from a LOOKUP. `think` returns the thought;
`get_task_status` and `get_portfolio_positions` return the unknown id they were
given. A session that called two read tools with a real run id, retrieved
nothing, and cited that run PASSED — trail check, existence check, and then
every number on the run's children available to support an answer built on a run
it never read. Provenance is the trail's whole promise.

### Majors

- **"Your holdings are AAPL 5000, MSFT 3500." extracted to nothing**, so the
  citations-required gate had no numbers to demand evidence for and let it
  through uncited. The designator exemption asked only whether a capitalised
  word preceded the digits — the question "Microsoft 365" and "AAPL 5000" both
  answer yes to. Both halves of the verification layer, off at once, on the
  most ordinary portfolio question there is.
- **A share count could not be cited.** C3 shipped a tool that reads the whole
  book back, and its own acceptance query — "how many shares of AAPL do I hold"
  — was unanswerable: positions had no evidence identity, so the quantity had
  nothing to cite and A1 refused it by construction.
- **`open_questions` was never numerically checked.** It is the one brief block
  that carries no citations, and the check looped over the cited blocks, so a
  brief could ask "will capex stay above $23B?" with that figure in none of its
  evidence.
- **MCP ran on 15 tool calls per PROCESS.** B2 inferred the budget regime from
  `kind="meta"`, which the MCP host also uses; it never claims a turn, so
  nothing ever reset the counter — while two documents said it kept the lifetime
  budget.

### Minors

`.5%` read as `5%` (a silent factor of ten); `3 M&A deals` read as three
million; and the module docstring's headline example argued against the
implementation — it claimed unit classes stop "15.8% of its limit" when the
answer is 79.2%, which they do not, because 0.158 is one of the three values
that alert row holds. The test asserting it was named for a separation it does
not perform.

### Defects in the tests and documents, not in the system

- **The RLS tests proved nothing.** `brief_service.latest_visible` and
  `status_of("rrun_")` carry no owner filter and say RLS scopes them — asserted
  through the `exposure` connection, which has `rolbypassrls`. The assertions
  held with row-level security switched off entirely. Now run as `app_rls`, and
  re-run against the bypassing connection to confirm they go red.
- **A one-time migration sweep had no bound**, and migrations here are re-applied
  by hand on every deploy: a session an operator switched off by setting its
  budget to 0 came back on at the next deploy.
- **`read_issuer_brief` did not say whose brief it was**, though RLS shows a
  caller the public demo briefs too.
- **The full-book read was unbounded**, against a 6,000-character result
  summariser — a large book would be cut mid-JSON.
- Documents that had drifted from the code: the tool budget (15/turn + 40/session
  since B2, not "40 per conversation"), the MCP face size (16 trimmed from 20,
  not 12), and README's claim of an identical REST/MCP surface.

### Found while fixing, not by the review

- **The demo book's ten holdings were minted as bare `uuid4`.** Third occurrence
  of this bug class in the project (`alert<hex>` was the first). Rewritten in
  place by migration — `positions.id` is referenced by nothing — and the seed
  script now mints `pos_` like `new_id` does.
- **`date_long` was leaning on the designator pattern.** The mandatory corpus
  re-run showed three of the nine spans the old pattern exempted were dates, so
  narrowing it would have started refusing "for the quarter ended March 28". The
  rule that any extractor change re-runs the corpus paid for itself here.
- **`check_limits` ignores `db_limits` entirely.** Found while correcting a note
  that said the dead parameter had been closed in V2-H. The workflow loads
  per-portfolio `risk_limits` and passes them; the body never reads the name, so
  every alert comes from the global YAML and the demo book's twelve rows —
  several TIGHTER than the defaults — do nothing.
  *(Closed in V2-H4, after this review. The row is now the only source of a
  threshold and the demo book's LLY limit fires for the first time.)*

### Deliberately not done

| | Why |
|---|---|
| Accounting parentheses as negatives | Zero instances in the corpus, and reading them means telling `(135,441)` the negative from `(see note 3)` the aside |
| Tightening COUNT compatibility | A bare number claiming no unit is the design; changing it is a semantics decision, not a repair |
| Removing `think`'s echo | Closed at the harvest layer instead, which also covers the next echoing tool nobody has written yet |
| The sixth review dimension | Stopped on instruction; the risk it would have covered is recorded above |
| Honouring `db_limits` | Changes which alerts exist — a decision, not a repair. *Taken in V2-H4: the decision had already been pre-approved, and the deferral was mine.* |
| MCP face explicitness | Belongs to MCP_BOUNDARY_PLAN |

---

## Known limits, carried forward deliberately

- **Two evidence-ingestion paths remain open.** The `{type,id}` dict branch and
  the `calc_id`/`fact_id` key branch can still put an id into the trail that the
  gate cannot resolve. A malformed `alertb41eec529430` is in the live trail via
  the former; 10 of 35 `risk_alerts` rows carry ids without the underscore.
- **The prose route is scale-blind, and sign-blind.** `chunk_`/`src_` citations
  are checked by whether the digits appear verbatim in the passage, not by
  magnitude: a filing table's scale usually lives in a header the chunk does not
  carry, and it writes a negative as `(16,450)` at least as often as `-16,450`,
  so requiring the minus would refuse the ordinary case. Strictly narrower than
  the previous rule (any number with a citation attached), and strictly weaker
  than the structured route, which since V3-R1 checks the sign exactly.
- **A bare number may still meet any class.** A number written without a unit
  claims none, so COUNT compares against ratios, money and counts alike. That is
  the design and not an oversight; tightening it would refuse "the series
  returned 2 points", and it is recorded here because the review asked.
- ~~**Per-portfolio risk limits are loaded, passed, and never read.**~~ Closed
  in V2-H4. What replaced it in PRODUCTION's known limits is narrower and worth
  reading: no constraint judges whether a threshold is *sensible* for its check,
  and a check that did not run still looks like one that passed.
- **A1 is an existence check, not a correctness check.** It proves a number
  appears in the cited evidence. It cannot prove the number *answers the
  question* — cross-swapping two figures within one answer, both of which are
  real values from the same citation, is not detectable this way.
- **MCP regressed, not improved.** `claim_turn` has one caller (the chat
  route); `apps/mcp/server.py` reuses one process-global session that never
  claims a turn, so a per-turn counter would never reset for it. It stays on the
  lifetime regime until MCP_BOUNDARY_PLAN gives it a face of its own. The face
  guard pins the drift at exactly one entry. *(V3-R6: this was the intent and
  not the behaviour — the regime was inferred from `kind="meta"`, which the MCP
  host also uses, so it ran on 15 tool calls per process. `create_session(...,
  per_turn=False)` is now the way it is said.)*
- **B1's pre-check will realistically never fire.** It cannot see a session's
  first turn (no measurement to project from), and a full turn measures in the
  low thousands against an 80,000 limit. The provider-side mapping is what would
  actually catch an overrun.
- **The four new read tools spend the same per-turn budget** as everything else,
  so a question that reads a brief, checks a run and lists holdings costs three
  of fifteen.
- **Retrieval is measured at section level.** A run returning the right SEC item
  and the wrong paragraph scores as a hit. Passage-level labels need a human to
  read 3,078 chunks and are the next step if this number stops discriminating.
- Carried from V2 and untouched by V3: factor prices outside the freshness
  checks, no request-rate limiting, `owner_id NOT NULL` still deferred, Clerk
  still a development instance. (`check_limits`' dead `db_limits` argument was on
  this list until V2-H4 closed it.)
