#!/usr/bin/env bash
# V7-D9 — nightly dump of the one thing that cannot be rebuilt.
#
# Almost everything in this database is derived: filings, facts, prices, chunks
# and the calc ledger can all be ingested again from EDGAR and yfinance. What
# cannot is what a user typed — their portfolios and positions — plus the
# conversation and run history that makes an answer traceable.
#
# It dumps everything anyway. Measured 2026-08-22: 27 MB compressed, which is
# mostly filing_chunks' embeddings, so seven of these are ~190 MB against 12 GB
# free. A selective dump would be smaller and would also be a list of table
# names that goes stale the first time someone adds one — and the table it
# would then be missing is the one nobody notices until a restore.
#
# Deliberately NOT off-machine. This survives a bad migration, a dropped table
# and a wrong DELETE, which are the failures that actually happen here; it does
# not survive losing the disk, and pretending otherwise would be worse than
# saying so. Off-site is a decision with a cost, and it has not been taken.
set -euo pipefail

DEST="${BACKUP_DIR:-/home/ubuntu/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
STAMP="$(date -u +%F)"
OUT="$DEST/ew-$STAMP.sql.gz"

mkdir -p "$DEST"

# Write to a temporary name and move it into place only on success. A dump
# interrupted half way through is a file that looks like a backup, and the
# moment anyone needs it is the worst moment to find out it is truncated.
TMP="$OUT.partial"
docker exec -i exposure-postgres pg_dump -U exposure exposure_workbench | gzip > "$TMP"
gzip -t "$TMP"
mv "$TMP" "$OUT"

# Prune AFTER a successful write, never before: pruning first would mean a run
# that then fails leaves one fewer backup than it started with.
find "$DEST" -name 'ew-*.sql.gz' -mtime "+$KEEP_DAYS" -delete

echo "$(date -u +%FT%TZ) backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
