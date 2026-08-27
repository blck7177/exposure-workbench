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


def _largest_container(obj: dict) -> str | None:
    """The top-level key holding the most serialized bytes, if it is a container."""
    best, best_len = None, -1
    for key, value in obj.items():
        if not isinstance(value, (dict, list)) or not value:
            continue
        size = len(dumps(value))
        if size > best_len:
            best, best_len = key, size
    return best


def dumps_capped(obj: Any, limit: int) -> str:
    """Serialize `obj`, dropping whole entries rather than bytes when it is too big.

    Entries come off the tail of the largest top-level container, and what went
    is named in a `truncated` field. Only a dict can carry that field, so a
    payload that is a bare list, or one whose shell alone exceeds the limit, is
    still cut by bytes — declared as `byte_cut` rather than left to look whole.
    """
    text = dumps(obj)
    if len(text) <= limit:
        return text
    if not isinstance(obj, dict):
        return text[:limit]

    key = _largest_container(obj)
    if key is not None:
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
    return dumps({k: v for k, v in obj.items() if not isinstance(v, (dict, list))} |
                 {"truncated": {"container": key, "byte_cut": True,
                                "detail": _CAP_DETAIL}})[:limit]
