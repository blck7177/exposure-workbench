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
20 exposure runs, 10 market syncs; the global pools are 200/30/100/200/50. All
env-overridable. The per-session budgets (40 tool calls, 5 external searches) are
a different, orthogonal layer — they bound one conversation, these bound one day.

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
docker compose up -d

# schema: idempotent, safe to re-run in full
docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
  -v ON_ERROR_STOP=1 < infra/migrations/v2_multiuser.sql

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

### Known limits

- **Account deletion has no path.** `app_rls` holds no DELETE grant by design, so
  removing a user's data requires an owner-role script that does not exist yet.
  Worth building before inviting anyone who is not a friend.
- **A portfolio's own risk limits do nothing.** `check_limits` takes a
  `db_limits` argument it never reads; only the YAML defaults fire. Either wire
  it up or delete the copy path — an interface that pretends to be configurable
  is worse than none.
- **Every exposure run now calls the price provider once per holding.** That is
  the cost of `sync_prices`, and it is not separately rate-limited.
