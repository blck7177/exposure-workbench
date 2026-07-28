# V2 — Multi-user & Production Coverage

Final acceptance for V2-A through V2-G: the work that takes a single-user demo to
something strangers can register on. Every figure below is from the live stack
against real Postgres, EDGAR, yfinance and Clerk — not fixtures.

Companion to [P9_COVERAGE.md](P9_COVERAGE.md), which covered the single-user
Issuer Intelligence MVP.

## Totals

| | |
|---|---|
| Offline tests | **191** (`pytest -m "not live"`) — 83 at P9, 113 entering V2-E |
| Live tests | **31** (`pytest -m live`) |
| Tables with RLS | **20**, one `tenant` policy each |
| Shared tables (no RLS, deliberately) | 13 — company evidence, `tasks`, `usage_daily` |
| `security_master` | 13,024 symbols |
| Commits in V2-E..G | 6, on `issuer-intelligence` |

Task types exercised end to end: `exposure_update` 15 completed / 2 failed,
`market_data_sync` 4 / 1, `issuer_research` 2 / 1, `company_readiness` **3 / 0**.
Every failure above is a deliberate acceptance case, not an accident.

## What each phase actually proved

### A — identity
Clerk verification with RS256 pinned. `tests/test_auth_clerk.py` forges an
HS256 token signed with the public key as the HMAC secret — the classic
algorithm-confusion attack — and asserts it is rejected.

### B — user portfolios
CSV upload is atomic: a bad row leaves zero rows written and returns per-row
reasons. Verified with a ticker outside the universe (422, no orphan portfolio).

### C — tenant isolation
Now a replayable suite (`tests/test_tenancy_live.py`, 11 cases) rather than the
hand-driven two-account walkthrough it started as. Connects as the non-owner
`app_rls` role, because reading as the owner proves nothing — the table owner
bypasses RLS entirely.

The claim tested is invisibility, not refusal: B's query for A's portfolio,
positions, runs, run children and messages returns **zero rows**, so there is no
existence oracle and nothing that has to remember to check. Also covered: an
unset tenant sees only `is_public` rows (fail-closed); a cross-tenant INSERT is
refused by `WITH CHECK`; a cross-tenant UPDATE matches nothing rather than
raising — a distinction that matters, since a service treating "0 rows updated"
as success would report a write that never happened; the runtime role cannot
DELETE at all; and 12 alternating A/B/anonymous transactions on a pooled
connection never leak, because `set_config(..., true)` is transaction-local.

### D — universe
13,024 symbols from the NASDAQ Trader listing files joined to SEC CIKs. Search
ranks exact ticker over prefix over name, and never auto-selects: "apple"
returns AAPL first *and* the distractors, because disambiguation is the user's
job.

### E0 — three prerequisites, each measured before being fixed

- **`workflow_events` was polymorphic over two parents, not three.**
  `company_readiness` logs under `run_id = task.id`, which matched neither, so
  its first step INSERT was denied. Measured before: **0** task-prefixed rows and
  **0** `company_readiness` rows in `tasks` of any status — the task type had
  never once completed through the worker since RLS was introduced. After: a real
  run completed with all 12 timeline events landing under its owner's tenant.
- **Two cost views read past RLS.** Measured: `app_rls` with no tenant saw 0 rows
  in `agent_sessions` and all 20 in `session_cost`. `security_invoker` fixed it;
  both now return 0.
- **The users upsert held a row lock for the whole request.** A concurrent
  request from the same user blocked in the auth dependency. The live test keeps
  a control that reproduces the block with the old write shape, so the fix is
  measured against something rather than asserted.

### E1 — worker lease
Two replicas, five runs: each task completed by exactly one worker, two distinct
workers participated, exactly one metrics row per run.

Takeover drill with the lease cut to 20s and the holding container removed
outright (`docker rm -f`, not `kill` — `restart: unless-stopped` would otherwise
resurrect it and make "the other worker took over" unprovable):

- `company_readiness` → requeued, `retry_count=1`, finished by the survivor
- `issuer_research` → task **and** run both failed with a lease-expired message,
  and that user could start the same company again immediately, which is the
  `ActiveRunExists` deadlock releasing

### E2/E3/E4 — turn lease and quota
- Two concurrent turns on one session: **409 in 0.023s** against the accepted
  turn's 1.59s. The pre-E0-3 symptom would have been a block that eventually
  returned 200, so the timing is the assertion.
- The refused turn was **not** charged: `used` went 0→1, not 0→2.
- Over quota: **429 in 14ms** carrying `{"error":"quota_exceeded","kind":
  "chat_turn","used":2,"limit":2,"resets_at":...}` — refused at the gate before
  any provider call, which is the entire point of a quota.
- The concurrency primitive was hammered directly: two callers racing for the
  last unit, exactly one wins.
- Unplanned but useful: the OpenAI key ran out of credit mid-acceptance, so every
  turn raised straight through `handle_message`. `turn_started_at` was still NULL
  afterwards — the `finally` release survived a real escaping exception rather
  than a simulated one.

### E5 — price freshness
Three cases, and they **cannot be merged**: step 1 pulls deleted history straight
back from the provider, so "delete some prices" can only ever demonstrate that
step 1 works and can never produce a red run.

| Case | Result |
|---|---|
| Deleted all 62 AAPL bars in the window, re-ran untouched | step 1 restored all 62; run green; MV $10,406,776 |
| A holding the provider has no bars for | run **red**, error names `ZZTESTX` and nothing else |
| `as_of` 30 days past the newest bar | run **red**, error lists all ten holdings with ages, not just the first |

The regression being closed: an unpriced holding used to be valued at $0 *and*
left in the denominator, so a two-name book reported the survivor at 100% instead
of 64.5% — enough to fabricate an issuer-concentration breach on a portfolio that
never breached. Three different missing-price conventions coexisted in one run;
all three are gone.

### F — deployment
Same-origin build verified by compiling the web image with an empty API base and
grepping the client bundle: **0 occurrences** of `localhost:8103`. All three
containers now publish on `127.0.0.1` only — Docker's published ports bypass ufw,
so the previous configuration had Postgres, credentials and all, listening on the
public internet.

### G — audit
`tests/test_v2_audit.py` turns the ownership table into executable invariants:
every declared table is explicitly tenant-scoped or explicitly shared (no third
state), every write route requires a user, every application-layer owner filter
carries the `semantic, not security` label, and providers never import upwards.

## Known gaps, carried forward deliberately

- **No account-deletion path.** `app_rls` holds no DELETE grant by design, so
  erasing a user needs an owner-role script that does not exist. Build it before
  inviting anyone who is not a friend.
- **A portfolio's own risk limits do nothing.** `check_limits` takes a
  `db_limits` argument it never reads; only the YAML defaults fire, while
  `_load_inputs` queries for them every run and new portfolios get a copied
  template. Wire it up or delete the copy path — a configurable-looking interface
  that is ignored is worse than none.
- **`owner_id NOT NULL` still deferred.** Ownerless rows are fail-closed, so this
  is safe, but it is a loose end.
- **Every exposure run now calls the price provider once per holding.** The cost
  of `sync_prices`; not separately rate-limited.
- **Clerk is still a development instance.** Fine at demo scale; a production
  instance needs its own DNS records and a key swap.
