#!/usr/bin/env bash
# V30 Phase 0 — the baseline, measured under instrument conditions.
#
#   frozen fixture restored before every set (scripts/battery_fixture.sh)
#   serial; `start` off the face; every tool call through the fixture face
#   two replicates of identical code (mini), then V21+V24 on a stronger model (D4)
#
# Outputs docs/spikes/v30/<SET>_<LABEL>.json and run_<set>_<label>.log.
set -u
cd /home/ubuntu/exposure-workbench
OWNER=user_3IDBMeAxLTbecvGorzwV7FCeroR
OUT=docs/spikes/v30
PY=.venv/bin/python
FX=scripts/battery_fixture.sh

run_set() {   # run_set <set> <label> [OPENAI_MODEL]
  local s="$1" label="$2" model="${3:-}"
  echo "### $(date -u +%FT%TZ) $s $label ${model:-mini}"
  env ${model:+OPENAI_MODEL=$model} $PY scripts/conversation_battery.py \
      "tests/battery/conversations_${s}.json" "$OUT/${s^^}_${label}.json" \
      --owner "$OWNER" --concurrency 1 --fixture > "$OUT/run_${s}_${label}.log" 2>&1
  echo "### exit=$?  turns=$(grep -c 'calls=' "$OUT/run_${s}_${label}.log" || true)  exceptions=$(grep -c 'Traceback\|ExceptionGroup' "$OUT/run_${s}_${label}.log" || true)"
}
fresh() { $FX stop >/dev/null; $FX restore | tail -1; $FX serve | tail -1; }

for R in 1 2; do
  fresh
  for s in v26 v21 v24; do run_set "$s" "R$R"; done
done
fresh
for s in v21 v24; do run_set "$s" "S55" gpt-5.5; done
$FX stop
echo "### $(date -u +%FT%TZ) all done"
