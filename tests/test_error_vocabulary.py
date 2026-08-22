"""V7-U3 — the UI and the API agree on what a refusal is called (offline).

apps/web/lib/errors.ts turns a refusal into a sentence a person can act on, and
it does that by matching an error CODE. A code the UI matches on but nobody
raises is a branch that can never fire — the user gets the generic "something
went wrong" for a failure we thought we had explained, and nothing goes red
because both halves are individually consistent.

That is not hypothetical. This guard exists because the 404 branch was written
when the chat panel was the only caller: it said "that conversation is no longer
available" and threw away the session id. When the issuer page started using the
same helper, a mistyped ticker — a 404 from a completely different route — told
the user their conversation had expired and dropped an unrelated session. The
fix was to key on codes instead of status, and codes only work if the two sides
are actually spelling them the same way.

Deliberately one-directional: the API raises many codes the web has no wording
for (tool-level failures the model reads, not the user), and that is fine. What
must not happen is the reverse.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS_TS = ROOT / "apps" / "web" / "lib" / "errors.ts"

# Where a code can legitimately be minted. Services are included because
# quota_exceeded is raised by usage_service and only re-raised by the route.
_SOURCES = [ROOT / "apps" / "api", ROOT / "src" / "exposure_workbench"]


def _codes_the_ui_explains() -> set[str]:
    return set(re.findall(r'detail\?\.error === "([a-z_]+)"', ERRORS_TS.read_text()))


def _codes_the_api_raises() -> set[str]:
    found: set[str] = set()
    for root in _SOURCES:
        for f in root.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            found |= set(re.findall(r'"error": "([a-z_]+)"', f.read_text()))
    return found


def test_every_explained_code_is_one_the_api_actually_raises():
    explained = _codes_the_ui_explains()
    raised = _codes_the_api_raises()
    orphans = sorted(explained - raised)
    assert orphans == [], (
        f"apps/web/lib/errors.ts explains codes nothing raises: {orphans}. "
        "Either the API renamed them, in which case the UI is now silently "
        "showing the generic message for a failure it has words for, or the "
        "branch was written for a code that never existed."
    )


def test_the_ui_explains_the_refusals_a_person_can_act_on():
    """The set is small and each member is here for a reason a reader can check.

    Not an inventory of every code — most are for the model, not the user. These
    are the ones a person meets by using the product: a second tab, a spent
    allowance, a conversation that outgrew a turn, a container that is down, a
    run already going, a symbol that does not exist or is out of scope, and a
    session id that no longer belongs to anyone.
    """
    assert _codes_the_ui_explains() == {
        "turn_in_flight",
        "quota_exceeded",
        "session_context_exhausted",
        "tool_face_unavailable",
        "active_run_exists",
        "unknown_session",
        "unknown_ticker",
        "not_investigable",
    }


def test_the_refusals_the_ui_explains_are_not_raised_as_prose():
    """A code in the body, not a sentence in `detail`.

    FastAPI happily takes a string, and a string is what these three were:
    HTTPException(404, "unknown session"), HTTPException(404, f"unknown ticker
    {tk}"), HTTPException(422, f"{tk} is not investigable"). The web could then
    only tell them apart by status code, which is exactly how a ticker typo came
    to be explained as an expired conversation.
    """
    routes = (ROOT / "apps" / "api" / "routes").rglob("*.py")
    offenders = []
    for f in routes:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            m = re.search(r'HTTPException\((404|422|409),\s*f?"', line)
            if not m:
                continue
            if any(w in line for w in ("session", "ticker", "investigable")):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == [], (
        "a refusal the UI has to explain is still prose in `detail`: " + "; ".join(offenders)
    )
