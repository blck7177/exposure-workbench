"""What a run says when it stops — a closed set of codes, and the rule for
turning an exception into one (V13-S2).

WHY THIS EXISTS. A research run that failed used to reach the person waiting for
it as whatever `str(exc)` happened to be. Three real examples off the live
database on 2026-08-29:

    Research agent analysing AAPL — ERROR: Error code: 429 - {'error': {'message':
        'You exceeded your current quota, please check your plan and …
    the research tool face at http://exposure-mcp:8000/mcp/research could not be
        reached (connect_error)
    pre-fix crash (max_tokens param)

The first is a billing relationship the reader is not party to, the second names
an internal host, the third is a note this desk wrote to itself. All three were
rendered on the issuer page. The chat route had already learned this lesson —
V4-S1 gives ToolFaceUnavailable a 503 and a sentence — but a run's failure took
a different path out and nobody had followed it.

THE SHAPE. A failure has two registers and they travel together but separately:

  code    what happened, from a closed set. The UI keys its sentence on this;
          apps/web/lib/errors.ts must have wording for every member, which
          tests/test_workflow_error_codes.py checks in both directions.
  detail  the exception's own words — the provider's message, the internal
          hostname, the last line of a traceback. It is kept, because the person
          running this desk needs it, and it is shown only in the audit layer.

WHAT IS NOT HERE, deliberately: any rule keyed on the *text* of an exception.
Codes come from the exception's TYPE, walked over its MRO and its cause chain,
because a type is a thing the raiser chose and a message is prose that changes.
The one place this codebase matches on message — `_is_provider_context_error` in
the agent route — says in its own docstring that it does so because neither SDK
exposes a distinct type for that case. There is no such excuse here.

THE ONE THING THAT IS NOT A TYPE LOOKUP is worth its own paragraph, because it
is the mistake this module was one edit away from making. Some failures already
speak to the reader. `_validate_inputs` raises

    Cannot value this portfolio as of 2026-08-26 — newest price older than 10
    days for: AAPL (30d old), … Re-run once the data is available, or remove
    the holdings.

which is a better sentence than anything a code table could substitute: it names
the date, the holdings and the way out. Replacing it with "the run stopped
before finishing" would be this batch destroying information in the name of
tidying it up. So RunRefused marks the class of failure whose message was
written for the reader, and `speaks_for_itself` tells the UI to show that message
instead of the code's generic one. The distinction is structural — a class the
raiser picks — rather than a guess about whether prose looks friendly.
"""

from __future__ import annotations

from dataclasses import dataclass


class RunRefused(ValueError):
    """A run stopping for a reason this desk can put to the person who started it.

    Subclasses ValueError so that everything already catching ValueError keeps
    behaving exactly as it did; the class exists to carry ONE extra bit — that
    the message was written for a reader — which no amount of inspecting the
    string could establish.
    """


class BriefNotSubmitted(RuntimeError):
    """The research agent used its whole budget without submitting a brief.

    Its own class rather than a bare RuntimeError because it is not a defect and
    the reader deserves to be told which of the two it was: nothing is broken,
    the work did not converge, and starting it again is a reasonable thing to do.
    A bare RuntimeError is indistinguishable from a bug and lands in `run_failed`,
    where the sentence is "the run stopped" — true, and useless here.
    """


@dataclass(frozen=True)
class Code:
    """One member of the closed set.

    `speaks_for_itself` is about the EXCEPTION's message, not the code's: when
    true, the run's stored error_message is the exception's own words and the UI
    shows them; when false, the words belong to the operator and the reader gets
    the sentence apps/web/lib/errors.ts holds for this code.
    """

    code: str
    what: str                       # for the operator reading this file
    speaks_for_itself: bool = False


# Every member was earned by a failure that actually happened, not by imagining
# what might. The provenance is in `what`.
CODES: dict[str, Code] = {
    "inputs_unusable": Code(
        "inputs_unusable",
        "the run refused its own inputs and said why — stale or missing prices, "
        "no positions, a risk-limit row naming a check that does not exist",
        speaks_for_itself=True,
    ),
    "provider_quota": Code(
        "provider_quota",
        "the model provider refused on rate or spend (429). Live example: a "
        "research run on AAPL, 2026-07",
    ),
    "provider_unavailable": Code(
        "provider_unavailable",
        "the model provider could not be reached, timed out, or answered 5xx",
    ),
    "provider_refused": Code(
        "provider_refused",
        "the provider rejected the request itself (4xx that is not 429) — always "
        "a defect on this side. Live example: 'max_tokens is not supported'",
    ),
    "tool_face_unavailable": Code(
        "tool_face_unavailable",
        "the tool container could not be reached or refused this run's bearer. "
        "Live example: connect_error to exposure-mcp",
    ),
    "ingest_failed": Code(
        "ingest_failed",
        "fetching the security universe failed. NOT yet EDGAR: that provider "
        "raises bare RuntimeError, so its failures land in run_failed — see the "
        "known limit below _BY_TYPE",
    ),
    "lease_expired": Code(
        "lease_expired",
        "the worker holding the task stopped reporting and the reaper settled it. "
        "Already had a sentence written for the reader (task_service)",
        speaks_for_itself=True,
    ),
    "brief_not_submitted": Code(
        "brief_not_submitted",
        "the research agent spent its whole budget without submitting a brief. "
        "Not a defect: the work did not converge",
    ),
    "run_failed": Code(
        "run_failed",
        "everything else, including defects. Live example: an RLS policy "
        "rejecting a workflow_events insert",
    ),
}

# Exception type -> code, keyed by "<module>.<ClassName>" so that nothing here
# has to import the provider SDK: `openai` is an optional dependency (llm/client
# degrades without it) and a module that fails to import would take every run's
# failure path down with it.
#
# Order matters only in that MRO order resolves it: RateLimitError is looked up
# before its base APIStatusError, so the specific answer wins without this table
# having to encode the hierarchy.
_BY_TYPE: dict[str, str] = {
    "exposure_workbench.errors.workflow_codes.RunRefused": "inputs_unusable",
    "exposure_workbench.errors.workflow_codes.BriefNotSubmitted": "brief_not_submitted",
    "exposure_workbench.agents.tool_session.ToolFaceUnavailable": "tool_face_unavailable",
    "openai.RateLimitError": "provider_quota",
    "openai.APITimeoutError": "provider_unavailable",
    "openai.APIConnectionError": "provider_unavailable",
    "openai.InternalServerError": "provider_unavailable",
    "openai.BadRequestError": "provider_refused",
    "openai.AuthenticationError": "provider_refused",
    "openai.PermissionDeniedError": "provider_refused",
    "openai.NotFoundError": "provider_refused",
    "openai.UnprocessableEntityError": "provider_refused",
    "exposure_workbench.providers.security_master_provider.UniverseFetchError": "ingest_failed",
}

# KNOWN LIMIT, stated rather than papered over. `ingest_failed` is earned by one
# class today. The EDGAR provider raises bare RuntimeError at seven sites
# ("EDGAR could not resolve ticker 'X'", "filing … returned empty text", …), and
# a bare RuntimeError is indistinguishable from a defect, so those failures
# classify as `run_failed` and the reader is told the run stopped rather than
# that EDGAR was the reason. Giving that provider an exception class of its own
# is the fix; it is a change to the provider layer and belongs in its own batch.
# tests/test_workflow_error_codes.py asserts this table names only classes that
# exist, which is how the two invented ones that were briefly here were caught.

DEFAULT_CODE = "run_failed"

# How far down a `raise … from e` chain to look. Failures are wrapped at most
# twice here — ReportUnavailable around an OpenAI error inside a step — and an
# unbounded walk would follow __context__ into whatever unrelated exception
# happened to be in flight.
_CAUSE_DEPTH = 4


def _keys(exc: BaseException) -> list[str]:
    return [f"{c.__module__}.{c.__name__}" for c in type(exc).__mro__]


def classify(exc: BaseException | None) -> str:
    """The code for this failure, from its type and the types it was raised from.

    Walks the cause chain because the informative type is often not the outermost
    one: `ReportUnavailable("the LLM call failed: …")` from a RateLimitError is a
    quota failure, and answering `run_failed` for it would tell the reader to
    try again when trying again is exactly what will not work.
    """
    seen: set[int] = set()
    cur, depth = exc, 0
    while cur is not None and depth < _CAUSE_DEPTH and id(cur) not in seen:
        seen.add(id(cur))
        for key in _keys(cur):
            if key in _BY_TYPE:
                return _BY_TYPE[key]
        cur = cur.__cause__ or cur.__context__
        depth += 1
    return DEFAULT_CODE


def speaks_for_itself(code: str) -> bool:
    """Whether the exception's own message is the one to show the reader."""
    spec = CODES.get(code)
    return bool(spec and spec.speaks_for_itself)


def detail_of(exc: BaseException | None, limit: int = 2000) -> str | None:
    """The operator's half: the type and the exception's own words, capped.

    The type is included because `str(exc)` alone loses it, and "which class"
    is most of the diagnosis when the words are a provider's JSON blob.
    """
    if exc is None:
        return None
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:limit] or None
