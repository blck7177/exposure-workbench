# Production

What is actually enforced when strangers can register, where each rule is
enforced, and how to check it is still true. Five sections; each says **where the
choke point is**, **which class of mistake it removes**, and **how to verify**.

The shape of the argument matters more than the individual mechanisms: every one
of these is a single place that a whole class of error has to pass through. A
rule spread over seven call sites is a rule that will eventually be enforced at
six.

---

## 1. Identity

**Choke point.** `src/exposure_workbench/auth/clerk.py` verifies the token;
`apps/api/auth_deps.py` turns it into a user. Two dependencies, `require_user`
and `optional_user`, are the only places in the codebase that decide who someone
is. Registration, email verification, OAuth and password policy are Clerk's
problem, not ours.

**Removes.** Hand-rolled session handling, and auth checks that drift apart
between routes. A write route either depends on `require_user` or it is
unauthenticated — there is no third state to get wrong.

`verify_token` pins RS256 and checks issuer and authorized party. The algorithm
pin is not decoration: a token signed HS256 using the public key as the HMAC
secret is the classic confusion attack, and `tests/test_auth_clerk.py` forges one
by hand to prove it is rejected.

**Verify.**

```bash
# every write route is gated
grep -rn "@router.post\|@router.put\|@router.patch" apps/api/routes/ | wc -l
grep -rn "require_user" apps/api/routes/ | wc -l          # must cover them all
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://<host>/api/agent/sessions   # 401
```

**Operational note.** `CLERK_AUTHORIZED_PARTIES` must list the production origin.
Miss it and every authenticated write returns 401 while the anonymous demo keeps
working perfectly — a failure that looks like "auth is broken for everyone" and
is really one missing string.

---

## 2. Tenant isolation

**Choke point.** Postgres row-level security. The runtime connects as `app_rls`,
a non-owner role, so policies bind; `db/session.py`'s `after_begin` listener
turns the request's user into a transaction-local `app.user_id` at the start of
every transaction — one injection point covering the API, the agent loop and the
worker alike. Unset means `current_setting` returns NULL, which shows only
`is_public` rows. Fail-closed.

**Removes.** "I forgot the `WHERE owner_id = ...`". Application-layer filters
are allowed only as business semantics and must be labelled
`# semantic, not security`; the database is what actually decides.

Three rules learned the hard way, all now guarded by
`tests/test_rls_parity.py`:

- **Both halves of a policy must cover every write.** ORM writes are
  `INSERT ... RETURNING`, and Postgres applies the SELECT policy (`USING`) to the
  returned row — so patching only `WITH CHECK` still fails, with an error whose
  text reads exactly like a `WITH CHECK` failure.
- **A view over an RLS table needs `security_invoker`.** Without it the view runs
  with its definer's privileges and reads straight past every policy. Two cost
  views did this until V2-E0; an unset tenant saw 0 rows in `agent_sessions` and
  all 20 in `session_cost`.
- **`app_rls` has no DELETE.** Append-only is enforced at the grant layer, not by
  convention. It also means nothing in the runtime can clean up after a failure,
  which is why the reaper marks records failed rather than removing them.

**Verify.**

```bash
# as the runtime role with no tenant: only public rows
docker exec -e PGPASSWORD=app_rls_pw exposure-postgres \
  psql -U app_rls -d exposure_workbench -c \
  "SELECT count(*) FROM portfolios;"        # the demo only
.venv/bin/python -m pytest -m live -k tenancy
```

---

## 3. Concurrency

Two leases, both on the same principle: pick a generous value and let expiry heal
it. **Nothing renews either one** — no heartbeat, no background thread. The worst
case is a dead thing occupying a slot for a while; there is no case where a live
thing has its slot taken.

**Worker (`tasks.lease_until`).** Stamped from the server clock at claim. A past
value on a running task means the worker holding it died, and the reaper in the
worker's poll loop settles it. Re-delivery is a **whitelist**, not the default,
because the handlers are not alike: `company_readiness` and `market_data_sync`
are upserts end to end and go back on the queue; `exposure_update` and
`issuer_research` are failed outright, because replaying them means either an
IntegrityError against `UNIQUE(run_id...)` or a second full LLM bill before the
collision is even detected. Failing loudly is also what releases the
`ActiveRunExists` deadlock that used to lock a user out of one company forever.

The reaper is two transactions on purpose. Phase 1 is one batch UPDATE with no
tenant (`tasks` has no RLS). Phase 2 marks each run failed under that task's own
tenant, one short transaction each — a WITH CHECK violation aborts whatever
transaction it lands in, so batching them would let one bad row kill every reap,
every cycle.

**Agent (`agent_sessions.turn_started_at`).** One in-flight turn per session,
claimed by a conditional UPDATE. Released in a `finally`, because the error paths
are the ones that must still release.

**Removes.** Stuck runs, double-processed tasks, and interleaved writes from two
browser tabs sharing a session id.

**Verify.**

```bash
docker compose up -d --scale exposure-worker=2
# enqueue several runs; each task must be completed by exactly one worker
docker exec exposure-postgres psql -U exposure -d exposure_workbench -c \
  "SELECT worker_id, count(*) FROM tasks WHERE type='exposure_update' GROUP BY 1;"
# takeover drill: cut TASK_LEASE_SECONDS, docker rm -f the holding container
```

---

## 4. Budget

**Choke points — exactly two.** `task_service.create_task` covers every enqueued
action (four REST routes and three agent delegation tools, which are parallel
implementations sharing no other code), and `POST /agent/sessions/{id}/messages`
covers chat.

The unit is a **user action** — one chat turn, one research run — not tokens and
not tool calls. That choice is what makes two charge points sufficient. Counting
tool calls would have to live in the tool wrapper, which cannot see the REST
routes at all.

Every action is charged twice in one transaction: the user's pool, then the
shared `_global` backstop. Either refusal rolls both back, so the counters cannot
drift and **there is no refund path anywhere** — a property, not an omission.

`usage_daily` deliberately has **no RLS**. The backstop must count across
tenants; any `user_id = current_setting(...)` policy would quietly reduce it to
counting only the caller, which is a fail-*open* backstop and worse than none.

Defaults are per user per UTC day: 10 chat turns, 3 research runs, 10 readiness,
20 exposure runs, 10 market syncs, plus 5 portfolio creates, 10 position uploads
and 5 agent sessions; the global pools are 200/30/100/200/50 and 100/100/100. All
env-overridable — the last three only since V7-Q, which found them declared in
settings and absent from compose, i.e. unreachable without editing the file.
The quota env belongs on **api and mcp**: those are the two processes that reach a
charge point (routes, and the delegation tools that run inside the MCP server).
The worker reaches none — it executes work that was already paid for at enqueue. The tool budgets are a different, orthogonal layer — they bound
one conversation, these bound one day — and since V3-B2 they run on two tracks:
**15 tool calls per TURN** for a conversation (reset when the turn is claimed,
which is what an over-long answer runs into) and **40 per SESSION** as the
lifetime ceiling, which is the only track a research run and the MCP host are on.
External search stays a sub-budget of 5 per session — and since V19 a chat session is one too, because `search_external_research` is on the meta face.

`QUOTA_UNLIMITED_USERS` (V7-Q) is a comma-separated list of user ids exempt from
the **refusal** — never from the count. Both rows are still written, so
`/api/me/usage`, the cost audit and the `_global` backstop keep reading the truth,
and `/api/me/usage` reports `unlimited: true` for those pools rather than a limit
the caller is already past. It exists so the operator can exercise the deployment
users actually get. Two consequences to hold on to:

  * an exempted tester **can exhaust the global pool for everyone else**, because
    the platform really did spend that;
  * with a name in this list, that account has **no ceiling** on this side. The
    provider-side monthly cap is the only thing under it — set one.

**Removes.** The unbounded bill. A refusal happens at the gate, before any
provider call: measured at 14ms.

**Verify.**

```bash
curl -sS -H "Authorization: Bearer $TOKEN" https://<host>/api/me/usage
docker exec exposure-postgres psql -U exposure -d exposure_workbench -c \
  "SELECT * FROM usage_daily WHERE day = CURRENT_DATE ORDER BY user_id;"
```

Watch the `_global` row. It is the number that tells you whether the site as a
whole is being drained, and it is the one a per-user view would never show you.

---

## 5. Audit

**Choke point.** The tool registry wrapper (`tools/registry.py`) reserves budget,
records a trace step, and harvests evidence references around **every** tool call
— including rejected ones. Workflow steps write `workflow_events` on entry and
exit. Calculations write `calc_ledger`. None of this is optional at the call
site, because none of it is done at the call site.

**Removes.** An answer nobody can walk back. Every figure in a brief resolves to
the fact, chunk or calculation it came from, and the submit gate refuses a brief
containing a citation that does not resolve.

**Verify.**

```bash
docker exec exposure-postgres psql -U exposure -d exposure_workbench -c \
  "SELECT step_name, status, count(*) FROM workflow_events GROUP BY 1,2 ORDER BY 1;"
.venv/bin/python -m pytest -m live -k "registry_enforcement or submit_gate"
```

---

## Backups

`scripts/backup_db.sh`, nightly at 03:30 UTC from the host crontab, keeps seven
days in `/home/ubuntu/backups`. It dumps the whole database — measured 27 MB
compressed, mostly filing_chunks' embeddings — writes to a `.partial` name and
only moves it into place after `gzip -t` passes, because a dump interrupted half
way is a file that looks like a backup until the moment someone needs it.

What it protects against is a bad migration, a dropped table, a wrong DELETE.
**Not** losing the disk: the dumps sit on the same volume as the database. That
is a stated limit rather than an oversight — off-site storage is a decision with
a cost and it has not been taken. Almost everything here is re-ingestable from
EDGAR and yfinance anyway; what is not is what a user typed (portfolios,
positions) and the conversation and run history that makes an answer traceable.

Restore, for when it is needed and nobody is calm:

```bash
gunzip -c /home/ubuntu/backups/ew-YYYY-MM-DD.sql.gz \
  | docker exec -i exposure-postgres psql -U exposure -d exposure_workbench
```

## Deploying

```bash
cd ~/exposure-workbench
git pull

# production values, then rebuild — NEXT_PUBLIC_* is inlined at BUILD time, so
# changing .env under a running container does nothing at all
#   NEXT_PUBLIC_API_URL=            (empty: same origin behind the proxy)
#   CORS_ORIGINS=                   (nothing cross-origin left to allow)
#   CLERK_AUTHORIZED_PARTIES=https://exposure.<domain>
docker compose build

# Schema BEFORE the new code sees the database. All of them are idempotent
# and safe to re-run in full, but the order is not optional: every V3 column is
# read by V3 code, so an API that starts first answers 500 on the agent routes
# until the ALTERs land. Bring postgres up alone, migrate, then start the rest.
#
# v4_cost.sql is the one file that DROPs. Its three issuer_briefs columns have
# no writer and no reader (V4-S2), so running it against the old code is
# harmless — which is why it still belongs before `up -d` with the others,
# rather than being the exception someone has to remember.
#
# v5_price_convention.sql adds factor_prices.adj_close and leaves it NULL on
# purpose. The first exposure run after the deploy re-ingests factor prices and
# fills it; until then the attribution step fails with a message naming the
# tickers, which is the intended state — a backfill of `close` into `adj_close`
# would assert that unadjusted history had been adjusted.
#
# v6_report_gate.sql adds issuer_exposures.contribution and does not backfill it
# either: the value is derivable from stored columns only when every holding
# priced on both days, so a computed backfill would write a silently wrong number
# into an old run. NULL reads as "this run did not record it".
#
# v8_skill_reads.sql adds the regression's own record (alpha, residual, model R²,
# observations, window, VIF, collinearity, attribution date) to exposure_metrics
# and does not backfill either, for the third time and the same reason: a run
# that never recorded the window it was fitted over does not acquire one by
# being asked later. The next run fills them; until then the read tools report
# the absence rather than a guess.
#
# v13_run_errors.sql adds error_code/error_detail to both run tables and does not
# backfill, for the fourth time and the same reason: a run that never recorded
# what KIND of failure it had does not acquire one by being asked later, and
# guessing a code from the old error_message text is exactly the string-matching
# V13 replaced. NULL reads as "this run did not record it", and the UI answers
# with its generic sentence rather than a claim about a cause it does not have.
#
# v15_calc_unit.sql adds calc_ledger.unit_class and does not backfill: every
# typed producer already states the unit in params.result_type, the gate reads
# that for older rows, and a row that stated neither is one whose unit nobody
# recorded — which is what NULL says.
#
# v13_users_ack.sql adds users.disclaimer_acknowledged_at and does not backfill:
# an account that existed before the column genuinely has not acknowledged
# anything, and the bar shows until the person does.
#
# v15_brief_blocks.sql adds issuer_briefs.blocks and does not backfill: a brief
# written through the prose gate has no blocks, and its text columns stay what
# they were — the page renders the prose path for it, and says nothing it did
# not have.
#
# v15_window_return_unit.sql DOES backfill, and says which rows: calc_ledger
# rows whose operation is portfolio.window_return and whose unit_class is NULL
# become RATIO. That is not a guess about a unit nobody recorded — a window
# return is a ratio by construction, the writer now says so on every new row,
# and the transitional operation-name table never learned this op, so the old
# rows were typed MONEY and a stated "-11.95%" could not meet the -0.1195 they
# hold.
#
# v13_limit_checks_values.sql records what each mandate check measured, and does
# not backfill for the fifth time. Recomputing from today's risk_limits rows
# would be worse than a guess — the thresholds may have been edited since — and
# would put a number that was never checked under a badge saying it was.
docker compose up -d postgres
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v2_multiuser.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v3_harness.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v4_cost.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v5_price_convention.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v6_report_gate.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v8_skill_reads.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v13_run_errors.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v13_limit_checks_values.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v13_users_ack.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v15_calc_unit.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v15_brief_blocks.sql
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v15_window_return_unit.sql

# v17_multiple_unit.sql is the one file that UPDATEs rows, and the exception is
# narrower than it looks: it changes how 326 existing figures are READ, not what
# any of them is. money / money is a RATIO to the unit algebra and always will
# be — net margin and debt/EBITDA are the same operation on the same units — so
# only the registry can say which of the two a named measure is, and until V17
# it had no way to. Every coverage, turnover and leverage ratio on this desk was
# therefore printed by the percent rule: 2.30 as "230.0%", a current ratio of
# 1.85 as "185.0%", an OLS beta of -0.543 as "-54.3%".
#
# No value, operand, basis, period or input ref is touched, which is why this is
# not a rewrite of an append-only ledger: a row whose VALUE changed would be a
# new row, and there is none here. It corrects both the unit_class column (what
# the table and the reader read) and params.result_type.unit_class (what the
# calculator reads when the row becomes an operand) — leaving one behind would
# be the two-rules-about-one-fact that v15_calc_unit.sql exists to end.
#
# Safe before the new code and safe to re-run: it matches on the eight names the
# registry declares, and a second run matches nothing.
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v17_multiple_unit.sql

# V16 has no schema migration — mapping v4 is code plus a data backfill.
# remap_concepts re-normalizes financial_facts under the current mapping
# (v4 names the per-share and capital-allocation layer: 2,472 rows went
# NULL -> named on 2026-09-01, no renames). Idempotent; --dry-run first.
python scripts/remap_concepts.py --dry-run
python scripts/remap_concepts.py --apply

docker compose up -d

# proxy: see infra/Caddyfile.example. DNS must resolve BEFORE reloading Caddy.
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

Smoke list, run from a different machine:

| Check | Expected |
|---|---|
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/portfolios` anonymous | the public demo, nothing else |
| `POST /api/agent/sessions` anonymous | 401 |
| page source contains `localhost:8103` | no occurrences |
| sign up → clone demo → upload CSV → run → chat | all succeed |

### What is deliberately not here

No Kubernetes, no message broker, no separate cache tier. One box, four
containers, a reverse proxy. Every mechanism above is a single well-placed
constraint rather than a piece of infrastructure, which is the whole argument:
the interesting part of "production-ready" is where the boundaries are, not how
much of it there is.

### Erasing an account

`app_rls` holds no DELETE grant, so erasure cannot be reached from the running
system at all — no route, no agent tool, no button. It is an operational act
performed as the table owner, and `scripts/delete_user.py` is its only shape.

Order matters. **Clerk first**: it is the identity system of record, and while
the Clerk user exists one sign-in re-upserts the `users` row under the same id
and quietly undoes the erasure. `--apply` therefore refuses without
`--clerk-deleted`, which is an assertion by the operator rather than a check.

```
# 1. delete the user in the Clerk dashboard
# 2. see what would go
python scripts/delete_user.py user_2abc...
# 3. do it
python scripts/delete_user.py user_2abc... --apply --clerk-deleted
```

Four guards reject the whole invocation before anything is written: the demo
sentinel and the `_global` quota row are refused outright; an id that owns
nothing is refused rather than reported as a success; and work still in flight
is refused, because a live worker holds that tenant's context and would write
rows back after the commit. The dry run is the default.

What survives, deliberately: every shared company table, and the two pointers
into the departed account that `calc_ledger.invoked_by` and
`research_sources.research_run_id` hold. Those are left dangling. Rewriting them
to a tombstone would be the first mutation ever made to an append-only evidence
store, and dangling ids already exist there.

Running it twice ends in the "owns nothing" refusal, which is correct: from
inside the script, "already erased" and "you typed the wrong id" are the same
case, and only one of the two is safe to treat as success.

Covered by `tests/test_account_deletion_live.py` (33 cases): every owned table
empty, the other tenant bit-for-bit unchanged, shared evidence and its dangling
pointers intact, and each guard refusing without writing.

### Known limits

V3 added five, and they are limits of the verification layer rather than of the
service — worth knowing precisely because the layer above them is now strong
enough that people will trust it.

- **Numeric verification is an existence check, not a correctness check.** It
  proves a number appears in the evidence cited for it. It cannot prove the
  number answers the question asked: swapping two real figures within one answer,
  both drawn from the same citation, passes.
- **Citations to prose are checked scale-blind.** A `chunk_`/`src_` citation is
  verified by whether the number appears in the passage as written — a percent
  claim needs a percent, which is what stops short digit strings matching by
  coincidence — but not by magnitude, because a filing table's scale usually sits
  in a header the chunk does not carry.
- ~~**Per-portfolio risk limits are loaded, passed, and never read.**~~ Closed in
  V2-H4. `check_limits` reads the portfolio's `risk_limits` rows through a
  `LimitBook` and there is no other source: `limits_config`, `db_limits` and the
  16 literals in the cfg() closure are deleted, and so is
  `configs/risk_limits.yaml`. A missing required row fails the run at step 3, in
  the same raise as a stale price. The demo rerun that proved it gained one
  alert — LLY at 0.13809 against its own 0.12, previously discarded in favour of
  the 0.15 default.
- **No constraint judges whether a threshold is SENSIBLE for its check.**
  `ck_risk_limits_levels` excludes the two mechanical own-goals (a non-positive
  warning; tiers that coincide or invert, both of which kill the warning tier
  because breach is tested first). It cannot exclude `breach_level = 9.99` on
  `daily_loss`, which satisfies every constraint and can never fire. A ceiling
  would have to be per-check — `gross_exposure` legitimately sits above 1.0 —
  and a per-check ceiling is threshold numbers back in the schema, the fourth
  source of truth V2-H4 removed. The limits endpoint displays such a row; no
  code judges it.
- **A check that did not run looks the same as one that passed, in the UI.**
  Every check sits behind a guard on its input, and one short-history holding
  truncates the whole return series through `pivot.ffill().dropna()`, so
  `var_95`, `expected_shortfall_95` and `rolling_volatility_30d` silently do not
  run while the timeline says step 8 completed and the page reads "all limits
  within bounds". The run now records which checks it evaluated in the
  `check_limits` event's `payload_summary`; nothing surfaces it yet.
- **Two evidence-ingestion paths remain open.** The explicit `{type,id}` branch
  and the `calc_id`/`fact_id` key branch can still put an unciteable id into the
  trail. One malformed id from before V1's alert-prefix fix is in the live trail
  through the first of them.
- **MCP is on the older budget regime and is worse off than chat.** It never
  claims a turn, so a per-turn counter would never reset for it; it keeps the
  lifetime budget until it has a face of its own. *(V3-R6 made that sentence
  true. It described the intent, and the code inferred the regime from
  `kind="meta"` — so the MCP host was stamped with 15 tool calls that nothing
  ever reset. `create_session` now takes `per_turn` explicitly.)*
- **The context pre-check will rarely fire.** It cannot see a session's first
  turn, and a full turn measures in the low thousands of tokens against an
  80,000 limit. The provider-side mapping is the one that would actually catch an
  overrun.

Carried from V2, unchanged:

Each of these is a decision, not an oversight. They are here so that the next
person to touch this — including me — does not have to rediscover them.
- ~~**A portfolio's own risk limits do nothing.**~~ Closed in V2-H4: the
  `risk_limits` row is the only source of a threshold, and provisioning a
  portfolio without a complete set now raises instead of succeeding quietly.
- **Every exposure run calls the price provider once per holding.** That is the
  cost of `sync_prices`, and it is not separately rate-limited.
- **A quota-rejected delegation call is refunded its session tool budget.** The
  rollback that correctly discards the half charge also discards the reservation,
  so `tools_used` and `agent_steps` disagree for that session.
- **The "one active research run per company" guard is per-tenant.** It reads
  `research_runs`, which is owner-scoped by RLS, so N users can research the same
  issuer at once and pay for the same ingest N times. A shared advisory lock or a
  partial unique index would fix it; neither exists.
- **Factor prices sit outside `sync_prices` and `validate_inputs`.** Holdings are
  refreshed and checked for staleness; the factor ETFs behind the attribution
  step are not, so they can silently drift older.
- **A transient provider error in step 1 fails a run whose prices were already
  complete.** The step distinguishes "the provider has nothing for this symbol"
  from a hard failure, but not a network blip from a real outage.
- **There is no rate limiting.** The quota bounds what a signed-in user can spend
  and the reverse proxy bounds body size, but nothing bounds request *frequency*.
  For a demo behind a personal domain that is a considered trade; it would not be
  for anything larger.
