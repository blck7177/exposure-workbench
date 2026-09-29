#!/usr/bin/env bash
# V30 Phase 0 — the frozen fixture the battery measures against.
#
# The battery used to run against the production book (desk-for-one.com is this
# machine), where the battery's own `start` calls and the scheduler both changed
# "latest run" mid-run (X26, V29 §5b). A measurement on a desk that moves is not
# a measurement. So the battery gets a database of its own, restored from one
# snapshot before every run, and a tool face of its own bound to that database.
#
#   scripts/battery_fixture.sh snapshot            dump production -> backups/battery/<date>.sql.gz
#   scripts/battery_fixture.sh restore [file]      drop + create exposure_battery from the snapshot
#   scripts/battery_fixture.sh serve               local MCP face on :8105 over exposure_battery (background)
#   scripts/battery_fixture.sh worker              a worker over exposure_battery (background): scenario books get their run
#   scripts/battery_fixture.sh stop                stop that face, and the worker if one runs
#   scripts/battery_fixture.sh status
#
# Nothing here touches exposure_workbench (production) except `snapshot`, which
# only reads it. The fixture face is a plain uvicorn on the venv, not a
# container: it serves the code in the working tree, which is what a battery
# under development measures. Production containers are untouched.
#
# THE FIXTURE'S CLOCK IS STOPPED (V2E_mini, 2026-09-29). The production workers are bound to
# the production database, so on the fixture a `scenario`'s run stayed pending for ever and
# Q13/Q14/Q15 and two of the cross-family conversations could not reach their end. `worker`
# runs the same worker code over the fixture — but a worker also ticks the scheduler, and the
# snapshot's one schedule (port_001, overdue since 2026-09-14) would have re-run the book on
# the first tick and moved the latest run under the battery (X26, V29 §5b). So `restore`
# deactivates every schedule and fails any task the snapshot left pending, and the round denies
# `start` (a frozen desk neither prepares issuers off EDGAR nor re-runs its books); what the
# worker then completes is exactly what the round's own `scenario` calls enqueued — new books,
# new rows, the latest run of the real book untouched.
set -euo pipefail
cd "$(dirname "$0")/.."

DEST=/home/ubuntu/backups/battery
DB="${BATTERY_DB:-exposure_battery}"        # BATTERY_DB=exposure_gold serves the gold snapshot instead
PORT="${BATTERY_MCP_PORT:-8105}"
PIDFILE=/tmp/battery_mcp_${PORT}.pid
LOG=/tmp/battery_mcp_${PORT}.log
WPIDFILE=/tmp/battery_worker_${PORT}.pid          # the worker is named by the face it serves beside
WLOG=/tmp/battery_worker_${PORT}.log
PY=.venv/bin/python

# The production connection strings, from .env, with the database name swapped.
owner_url() { grep -E '^DATABASE_URL_LOCAL=' .env | cut -d= -f2- | sed "s#/exposure_workbench#/$DB#"; }
app_url()   { grep -E '^DATABASE_URL_LOCAL=' .env | cut -d= -f2- | sed -E "s#://[^:]+:[^@]+@#://app_rls:app_rls_pw@#; s#/exposure_workbench#/$DB#"; }

case "${1:-}" in
  snapshot)
    mkdir -p "$DEST"
    OUT="$DEST/battery-$(date -u +%F).sql.gz"
    docker exec -i exposure-postgres pg_dump -U exposure exposure_workbench | gzip > "$OUT.partial"
    gzip -t "$OUT.partial" && mv "$OUT.partial" "$OUT"
    echo "snapshot: $OUT ($(du -h "$OUT" | cut -f1))"
    ;;
  restore)
    FILE="${2:-$(ls -t "$DEST"/battery-*.sql.gz | head -1)}"
    [ -f "$FILE" ] || { echo "no snapshot at $FILE" >&2; exit 2; }
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "fixture face is running; stop it first" >&2; exit 2
    fi
    if [ -f "$WPIDFILE" ] && kill -0 "$(cat "$WPIDFILE")" 2>/dev/null; then
      echo "fixture worker is running; stop it first" >&2; exit 2
    fi
    # nobody may hold the fixture open across a restore: a gold derivation or a
    # stray psql would make DROP DATABASE fail and the battery measure a stale book
    docker exec exposure-postgres psql -U exposure -d postgres -q -c \
      "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid <> pg_backend_pid()" > /dev/null
    docker exec exposure-postgres psql -U exposure -d postgres -q -c "DROP DATABASE IF EXISTS $DB" \
      -c "CREATE DATABASE $DB OWNER exposure"
    gunzip -c "$FILE" | docker exec -i exposure-postgres psql -U exposure -d "$DB" -q -v ON_ERROR_STOP=0 \
      2>&1 | grep -v "^$" | grep -iv "setval\|set_config\|^ *[0-9-]* *$\|^(1 row)$" || true
    docker exec exposure-postgres psql -U exposure -d "$DB" -Atc \
      "select 'restored '||(select count(*) from exposure_runs)||' runs, latest '||(select max(as_of_date) from exposure_runs)||', '||(select count(*) from agent_steps)||' steps, '||(select count(*) from pg_policies)||' policies'"
    # the clock stops here: no schedule fires, nothing the snapshot left pending is picked up
    docker exec exposure-postgres psql -U exposure -d "$DB" -Atc \
      "with s as (update schedules set is_active = false where is_active returning 1),
            t as (update tasks set status = 'failed', completed_at = now(),
                    error_message = 'frozen fixture: pending in the snapshot, not run by the battery'
                  where status = 'pending' returning 1)
       select 'clock stopped: '||(select count(*) from s)||' schedule(s) deactivated, '||(select count(*) from t)||' pending task(s) from the snapshot failed'"
    ;;
  serve)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already serving (pid $(cat "$PIDFILE"))"; exit 0
    fi
    DATABASE_URL="$(owner_url)" DATABASE_URL_APP="$(app_url)" PYTHONPATH=src:. \
      nohup $PY -m uvicorn apps.mcp.http:app --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    for i in $(seq 1 30); do
      if curl -sf "http://127.0.0.1:$PORT/healthz" > /dev/null 2>&1; then
        echo "fixture face up on :$PORT over $DB (pid $(cat "$PIDFILE"), log $LOG)"; exit 0
      fi
      sleep 1
    done
    echo "fixture face did not come up; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1
    ;;
  worker)
    if [ -f "$WPIDFILE" ] && kill -0 "$(cat "$WPIDFILE")" 2>/dev/null; then
      echo "worker already running (pid $(cat "$WPIDFILE"))"; exit 0
    fi
    # the same worker the containers run, over the fixture; MCP_URL points at the fixture face
    # for the one task type that would mint a bearer (issuer_research), which the round never enqueues
    DATABASE_URL="$(owner_url)" DATABASE_URL_APP="$(app_url)" MCP_URL="http://127.0.0.1:$PORT" \
      WORKER_POLL_INTERVAL=1 PYTHONPATH=src:. \
      nohup $PY -m apps.worker.worker > "$WLOG" 2>&1 &
    echo $! > "$WPIDFILE"
    for i in $(seq 1 30); do
      if grep -q "Worker started" "$WLOG" 2>/dev/null; then
        echo "fixture worker up over $DB (pid $(cat "$WPIDFILE"), log $WLOG)"; exit 0
      fi
      if ! kill -0 "$(cat "$WPIDFILE")" 2>/dev/null; then break; fi
      sleep 1
    done
    echo "fixture worker did not come up; see $WLOG" >&2; tail -20 "$WLOG" >&2; rm -f "$WPIDFILE"; exit 1
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; echo "stopped"; else echo "not running"; fi
    if [ -f "$WPIDFILE" ]; then kill "$(cat "$WPIDFILE")" 2>/dev/null || true; rm -f "$WPIDFILE"; echo "worker stopped"; fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "serving on :$PORT (pid $(cat "$PIDFILE"))"; else echo "not serving"; fi
    if [ -f "$WPIDFILE" ] && kill -0 "$(cat "$WPIDFILE")" 2>/dev/null; then echo "worker running (pid $(cat "$WPIDFILE"))"; else echo "no worker"; fi
    docker exec exposure-postgres psql -U exposure -d postgres -Atc "select 'fixture db: '||count(*) from pg_database where datname='$DB'"
    ;;
  *) echo "usage: $0 snapshot|restore [file]|serve|worker|stop|status" >&2; exit 2 ;;
esac
