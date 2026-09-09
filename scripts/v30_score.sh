#!/usr/bin/env bash
# V30 — score one battery output: gold + structure (free), counters (free),
# then the judge on the three criteria that stay judged, N replicates.
#   scripts/v30_score.sh docs/spikes/v30/V24_C1.json v24 [replicates]
set -u
cd /home/ubuntu/exposure-workbench
IN="$1"; SET="$2"; N="${3:-3}"
PY=.venv/bin/python
Q=tests/battery/criteria_conversations_${SET}.json; [ -f "$Q" ] || Q=tests/battery/criteria_${SET}.json
G=tests/battery/gold_${SET}.json
base="${IN%.json}"
$PY scripts/rubric_battery.py "$IN" --questions "$Q" --gold "$G" --out "${base}_struct.json" > "${base}_struct.log" 2>&1
$PY scripts/battery_counters.py "$IN" --json "${base}_counters.json" > "${base}_counters.log" 2>&1
if [ "$N" -gt 0 ]; then
  $PY scripts/rubric_battery.py "$IN" --questions "$Q" --gold "$G" --semantic --replicates "$N" \
     --criteria so_what,follows_on,honest_absence --out "${base}_judged.json" > "${base}_judged.log" 2>&1
fi
echo "scored $IN -> ${base}_{struct,counters,judged}"
grep -E "figures_present|TOTAL" "${base}_struct.log" | tail -2
grep -E "so_what|follows_on|honest_absence" "${base}_judged.log" 2>/dev/null | tail -3
