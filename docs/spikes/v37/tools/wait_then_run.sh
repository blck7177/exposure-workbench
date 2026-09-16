#!/usr/bin/env bash
# Wait for the OpenAI account to have credits again, then run Phase F once.
# Gives up after 24 h. Refuses to measure if HEAD moved off the pushed commit
# or the tree is dirty: a different tree is the user's call, not this loop's.
set -uo pipefail
cd /home/ubuntu/exposure-workbench
SP=/tmp/claude-1000/-home-ubuntu/ce8a74cd-10b7-4f2e-811d-51da772d0f79/scratchpad
EXPECT_HEAD=b79354fe9256f1f5d5ab6b51dc04f20b30c7e6cb
deadline=$(( $(date +%s) + 24*3600 ))
last=""
echo "waiting for credits from $(date -u +%FT%T+00:00), probing every 120 s"
while :; do
  out=$(.venv/bin/python $SP/credit_probe.py 2>&1); rc=$?
  state="rc=$rc ${out:0:60}"
  if [ "$state" != "$last" ]; then echo "$(date -u +%FT%T+00:00) $state"; last=$state; fi
  [ "$rc" -eq 0 ] && break
  if [ "$(date +%s)" -ge "$deadline" ]; then echo "gave up after 24 h without credits"; exit 3; fi
  sleep 120
done
head=$(git rev-parse HEAD)
if [ "$head" != "$EXPECT_HEAD" ]; then echo "HEAD moved to $head; not measuring without an instruction"; exit 4; fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then echo "tree is dirty; not measuring"; exit 4; fi
echo "credits back at $(date -u +%FT%T+00:00); running Phase F"
bash $SP/phase_f.sh V37C
echo "phase_f exit $?"
