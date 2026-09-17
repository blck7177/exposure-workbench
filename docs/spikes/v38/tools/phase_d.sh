#!/usr/bin/env bash
# V38 round D in one go, under the same conditions as rounds A, B and C:
# credit preflight -> freeze -> stop/restore/migrate/serve -> 20 questions ->
# communication tables, counters, answers, audit -> freeze check.
# Nothing under src/ tests/ scripts/ is written; round artefacts go to docs/spikes/v38/.
# NOT RUN by V38: round D waits on the model decision (the A-R1 fix to the
# meta_agent repair branch landed 9/17). The one step added to round C's procedure is the v5 remap after
# the restore (V38/S3: the snapshot predates the two debt-and-lease lines).
set -uo pipefail
cd /home/ubuntu/exposure-workbench
TOOLS=docs/spikes/v37/tools
TAG="${1:-V38D}"
D=docs/spikes/v38
LOG=$D/${TAG}_run.log
PY=.venv/bin/python
mkdir -p $D

say() { echo "$@" | tee -a "$LOG"; }

say ""
say "=== PREFLIGHT $(date -u +%FT%T+00:00) ==="
$PY $TOOLS/credit_probe.py 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] || { say "preflight exit $rc: not running the round"; exit "$rc"; }

say ""
say "=== FREEZE $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'; git log -1 --format='HEAD commit time %cI'; } 2>&1 | tee -a "$LOG"
dirty=$(git status --porcelain --untracked-files=no)
if [ -n "$dirty" ]; then say "tracked changes present, refusing to measure:"; say "$dirty"; exit 4; fi
say "--- offline baseline ---"
timeout 400 $PY -m pytest -m "not live" -q -p no:cacheprovider 2>&1 | tail -1 | tee -a "$LOG"

say ""
say "=== RESTORE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh stop 2>&1 | tee -a "$LOG"
scripts/battery_fixture.sh restore /home/ubuntu/backups/battery/battery-2026-09-13.sql.gz 2>&1 | tee -a "$LOG"
say "--- migrations ---"
for m in v36_actor v36_analyst_reports; do
  docker exec -i exposure-postgres psql -U exposure -d exposure_battery -q -v ON_ERROR_STOP=1 < infra/migrations/$m.sql 2>&1 | tee -a "$LOG"
done
docker exec exposure-postgres psql -U exposure -d exposure_battery -Atc \
  "select 'analyst_reports '||count(*)||' rows; actor column '||(select count(*) from information_schema.columns where table_name='agent_steps' and column_name='actor') from analyst_reports" 2>&1 | tee -a "$LOG"
say "--- concept remap (mapping v5, V38/S3) ---"
$PY scripts/remap_concepts.py --apply --db exposure_battery 2>&1 | tee -a "$LOG"
$PY scripts/unmapped_family_concepts.py --db exposure_battery 2>&1 | tee -a "$LOG"

say ""
say "=== FACE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh serve 2>&1 | tee -a "$LOG" || exit 5
sleep 2
grep -E "mcp mount /mcp/meta" /tmp/battery_mcp_8105.log | tail -1 | tee -a "$LOG"

say ""
say "=== ROUND D $(date -u +%FT%T+00:00) ==="
say "cmd: conversation_battery questions_v33.json ${TAG}.json --fixture --concurrency 5 --deny submit_brief"
BATTERY_OWNER_ID=user_3IDBMeAxLTbecvGorzwV7FCeroR $PY scripts/conversation_battery.py \
  docs/spikes/v33/questions_v33.json $D/${TAG}.json --fixture --concurrency 5 --deny submit_brief 2>&1 | tee -a "$LOG"

say ""
say "=== FORENSICS $(date -u +%FT%T+00:00) ==="
$PY scripts/v36_forensics.py $D/${TAG}.json --db exposure_battery --out $D/${TAG}_forensics.txt --samples $D/${TAG}_schema.md 2>&1 | tee -a "$LOG"
$PY scripts/battery_counters.py $D/${TAG}.json --json $D/${TAG}_counters.json > $D/${TAG}_counters.txt 2>&1
say "counters: $D/${TAG}_counters.txt"
$PY $TOOLS/v37c_audit.py $D/${TAG}.json --db exposure_battery --answers $D/${TAG}_answers.txt --audit $D/${TAG}_audit.txt 2>&1 | tee -a "$LOG"
grep -oE "  (ANSWERED|EXHAUSTED|ERROR|EMPTY|GATE:[a-z_]+)$" $D/${TAG}_answers.txt | sort | uniq -c | tee -a "$LOG"

say ""
say "=== FREEZE CHECK $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'
  echo "--- tracked changes (must be empty) ---"; git status --porcelain --untracked-files=no
  echo "--- src tests scripts newer than the HEAD commit (must be empty) ---"
  find src tests scripts -newermt "$(git log -1 --format=%cI HEAD)" -type f -not -path '*/__pycache__/*'
  echo "--- untracked ---"; git status --porcelain | grep '^??'; } 2>&1 | tee -a "$LOG"
say "=== DONE $(date -u +%FT%T+00:00) ==="
