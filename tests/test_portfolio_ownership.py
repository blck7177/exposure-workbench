"""V7-Q — ownership and publicness are two facts, not one (offline).

`is_public` had been standing in for "somebody else's". The substitution held
only while nothing was both public and yours, and it stopped holding the moment
port_001 was handed to a real account so its owner could run it: the web then
declined to open the one book he owned and told him his desk was empty, while
the API kept answering the question it was actually asked.

So the wire carries both, computed the same way the portfolio snapshot and the
brief already compute it, and the owner id itself stays off the wire.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.routes.portfolios import PortfolioOut
from exposure_workbench.auth.context import current_user_ctx

ROOT = Path(__file__).resolve().parents[1]
PAGE_TSX = ROOT / "apps" / "web" / "app" / "page.tsx"


def _book(owner_id: str | None, is_public: bool) -> PortfolioOut:
    return PortfolioOut(
        id="port_x", name="n", description=None, currency="USD", base_nav=1.0,
        benchmark=None, manager=None, is_active=True, is_public=is_public,
        owner_id=owner_id,
    )


@pytest.mark.parametrize("owner_id, tenant, expected", [
    ("user_a", "user_a", True),
    ("user_a", "user_b", False),
    ("user_a", None, False),          # anonymous: fail closed
    (None, "user_a", False),          # an ownerless row belongs to nobody, not to everyone
    (None, None, False),
])
def test_is_own_is_the_owner_id_against_the_caller(owner_id, tenant, expected):
    token = current_user_ctx.set(tenant)
    try:
        assert _book(owner_id, is_public=False).is_own is expected
    finally:
        current_user_ctx.reset(token)


def test_public_and_own_are_independent():
    """The case that broke the web: the shared demo, owned by the caller."""
    token = current_user_ctx.set("user_a")
    try:
        b = _book("user_a", is_public=True)
        assert (b.is_public, b.is_own) == (True, True)
    finally:
        current_user_ctx.reset(token)


def test_the_owner_id_never_reaches_the_wire():
    """It is carried to answer is_own and nothing else. Putting a tenant's
    identifier in front of every anonymous visitor is what the boolean exists to
    avoid — see the field comment on PortfolioOut."""
    token = current_user_ctx.set("user_a")
    try:
        dumped = _book("user_a", is_public=True).model_dump()
    finally:
        current_user_ctx.reset(token)
    assert "owner_id" not in dumped
    assert dumped["is_own"] is True and dumped["is_public"] is True


def test_the_web_decides_ownership_from_is_own_and_never_from_is_public():
    """Both halves of the old bug were individually consistent: the API answered
    'is this public' correctly and the page asked the wrong question. Nothing
    goes red for that, so this does.

    The ban was on the whole word, which is the right shape while the only thing
    anyone wants publicness for is ownership. V13-S6c wants it for one other
    thing — saying `Shared demo book` on a book that is public AND not yours,
    which is a true sentence that `is_own` alone cannot produce and that
    `!is_own` alone would print over somebody's shared book. So the rule is
    narrowed rather than dropped: publicness may appear, and never on its own.
    An expression that reads `is_public` without `is_own` in the same breath is
    the original bug, and still fails here.
    """
    web = ROOT / "apps" / "web" / "app"
    offenders = []
    for path in sorted(web.rglob("*.tsx")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "is_public" in line and "is_own" not in line:
                offenders.append(f"{path.relative_to(web)}:{n}: {line.strip()}")
    assert not offenders, (
        "publicness is deciding something on its own; it does not mean 'not mine' "
        "— see this module's docstring:\n  " + "\n  ".join(offenders)
    )
    assert any("is_own" in p.read_text() for p in web.rglob("*.tsx")), (
        "the web must ask about ownership directly"
    )
