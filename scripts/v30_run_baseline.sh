#!/usr/bin/env bash
# V30 Phase 0 — the baseline, from a worktree pinned at HEAD (e6c290b), so the
# fixture face serves the code under measurement and not the working tree.
# R2 and R3 on mini are the clean replicate pair; S55 is V21+V24 on gpt-5.5 (D4).
set -u
BASE=/home/ubuntu/exposure-workbench-baseline
MAIN=/home/ubuntu/exposure-workbench
cd "$BASE"
OWNER=user_3IDBMeAxLTbecvGorzwV7FCeroR
OUT=$MAIN/docs/spikes/v30
PY=$MAIN/.venv/bin/python
FX=scripts/battery_fixture.sh
run_set() {
  local s="$1" label="$2" model="${3:-}"
  echo "### $(date -u +%FT%TZ) $s $label ${model:-mini} @ $(git log --oneline -1 | cut -c1-7)"
  env ${model:+OPENAI_MODEL=$model} $PY scripts/conversation_battery.py \
      "tests/battery/conversations_${s}.json" "$OUT/${s^^}_${label}.json" \
      --owner "$OWNER" --concurrency 1 --fixture > "$OUT/run_${s}_${label}.log" 2>&1
  echo "### exit=$?  turns=$(grep -c 'calls=' "$OUT/run_${s}_${label}.log" || true)  exceptions=$(grep -c 'Traceback\|ExceptionGroup' "$OUT/run_${s}_${label}.log" || true)"
}
fresh() { $FX stop >/dev/null; $FX restore | tail -1; $FX serve | tail -1; grep -o "mount /mcp/meta serving [0-9]* tools" /tmp/battery_mcp_8105.log | tail -1; }
for R in 2 3; do
  fresh
  for s in v26 v21 v24; do run_set "$s" "R$R"; done
done
fresh
for s in v21 v24; do run_set "$s" "S55" gpt-5.5; done
$FX stop
echo "### $(date -u +%FT%TZ) baseline done"
