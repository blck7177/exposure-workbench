"""Arm (or re-arm) the daily scheduled exposure update for one portfolio.

WHAT THIS IS FOR. V13 §9-④A: the worker's scheduler tick fires any active
`schedules` row whose next_run_at has passed, and a scheduled_update task then
syncs the book's prices, resolves the session, and mints the run as the owner.
The rows themselves are operator-managed — there is no route that writes them —
and this script is the one place they are written, so what a schedule says is
always something an operator chose on purpose.

WHY A SCRIPT AND NOT A ROUTE, same shape as prune_runs.py: `schedules` carries
the tenant policy, so the running system can only ever manage a user's own
schedules for them — which is a feature to build someday, not this batch. Until
then, arming a book on someone's behalf is an operational act carried out as
the table owner.

IDEMPOTENT BY (portfolio, task_type). One book gets one exposure_update
schedule; running the script again updates cron/timezone in place rather than
stacking a second alarm for the same work.

next_run_at IS DELIBERATELY LEFT NULL, on insert and on update. The service is
the only thing that computes fire instants (schedule_service.next_fire), and it
arms a NULL row on the next worker tick without firing it — so a schedule
created at 03:00 waits for its first real 06:30, and a cron edit takes effect
from the NEW expression rather than the old row's leftover instant. The dry run
prints the instant the service will arm, computed the same way, so the operator
sees what they are agreeing to.

Usage:
    python scripts/set_schedule.py --portfolio port_001                # dry run
    python scripts/set_schedule.py --portfolio port_001 --apply
    python scripts/set_schedule.py --portfolio port_001 --cron "0 7 * * 1-5" --apply
    python scripts/set_schedule.py --portfolio port_001 --deactivate --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2
from croniter import croniter

from exposure_workbench.services.schedule_service import next_fire

DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv("DATABASE_URL_SYNC",
              "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"),
)
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")

OWNER_ROLE = "exposure"
TASK_TYPE = "exposure_update"

# 06:30 New York, weekdays: after the overnight EDGAR/market lull, an hour
# before any human wants the page, and a session boundary the sync can serve.
DEFAULT_CRON = "30 6 * * 1-5"
DEFAULT_TZ = "America/New_York"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--portfolio", required=True, help="the book to arm, e.g. port_001")
    ap.add_argument("--cron", default=DEFAULT_CRON,
                    help=f"cron expression in the schedule's own zone (default: {DEFAULT_CRON!r})")
    ap.add_argument("--tz", default=DEFAULT_TZ,
                    help=f"IANA timezone the cron is written in (default: {DEFAULT_TZ})")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the row (default: dry run)")
    ap.add_argument("--deactivate", action="store_true",
                    help="switch the schedule off instead of arming it")
    args = ap.parse_args()

    # Validate BEFORE touching the database: a bad expression stored on an
    # active row would fail every scheduler tick until someone fixed the data.
    try:
        ZoneInfo(args.tz)
    except Exception:
        print(f"unknown timezone {args.tz!r}")
        return 2
    if not croniter.is_valid(args.cron):
        print(f"invalid cron expression {args.cron!r}")
        return 2

    will_arm_to = next_fire(args.cron, args.tz, datetime.now(timezone.utc))

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT current_user")
    who = cur.fetchone()[0]
    if who != OWNER_ROLE:
        print(f"connected as {who!r}, not the table owner {OWNER_ROLE!r} — "
              "schedules carries the tenant policy and this must bypass it")
        return 2

    cur.execute("SELECT name, owner_id, is_public FROM portfolios WHERE id = %s",
                (args.portfolio,))
    pf = cur.fetchone()
    if pf is None:
        print(f"no portfolio {args.portfolio!r}")
        return 2
    name, owner_id, is_public = pf
    if owner_id is None:
        print(f"portfolio {args.portfolio!r} has no owner — the minted run would "
              "have no tenant to land under; fix the book first")
        return 2

    cur.execute("""SELECT id, cron_expression, timezone, is_active, next_run_at
                   FROM schedules WHERE portfolio_id = %s AND task_type = %s""",
                (args.portfolio, TASK_TYPE))
    existing = cur.fetchone()

    is_active = not args.deactivate
    print(f"portfolio {args.portfolio} ({name!r}) · owner={owner_id} · public={is_public}")
    if existing:
        sid, old_cron, old_tz, old_active, old_next = existing
        print(f"existing schedule {sid}: cron={old_cron!r} tz={old_tz} "
              f"active={old_active} next_run_at={old_next}")
        print(f"would UPDATE -> cron={args.cron!r} tz={args.tz} active={is_active} "
              f"next_run_at=NULL (service re-arms)")
    else:
        sid = f"sched_{uuid.uuid4().hex[:12]}"
        print(f"no schedule yet; would INSERT {sid}: cron={args.cron!r} tz={args.tz} "
              f"active={is_active} next_run_at=NULL")
    if is_active:
        print(f"the worker will arm it to fire at {will_arm_to:%Y-%m-%d %H:%M %Z} "
              f"({will_arm_to.astimezone(ZoneInfo(args.tz)):%Y-%m-%d %H:%M %Z})")

    if not args.apply:
        print(f"\ndry run — nothing written. Re-run with --apply to "
              f"{'deactivate' if args.deactivate else 'arm'} it.")
        return 0

    if existing:
        cur.execute("""UPDATE schedules
                       SET cron_expression = %s, timezone = %s, is_active = %s,
                           next_run_at = NULL, updated_at = now()
                       WHERE id = %s""",
                    (args.cron, args.tz, is_active, sid))
    else:
        cur.execute("""INSERT INTO schedules
                           (id, portfolio_id, name, task_type, cron_expression,
                            timezone, is_active, next_run_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)""",
                    (sid, args.portfolio, f"Daily exposure update — {args.portfolio}",
                     TASK_TYPE, args.cron, args.tz, is_active))
    conn.commit()
    print(f"\n{'updated' if existing else 'inserted'} {sid} "
          f"(active={is_active}, next_run_at=NULL — armed on the next worker tick)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
