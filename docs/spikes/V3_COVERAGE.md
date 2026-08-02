# V3 — Harness Coverage (Verify / Context / Memory / Evals)

Final acceptance for the work that takes a multi-user demo to something whose
answers a finance desk can act on. Companion to
[V2_COVERAGE.md](V2_COVERAGE.md), which covered multi-user and production, and
[P9_COVERAGE.md](P9_COVERAGE.md), which covered the single-user MVP.

Every figure below is measured against the live stack and the real corpus —
the agent messages and issuer briefs this system has actually produced — not
against fixtures.

## Totals

| | |
|---|---|
| Offline tests | **277** (`pytest -m "not live"`) — 215 entering V3 |
| Live tests | **89** — 70 entering V3 |
| Commits | 13, on `issuer-intelligence` |
| Diff | 48 files, +3,590 / −81 |
| New columns | 5, one migration (`infra/migrations/v3_harness.sql`) |
| New agent tools | 4 (face 16 → 20) |

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
| Numbers stated | 20 | 66 |
| Unverified | **0** | 13 |
| Citations checked | 8 | 244 |
| Citations that no longer resolve | **0** | **0** |
| Number-bearing answers with no citation | **0** | n/a |

Chat is 0 of 20 against the plan's acceptance bar of 2 in 20.

The 13 brief refusals are enumerated, not averaged:

- **4** are the derived-Q4 class, closed by A1c for anything written afterwards
  but not retrofittable onto stored text;
- **1** is the rule working as designed — a brief writes 32.2% where the
  operating margin is 32.2753%, i.e. truncation rather than rounding, and the
  rule is that the true value must *round* to what was written;
- **8** are true catches: a `$58.3B` net income in a block citing revenue,
  gross profit and operating income but never net income, and prior-year
  comparison figures cited to the current-year rows.

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

## Known limits, carried forward deliberately

- **Two evidence-ingestion paths remain open.** The `{type,id}` dict branch and
  the `calc_id`/`fact_id` key branch can still put an id into the trail that the
  gate cannot resolve. A malformed `alertb41eec529430` is in the live trail via
  the former; 10 of 35 `risk_alerts` rows carry ids without the underscore.
- **The prose route is scale-blind.** `chunk_`/`src_` citations are checked by
  whether the digits appear verbatim in the passage, not by magnitude: a filing
  table's scale usually lives in a header the chunk does not carry. Strictly
  narrower than the previous rule (any number with a citation attached), and
  strictly weaker than the structured route.
- **A1 is an existence check, not a correctness check.** It proves a number
  appears in the cited evidence. It cannot prove the number *answers the
  question* — cross-swapping two figures within one answer, both of which are
  real values from the same citation, is not detectable this way.
- **MCP regressed, not improved.** `claim_turn` has one caller (the chat
  route); `apps/mcp/server.py` reuses one process-global session that never
  claims a turn, so a per-turn counter would never reset for it. It stays on the
  lifetime regime until MCP_BOUNDARY_PLAN gives it a face of its own. The face
  guard pins the drift at exactly one entry.
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
- Carried from V2 and untouched by V3: `check_limits`' dead `db_limits`
  argument, factor prices outside the freshness checks, no request-rate limiting,
  `owner_id NOT NULL` still deferred, Clerk still a development instance.
