#!/usr/bin/env bash
# V1 round E (plan step 7) in one go, under the conditions of rounds A–C:
# credit preflight -> freeze -> stop/restore/migrate/serve -> the twenty questions ->
# the cross-family series -> communication tables, counters, answers, audit -> freeze check.
# Nothing under src/ tests/ scripts/ is written; round artefacts go to docs/spikes/v1/.
#
# ONE ARM PER RUN. The model is the round's variable (plan step 7): the arm is named by TAG and
# its models by the battery's own variables, which survive `.env`:
#
#   LEAD_MODEL=<strong> ANALYST_MODEL=<weak> docs/spikes/v1/tools/phase_e.sh V1E_lead_strong
#   LEAD_MODEL=<weak> ANALYST_MODEL=<strong> docs/spikes/v1/tools/phase_e.sh V1E_analysts_strong
#
# Every arm restores the same snapshot first, so the arms start from one book.
#
# TWO SERIES, TWO FILES. ${TAG}.json is the twenty questions of rounds A–C and nothing else, so it
# reads against V37C question for question. ${TAG}_X.json is docs/spikes/v1/questions_cross_family
# .json: eight conversations whose second half depends on what the first half FOUND, asked after
# the twenty on the same fixture (a scenario's book and a `start`'s task are new rows; neither moves
# the latest run the series reads).
#
# First run 2026-09-29 as V2E_mini (docs/spikes/v1/ACCEPTANCE_V2E_mini.md). The procedure is
# phase_d.sh's, which was itself never run; the steps added to it: the v39 and v40 migrations, and
# after that round a worker over the fixture (battery_fixture.sh worker) so a scenario's book gets
# its run, with `start` denied — the frozen desk neither prepares issuers nor re-runs its books, so
# what the worker completes is the round's own scenario books and nothing that moves the latest run.
set -uo pipefail
cd /home/ubuntu/exposure-workbench
TOOLS=docs/spikes/v37/tools
TAG="${1:-V1E}"
D=docs/spikes/v1
LOG=$D/${TAG}_run.log
PY=.venv/bin/python
OWNER=user_3IDBMeAxLTbecvGorzwV7FCeroR
SNAPSHOT=/home/ubuntu/backups/battery/battery-2026-09-13.sql.gz
CROSS=$D/questions_cross_family.json
mkdir -p $D

say() { echo "$@" | tee -a "$LOG"; }

say ""
say "=== PREFLIGHT $(date -u +%FT%T+00:00) ==="
say "arm: $TAG  models: OPENAI_MODEL=${OPENAI_MODEL:-(.env)} LEAD_MODEL=${LEAD_MODEL:-=} ANALYST_MODEL=${ANALYST_MODEL:-=}"
$PY $TOOLS/credit_probe.py 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] || { say "preflight exit $rc: not running the round"; exit "$rc"; }

say ""
say "=== FREEZE $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'; git log -1 --format='HEAD commit time %cI'; git describe --always --dirty; } 2>&1 | tee -a "$LOG"
dirty=$(git status --porcelain --untracked-files=no)
if [ -n "$dirty" ]; then say "tracked changes present, refusing to measure:"; say "$dirty"; exit 4; fi
say "--- offline baseline ---"
timeout 400 $PY -m pytest -m "not live" -q -p no:cacheprovider 2>&1 | tail -1 | tee -a "$LOG"
say "--- the wording sheet is the wording the round runs on ---"
$PY scripts/v1_wording.py --check 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -eq 0 ] || { say "docs/WORDING_V1.md is stale: not measuring wording nobody has read"; exit 4; }

say ""
say "=== RESTORE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh stop 2>&1 | tee -a "$LOG"
scripts/battery_fixture.sh restore "$SNAPSHOT" 2>&1 | tee -a "$LOG"
say "--- migrations ---"
for m in v36_actor v36_analyst_reports v39_fact_means v40_analysis_state; do
  docker exec -i exposure-postgres psql -U exposure -d exposure_battery -q -v ON_ERROR_STOP=1 < infra/migrations/$m.sql 2>&1 | tee -a "$LOG"
done
docker exec exposure-postgres psql -U exposure -d exposure_battery -Atc \
  "select 'analyst_reports '||count(*)||' rows; actor column '||(select count(*) from information_schema.columns where table_name='agent_steps' and column_name='actor')||'; facts.means '||(select count(*) from information_schema.columns where table_name='facts' and column_name='means') from analyst_reports" 2>&1 | tee -a "$LOG"
say "--- concept remap (mapping v5, V38/S3) ---"
$PY scripts/remap_concepts.py --apply --db exposure_battery 2>&1 | tee -a "$LOG"
$PY scripts/unmapped_family_concepts.py --db exposure_battery 2>&1 | tee -a "$LOG"

say ""
say "=== FACE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh serve 2>&1 | tee -a "$LOG" || exit 5
sleep 2
grep -E "mcp mount /mcp/" /tmp/battery_mcp_8105.log | tail -5 | tee -a "$LOG"
say "--- the worker: a scenario's book gets its run; nothing else is enqueued with start denied ---"
scripts/battery_fixture.sh worker 2>&1 | tee -a "$LOG" || exit 5

say ""
say "=== ROUND E, the twenty $(date -u +%FT%T+00:00) ==="
say "cmd: conversation_battery questions_v33.json ${TAG}.json --fixture --concurrency 5 --deny submit_brief --deny start"
BATTERY_OWNER_ID=$OWNER $PY scripts/conversation_battery.py \
  docs/spikes/v33/questions_v33.json $D/${TAG}.json --fixture --concurrency 5 --deny submit_brief --deny start 2>&1 | tee -a "$LOG"

say ""
say "=== ROUND E, the cross-family series $(date -u +%FT%T+00:00) ==="
say "cmd: conversation_battery questions_cross_family.json ${TAG}_X.json --fixture --concurrency 4 --deny submit_brief --deny start"
BATTERY_OWNER_ID=$OWNER $PY scripts/conversation_battery.py \
  $CROSS $D/${TAG}_X.json --fixture --concurrency 4 --deny submit_brief --deny start 2>&1 | tee -a "$LOG"

say ""
say "=== FORENSICS $(date -u +%FT%T+00:00) ==="
for S in "" "_X"; do
  $PY scripts/v36_forensics.py $D/${TAG}${S}.json --db exposure_battery --out $D/${TAG}${S}_forensics.txt --samples $D/${TAG}${S}_schema.md 2>&1 | tee -a "$LOG"
  $PY $TOOLS/v37c_audit.py $D/${TAG}${S}.json --db exposure_battery --answers $D/${TAG}${S}_answers.txt --audit $D/${TAG}${S}_audit.txt 2>&1 | tee -a "$LOG"
  grep -oE "  (ANSWERED|EXHAUSTED|ERROR|EMPTY|GATE:[a-z_]+)$" $D/${TAG}${S}_answers.txt | sort | uniq -c | tee -a "$LOG"
done
$PY scripts/battery_counters.py $D/${TAG}.json --json $D/${TAG}_counters.json > $D/${TAG}_counters.txt 2>&1
$PY scripts/battery_counters.py $D/${TAG}_X.json --questions $CROSS --json $D/${TAG}_X_counters.json > $D/${TAG}_X_counters.txt 2>&1
say "counters: $D/${TAG}_counters.txt  $D/${TAG}_X_counters.txt"
say "--- what became of each handoff the series was written to need ---"
sed -n '/^by shape/,/^refusals by class/p' $D/${TAG}_X_counters.txt | grep -v "^refusals by class" | tee -a "$LOG"

say ""
say "=== FREEZE CHECK $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'
  echo "--- tracked changes (must be empty) ---"; git status --porcelain --untracked-files=no
  echo "--- src tests scripts newer than the HEAD commit (must be empty) ---"
  find src tests scripts -newermt "$(git log -1 --format=%cI HEAD)" -type f -not -path '*/__pycache__/*'
  echo "--- untracked ---"; git status --porcelain | grep '^??'; } 2>&1 | tee -a "$LOG"
say "=== DONE $(date -u +%FT%T+00:00) ==="
