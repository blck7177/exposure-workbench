#!/bin/bash
# V29 — one replicate of the battery under the X26 instrument conditions.
#
#   serial (concurrency 1)              a conversation must not read a run another one made
#   a fresh completed run already there  so no turn reaches for start()
#   every tool call through the CONTAINER (MCP_URL), not local code
#
# The run inventory is printed before and after: a battery that started a run
# was measuring its own wake, and the score of that replicate is not comparable.
set -u
cd /home/ubuntu/exposure-workbench
R="$1"                       # replicate label, e.g. 1 or 2
OWNER=user_3IDBMeAxLTbecvGorzwV7FCeroR
OUT=docs/spikes/v29
PY=.venv/bin/python
export MCP_URL=http://127.0.0.1:8104

inventory() {
  docker exec exposure-postgres psql -U exposure -d exposure_workbench -tAc \
    "SELECT count(*)||' runs, latest as_of '||max(as_of_date) FROM exposure_runs WHERE portfolio_id='port_001'"
}

echo "### replicate $R starts — book: $(inventory)"
for s in v26 v21 v24; do
  echo "### $s"
  $PY scripts/conversation_battery.py "tests/battery/conversations_${s}.json" \
      "$OUT/${s^^}_R${R}.json" --owner "$OWNER" --concurrency 1 \
      > "$OUT/run_${s}_r${R}.log" 2>&1
  code=$?
  answered=$(grep -c "calls=" "$OUT/run_${s}_r${R}.log" || true)
  failed=$(grep -c "ExceptionGroup\|Traceback" "$OUT/run_${s}_r${R}.log" || true)
  echo "### $s exit=$code  turns_logged=$answered  turns_with_an_exception=$failed"
done
echo "### replicate $R done — book: $(inventory)"
