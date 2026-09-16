#!/usr/bin/env bash
# The same 20 questions on gpt-5.6-sol, beside round C (gpt-5.4-mini), on a fixture
# of its own (exposure_battery_sol, face :8106) so round C's database stays readable.
set -uo pipefail
cd /home/ubuntu/exposure-workbench
SP=/tmp/claude-1000/-home-ubuntu/ce8a74cd-10b7-4f2e-811d-51da772d0f79/scratchpad
MODEL=gpt-5.6-sol
TAG=V37C_sol
export BATTERY_DB=exposure_battery_sol BATTERY_MCP_PORT=8106
D=docs/spikes/v37
LOG=$D/${TAG}_run.log
PY=.venv/bin/python
say() { echo "$@" | tee -a "$LOG"; }

say "=== ROUND C on $MODEL — run by the user's instruction of 2026-09-16 (\"并行用 5.6 sol再跑一次20题，对比和5.4 mini的结果\") ==="
say "same questions, snapshot, concurrency and deny as round C; own fixture $BATTERY_DB and face :$BATTERY_MCP_PORT"
say "model swap and reasoning_effort=none are applied by $SP/battery_with_model.py (see its docstring); the tree is not touched"
say ""
say "=== FREEZE $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'; } 2>&1 | tee -a "$LOG"
[ "$(git rev-parse HEAD)" = b79354fe9256f1f5d5ab6b51dc04f20b30c7e6cb ] || { say "HEAD moved; not measuring"; exit 4; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { say "tracked changes present; not measuring"; exit 4; }
say "--- offline baseline ---"
timeout 400 $PY -m pytest -m "not live" -q -p no:cacheprovider 2>&1 | tail -1 | tee -a "$LOG"

say ""
say "=== RESTORE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh stop 2>&1 | tee -a "$LOG"
scripts/battery_fixture.sh restore /home/ubuntu/backups/battery/battery-2026-09-13.sql.gz 2>&1 | tee -a "$LOG"
for m in v36_actor v36_analyst_reports; do
  docker exec -i exposure-postgres psql -U exposure -d "$BATTERY_DB" -q -v ON_ERROR_STOP=1 < infra/migrations/$m.sql 2>&1 | tee -a "$LOG"
done
docker exec exposure-postgres psql -U exposure -d "$BATTERY_DB" -Atc \
  "select 'analyst_reports '||count(*)||' rows; actor column '||(select count(*) from information_schema.columns where table_name='agent_steps' and column_name='actor') from analyst_reports" 2>&1 | tee -a "$LOG"

say ""
say "=== FACE $(date -u +%FT%T+00:00) ==="
scripts/battery_fixture.sh serve 2>&1 | tee -a "$LOG" || exit 5
sleep 2
grep -E "mcp mount /mcp/meta" /tmp/battery_mcp_${BATTERY_MCP_PORT}.log | tail -1 | tee -a "$LOG"

say ""
say "=== ROUND $(date -u +%FT%T+00:00) ==="
say "cmd: battery_with_model $MODEL questions_v33.json ${TAG}.json --fixture --concurrency 5 --deny submit_brief"
BATTERY_OWNER_ID=user_3IDBMeAxLTbecvGorzwV7FCeroR $PY $SP/battery_with_model.py $MODEL \
  docs/spikes/v33/questions_v33.json $D/${TAG}.json --fixture --concurrency 5 --deny submit_brief 2>&1 | tee -a "$LOG"

say ""
say "=== FORENSICS $(date -u +%FT%T+00:00) ==="
$PY scripts/v36_forensics.py $D/${TAG}.json --db "$BATTERY_DB" --out $D/${TAG}_forensics.txt --samples $D/${TAG}_schema.md 2>&1 | tee -a "$LOG"
$PY scripts/battery_counters.py $D/${TAG}.json --json $D/${TAG}_counters.json > $D/${TAG}_counters.txt 2>&1
say "counters: $D/${TAG}_counters.txt"
$PY $SP/v37c_audit.py $D/${TAG}.json --db "$BATTERY_DB" --answers $D/${TAG}_answers.txt --audit $D/${TAG}_audit.txt 2>&1 | tee -a "$LOG"
grep -oE "  (ANSWERED|EXHAUSTED|ERROR|EMPTY|GATE:[a-z_]+)$" $D/${TAG}_answers.txt | sort | uniq -c | tee -a "$LOG"
say "--- which model served the completions ---"
ids=$($PY -c "import json;print(','.join(\"'\"+c['session_id']+\"'\" for c in json.load(open('$D/${TAG}.json'))))")
docker exec exposure-postgres psql -U exposure -d "$BATTERY_DB" -Atc \
  "select split_part(result_summary, ':', 1), count(*) from agent_steps where step_type='llm_call' and session_id in ($ids) group by 1" 2>&1 | tee -a "$LOG"

say ""
say "=== FREEZE CHECK $(date -u +%FT%T+00:00) ==="
{ git rev-parse HEAD; git rev-parse 'HEAD^{tree}'
  echo "--- tracked changes (must be empty) ---"; git status --porcelain --untracked-files=no
  echo "--- src tests scripts newer than the HEAD commit (must be empty) ---"
  find src tests scripts -newermt "$(git log -1 --format=%cI HEAD)" -type f -not -path '*/__pycache__/*'; } 2>&1 | tee -a "$LOG"
say "=== DONE $(date -u +%FT%T+00:00) ==="
