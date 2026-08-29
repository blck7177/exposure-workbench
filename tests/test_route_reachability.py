"""No route is unreachable because an earlier one swallows its path (offline).

`GET /api/evidence/labels` was added below `GET /api/evidence/{ref_id}`, and a
path parameter matches any single segment — so the batch-label endpoint answered
`404 no evidence for labels` and nothing on the wire said why. It had sixteen
tests behind it in test_v13_read_endpoints.py and not one of them was a request;
they all read the handler.

That is the shape worth guarding, not the one path. Route order is invisible in
review — the two declarations sit sixteen lines apart in one file and each is
correct on its own — and the failure surfaces as a plausible 404 from the wrong
handler rather than as an error, which is the kind that survives a deploy.

So the guard reads the app's own route table rather than a list of paths anyone
has to remember to extend: every literal path must be matched by its own handler
first. A new endpoint is covered the moment it is registered.
"""

from __future__ import annotations

import pytest


def _registered():
    """Every route in the order the app registers it — main.py's include order,
    which is the order Starlette matches in."""
    from apps.api.main import app  # noqa: F401  (import for side-effect parity)
    from apps.api.routes import (
        portfolios, exposure_runs, tasks, market_data, research, agent,
        issuers, me, securities,
    )
    seq = []
    for module in (portfolios, exposure_runs, tasks, market_data, research,
                   agent, issuers, me, securities):
        seq.extend(module.router.routes)
    return seq


def test_the_route_table_was_actually_read():
    """A guard that examines nothing passes forever. The app had 45 routes when
    this was written; the floor is there to catch an import that stops
    resolving, not to be kept in step with the count."""
    seq = _registered()
    assert len(seq) >= 40, f"only {len(seq)} routes found — the walk is not reaching the app"
    assert any("{" in r.path for r in seq), "no parameterised routes found — nothing to shadow"


def test_no_literal_path_is_shadowed_by_an_earlier_parameterised_one():
    seq = _registered()
    offenders = []
    for i, route in enumerate(seq):
        if "{" in route.path:
            continue
        for earlier in seq[:i]:
            if "{" not in earlier.path:
                continue
            if not (set(earlier.methods) & set(route.methods)):
                continue
            if earlier.path_regex.match(route.path):
                offenders.append(
                    f"{sorted(set(earlier.methods) & set(route.methods))[0]} "
                    f"{route.path} is answered by {earlier.path}"
                )
    assert not offenders, (
        "these routes can never be reached — declare each above the "
        "parameterised route that swallows it:\n  " + "\n  ".join(offenders)
    )
