"""JSON serialization helpers."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


class ExposureJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def dumps(obj: Any, **kwargs: Any) -> str:
    return json.dumps(obj, cls=ExposureJSONEncoder, **kwargs)


def loads(s: str) -> Any:
    return json.loads(s)


# ── capping a tool result for a model's context ───────────────────────────────
# A byte slice of serialized JSON was the first version and it is the wrong cut
# in two ways at once. It hands the model invalid JSON, and — measured on the
# fundamental panel, which is an ordered dict of sixteen formula lines — it drops
# whole entries off the tail SILENTLY: NVDA lost gross_margin, net_debt,
# net_margin and operating_margin every single call. The citation gate then
# refused a number the panel had computed and minted a calc id for, because the
# line carrying that id never reached the model. A loss the model cannot see is
# a loss it cannot work around, so this drops whole entries and says which.

_CAP_DETAIL = ("omitted to fit the message size limit — these were computed and can be "
               "requested individually")


def _largest_container(obj: dict, exclude: tuple[str, ...] = ()) -> str | None:
    """The top-level key holding the most serialized bytes, if it is a container.
    Keys in `exclude` are not candidates."""
    best, best_len = None, -1
    for key, value in obj.items():
        # The table is what the gate resolves against; a payload that dropped
        # part of it would show the model less than it may cite. It is capped
        # where it is built (services/table.py) and never here.
        if key == "table" or key in exclude or not isinstance(value, (dict, list)) or not value:
            continue
        size = len(dumps(value))
        if size > best_len:
            best, best_len = key, size
    return best


def _drop_tail(obj: dict, key: str, limit: int) -> str | None:
    """`obj` with entries taken off the tail of container `key` until it fits,
    the dropped names declared; None when even an empty container does not fit."""
    container = obj[key]
    is_dict = isinstance(container, dict)
    entries = list(container.items()) if is_dict else list(enumerate(container))
    # One entry off the tail at a time, re-serialized each round: the
    # declaration is part of what has to fit, and it grows as the list of
    # dropped names does. Sixteen rounds over eight kilobytes is nothing.
    for keep in range(len(entries) - 1, -1, -1):
        head, tail = entries[:keep], entries[keep:]
        kept = dict(head) if is_dict else [v for _, v in head]
        names = [k if is_dict else f"[{k}]" for k, _ in tail]
        trial = dumps({**obj, key: kept,
                       "truncated": {"container": key, "dropped": names,
                                     "detail": _CAP_DETAIL}})
        if len(trial) <= limit:
            return trial
    return None


def dumps_capped(obj: Any, limit: int, keep: tuple[str, ...] = ()) -> str:
    """Serialize `obj`, dropping whole entries rather than bytes when it is too big.

    Entries come off the tail of the largest top-level container, and what went
    is named in a `truncated` field. Only a dict can carry that field, so a
    payload that is a bare list, or one whose shell alone exceeds the limit, is
    still cut by bytes — declared as `byte_cut` rather than left to look whole.

    `keep` names the containers that are dropped from LAST: the section a call
    asked to open is what its payload is for. V33 found describe(ticker,
    expand='methods') reaching the model as `methods: {}` — expanding is what
    made that section the largest, so the cap emptied exactly it and left the
    map the call was made for in a `truncated` note (MODEL_IO_ANALYSIS §1.2).
    With `keep`, another container gives way first; the kept one is trimmed
    from its tail only when nothing else is left to drop.
    """
    text = dumps(obj)
    if len(text) <= limit:
        return text
    if not isinstance(obj, dict):
        return text[:limit]

    kept_keys = tuple(k for k in keep if k)
    key = None
    for key in (k for k in (_largest_container(obj, exclude=kept_keys), _largest_container(obj)) if k is not None):
        out = _drop_tail(obj, key, limit)
        if out is not None:
            return out
    return dumps({k: v for k, v in obj.items() if not isinstance(v, (dict, list))} |
                 {"truncated": {"container": key, "byte_cut": True,
                                "detail": _CAP_DETAIL}})[:limit]
