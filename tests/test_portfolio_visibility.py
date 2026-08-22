"""V7-U2 — the client can tell the demo book from the caller's own (offline).

GET /portfolios answers "mine plus public": RLS says so and portfolio_service
says so above it. Until this batch the response carried no way to tell the two
apart, and the consequence was not cosmetic — the left panel could not
distinguish a stranger who owns nothing from a desk with one book, so the one
screen that had to say "start here" said nothing at all, and the fastest route
in stayed buried inside a modal.

`is_public` is what makes that question answerable, so these tests pin the three
places it has to hold together: the response model promises it, the column
exists to answer it, and the web type is still a mirror of the model rather than
a copy that has drifted. The last one is the reason the whole file is offline —
the drift it catches type-checks on both sides and only shows up as a field
arriving `undefined` in a browser.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.routes.portfolios import PortfolioOut
from exposure_workbench.db.models import Portfolio

ROOT = Path(__file__).resolve().parents[1]
WEB_TYPES = ROOT / "apps" / "web" / "lib" / "types.ts"
INIT_SQL = ROOT / "infra" / "init.sql"


def test_portfolio_out_says_whether_a_book_is_the_shared_demo():
    field = PortfolioOut.model_fields["is_public"]
    assert field.annotation is bool
    # Required, with no default. A default of False would mean a route that
    # forgot to load the column tells every client "this book is yours" — the
    # single most consequential thing this field says, asserted from nothing.
    assert field.is_required()


def test_portfolio_out_promises_nothing_the_table_cannot_answer():
    """model_validate reads attributes; a field with no column raises at runtime.

    from_attributes turns a missing column into a validation error on the first
    request rather than at import, so nothing here fails until the endpoint is
    called. This is that check, moved to where it costs nothing.
    """
    columns = set(Portfolio.__table__.columns.keys())
    promised = set(PortfolioOut.model_fields)
    assert promised <= columns, f"PortfolioOut fields with no column: {sorted(promised - columns)}"


def test_the_web_type_is_still_a_mirror_of_the_response_model():
    """Both directions, because both are the same silent failure.

    A field the API sends and the web type omits is unreachable from the client;
    a field the web type declares and the API does not send is `undefined` at
    runtime with no compile error anywhere — and `is_public` being undefined
    reads as falsy, which is exactly "this book is yours". The whole first-run
    decision hangs on that value, so the two declarations are pinned equal.
    """
    src = WEB_TYPES.read_text()
    body = re.search(r"export interface Portfolio \{(.*?)\n\}", src, re.DOTALL)
    assert body, "no `export interface Portfolio` in lib/types.ts"
    # Field lines only: `  name: string;`. Comment lines are the file's voice and
    # are deliberately not parsed as anything.
    declared = set(re.findall(r"^\s{2}(\w+)[?]?:", body.group(1), re.MULTILINE))
    # What the RESPONSE carries, not what the model declares: `owner_id` is
    # declared so is_own can be answered and excluded so it never reaches a
    # client, and `is_own` is computed rather than declared. Comparing
    # model_fields alone would report both of those as mismatches while the two
    # sides agreed perfectly on the wire.
    sent = ({n for n, f in PortfolioOut.model_fields.items() if not f.exclude}
            | set(PortfolioOut.model_computed_fields))
    assert declared == sent, (
        f"web-only: {sorted(declared - sent)}, api-only: {sorted(sent - declared)}"
    )


def test_the_demo_book_is_actually_flagged_public():
    """The seed is what makes the flag mean anything.

    Two things read this row's is_public and disagree about nothing else: the
    RLS policy, which is why an anonymous visitor sees a portfolio at all, and
    the first-run card, which appears exactly when every visible book is public.
    Un-flag the demo and the shop window goes dark AND the card never fires for
    anyone — one edit, two failures, neither of them near this line.
    """
    assert re.search(
        r"UPDATE portfolios\s+SET is_public = TRUE WHERE id = 'port_001'",
        INIT_SQL.read_text(),
    ), "the demo portfolio is no longer seeded public"
