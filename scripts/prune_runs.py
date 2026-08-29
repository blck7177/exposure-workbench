"""Remove runs the public demo should never have been showing. Owner role only.

WHAT THIS IS FOR. The shared demo book is the shop window: an anonymous visitor
sees its runs, and on 2026-08-29 five of the twenty were labelled
`v8-p-live-acceptance`, `v5_validation`, `v5_deploy_check`, `v2h4_verification`
and `seed`, while two more were failures — one of them naming a test symbol
(`ZZTESTX`) that does not exist. Every one of those is a note this desk wrote to
itself during development, standing on the page a stranger reads first.

WHY A SCRIPT AND NOT A ROUTE, and why nobody should "fix" that: app_rls holds no
DELETE grant anywhere (V2-C), which is the application's inability to delete
hardened at the permission layer rather than promised in a code review. Erasure
is an operational act carried out as the table owner and unreachable from the
running system. Same shape as delete_user.py, for the same reason.

WHAT IT DELETES. Whole exposure runs, chosen by `triggered_by`, on ONE portfolio
named on the command line. Nine child tables (metrics, sector/issuer exposures,
factor attributions and residuals, alerts, limit checks, stress results, daily
reports) carry ON DELETE CASCADE and go with the parent.

`workflow_events` does NOT. It is polymorphic — exposure runs and research runs
both write to it — so `infra/init.sql:414` deliberately gives run_id no foreign
key, and the row is deleted here explicitly. Note that `db/models.py:515`
declares a cascading ForeignKey to exposure_runs that the live database does not
have: the model asserts a constraint the schema refused, and anything relying on
the ORM to clean these up would leave them behind. That divergence is recorded
here rather than fixed here; it is not this script's batch.

WHAT IT LEAVES ALONE. The `tasks` row that produced the run: it is the queue's
own audit trail, it carries owner and payload, and nothing on any page reads it.
Evidence (calc_ledger, facts, chunks) is append-only and never touched — a run
id living on in `calc_ledger.invoked_by` is a dangling pointer of exactly the
kind delete_user.py already documents and keeps.

DELETING IS NOT ALWAYS THE ANSWER, and the live book is why. On 2026-08-29 the
newest run on port_001 — the only one carrying stress results, limit checks and
the regression's own metadata — is labelled `v8-p-live-acceptance`. It is a real
run of the real book against real prices; only its label is development
residue. Deleting it by label would leave the shop window showing July.

So the script offers both. --relabel rewrites `triggered_by` and touches nothing
else, which is the right move for a run whose only problem is what it called
itself; --apply deletes. Both take the same selection, so the operator sees
exactly the same list either way before choosing.

Dry run is the default and prints what would go. --apply requires naming the
portfolio again, because "which book" is the one thing a mistyped invocation
gets wrong in a way that cannot be undone.

Usage:
    python scripts/prune_runs.py port_001                       # dry run
    python scripts/prune_runs.py port_001 --relabel manual --confirm port_001
    python scripts/prune_runs.py port_001 --apply --confirm port_001
    python scripts/prune_runs.py port_001 --keep manual,seed    # widen the keep set
    python scripts/prune_runs.py port_001 --failed              # also take failed runs
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2

DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv("DATABASE_URL_SYNC",
              "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"),
)
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")

OWNER_ROLE = "exposure"

# What a run on a public book may legitimately say about who started it. Anything
# else is a label this desk wrote to itself. `agent:<session>` is deliberately
# NOT here: an agent-started run on the shared demo would be a real user's work
# and is not development residue — but no such run exists on port_001 today, and
# a keep-set that has to be argued about is one the operator should pass by hand.
DEFAULT_KEEP = ("manual", "scheduled", "seed")


def _rows(cur, sql: str, args: tuple = ()) -> list[tuple]:
    cur.execute(sql, args)
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("portfolio_id", help="the book to prune, e.g. port_001")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--relabel", default=None, metavar="VALUE",
                    help="rewrite triggered_by on the selected runs instead of deleting them")
    ap.add_argument("--confirm", default=None,
                    help="repeat the portfolio id; required with --apply")
    ap.add_argument("--keep", default=",".join(DEFAULT_KEEP),
                    help=f"comma-separated triggered_by values to keep (default: {','.join(DEFAULT_KEEP)})")
    ap.add_argument("--failed", action="store_true",
                    help="also take runs that failed, whatever their label")
    args = ap.parse_args()

    keep = tuple(k.strip() for k in args.keep.split(",") if k.strip())
    if not keep:
        print("refusing to run with an empty keep set — that is every run on the book")
        return 2

    if args.apply and args.relabel:
        print("--apply and --relabel are two different decisions; pass one")
        return 2
    if (args.apply or args.relabel) and args.confirm != args.portfolio_id:
        print(f"--apply/--relabel needs --confirm {args.portfolio_id}")
        return 2
    if args.relabel and args.relabel not in keep:
        print(f"--relabel {args.relabel!r} is not in the keep set ({','.join(keep)}) — "
              "the runs would still be selected on the next run of this script")
        return 2

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT current_user")
    who = cur.fetchone()[0]
    if who != OWNER_ROLE:
        print(f"connected as {who!r}, not the table owner {OWNER_ROLE!r} — "
              "app_rls has no DELETE grant and this would fail row by row")
        return 2

    exists = _rows(cur, "SELECT is_public FROM portfolios WHERE id = %s", (args.portfolio_id,))
    if not exists:
        print(f"no portfolio {args.portfolio_id!r}")
        return 2

    # The selection, printed in full. Not a count: the operator is deciding
    # whether these particular rows are development residue, and a number cannot
    # be checked against that judgement.
    where = "portfolio_id = %s AND (triggered_by IS NULL OR NOT (triggered_by = ANY(%s)))"
    params: tuple = (args.portfolio_id, list(keep))
    if args.failed:
        where = f"portfolio_id = %s AND ((triggered_by IS NULL OR NOT (triggered_by = ANY(%s))) OR status = 'failed')"

    doomed = _rows(cur, f"""
        SELECT id, status, as_of_date, triggered_by, created_at,
               COALESCE(LEFT(error_message, 90), '')
        FROM exposure_runs WHERE {where} ORDER BY created_at DESC""", params)
    kept = _rows(cur, """
        SELECT COUNT(*) FROM exposure_runs
        WHERE portfolio_id = %s AND (triggered_by = ANY(%s))""",
        (args.portfolio_id, list(keep)))[0][0]

    print(f"portfolio {args.portfolio_id} · public={exists[0][0]} · keep={','.join(keep)}"
          f"{' · also taking failed runs' if args.failed else ''}")
    print(f"{len(doomed)} run(s) selected, {kept} kept\n")
    for rid, status, as_of, trig, created, err in doomed:
        print(f"  {rid}  {status:<10} as_of={as_of}  triggered_by={trig!r}"
              f"  {created:%Y-%m-%d}{('  ' + err) if err else ''}")

    if not doomed:
        print("\nnothing to do")
        return 0

    ids = [r[0] for r in doomed]
    events = _rows(cur, "SELECT COUNT(*) FROM workflow_events WHERE run_id = ANY(%s)", (ids,))[0][0]
    print(f"\n  + {events} workflow_events row(s) (no FK — deleted explicitly, see the module docstring)")
    print("  + every child row in the nine cascading tables")

    if args.relabel:
        cur.execute("UPDATE exposure_runs SET triggered_by = %s WHERE id = ANY(%s)",
                    (args.relabel, ids))
        n = cur.rowcount
        conn.commit()
        print(f"\nrelabelled {n} run(s) to {args.relabel!r} — nothing was deleted")
        return 0

    if not args.apply:
        print(f"\ndry run. Either:"
              f"\n  relabel  python scripts/prune_runs.py {args.portfolio_id} "
              f"--relabel manual --confirm {args.portfolio_id}"
              f"\n  delete   python scripts/prune_runs.py {args.portfolio_id} "
              f"--apply --confirm {args.portfolio_id}"
              f"{' --failed' if args.failed else ''}")
        return 0

    cur.execute("DELETE FROM workflow_events WHERE run_id = ANY(%s)", (ids,))
    ev = cur.rowcount
    cur.execute("DELETE FROM exposure_runs WHERE id = ANY(%s)", (ids,))
    rn = cur.rowcount
    conn.commit()
    print(f"\ndeleted {rn} run(s) and {ev} workflow event(s)")

    left = _rows(cur, "SELECT COUNT(*) FROM exposure_runs WHERE " + where, params)[0][0]
    print(f"remaining selected-by-the-same-filter rows: {left} (expected 0)")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
