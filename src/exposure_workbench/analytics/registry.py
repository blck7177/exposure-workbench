"""The desk's registry (V1, step 1): the closed vocabulary a Fact's MEANING is
written in, and the words a row is rendered with.

WHY THIS EXISTS. The services computed what a reading means — a net beta's
`loses / gains`, a check's `clear / warning / breach`, that a fit is collinear,
which line stood in for which — and the tool boundary dropped every one of those
words, because a Fact held numbers and the words were string leaves. The model
was handed −0.86 and a handbook sentence about signs; the handbook grew four
copies of that sentence, and the answer check could not tell "gains" from
"loses" because the ledger held neither (IMPLEMENTATION_PLAN_V1 §2.2).

So the words travel with the figure. A producer says them in its own payload,
the namer carries them, the Fact stores them under `means`, and one renderer
turns the stored row into the line a trained analyst reads without a legend:

    [f_…] what, of, when: value — means — from

WHAT IS STORED AND WHAT IS RENDERED. `means` holds only what the row cannot
derive: the exposure's direction, a check's status, a basis, a flag, an
absence's reason and way out. A place in an ordering, a change's sign and what a
composed total was built from are already on the row (`params.place/of`,
`params.op` with the value, `params.made_of/substituted`), so they are RENDERED
from there and never copied. The line is a pure function of the stored row.

NO FREE TEXT. Every stored word is a key of a table below; an unknown key or
value is an error at the Fact's construction, not a sentence a reader later has
to interpret. `way_out` is the one string: it names allowed values or another
door, and the desk writes it, never the model.

Step 2 grows this module into the full registry (a measure's definition, unit,
basis, reading and authority in one entry). What is here is the part every
later step reads.
"""

from __future__ import annotations

import re
from typing import Any

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.analytics import resources as rs

# ── the vocabulary ────────────────────────────────────────────────────────────

# What the book does if the risk the measure names happens. The word, not the
# sign (analytics/integration.NetExposure.direction): "loses if equities fall"
# cannot be misread, and "−0.86" was, as a short book, twice in round C.
DIRECTION: dict[str, str] = {
    "loses": "the book loses if this risk happens",
    "gains": "the book gains if this risk happens",
    "flat": "the book is flat to this risk",
}

# Where a check stands against its own tiers. `ok` is the limits engine's word
# for `clear` (analytics/limits.CheckRecord.status) and is mapped on the way in.
STATUS: dict[str, str] = {
    "clear": "clear of its tiers",
    "warning": "in warning",
    "breach": "in breach",
    "not_run": "check not run",
}
_STATUS_ALIASES = {"ok": "clear"}

# What a figure was built on, where the choice changes how it compares.
BASIS: dict[str, str] = {
    "ending_balance": "built on ending balances",
    "average_balance": "built on average balances",
    "adjusted_close": "over the adjusted close",
    "as_traded_close": "over the as-traded close",
    "book_return": "fitted on the book's return",
    "name_return": "fitted on the name's own return",
}

# What limits how the figure may be used.
FLAGS: dict[str, str] = {
    "collinear_legs_not_quotable": "collinear fit: the net is quotable, no single leg is",
    "withheld_pending_validation": "withheld pending validation",
    "proxy": "a proxy stands in for the thing named",
}

# Why the desk has nothing to show. Eight reasons and `cannot`; a tool that
# refuses says which, so the requirement list can be counted by reason.
ABSENCE_REASONS: dict[str, str] = {
    "not_held": "the desk does not hold this",
    "not_on_this_face": "this belongs to another analyst's face",
    "not_prepared": "this name is not prepared",
    "no_such_name": "the desk has nothing by this name",
    "param_out_of_range": "the request does not fit what this takes",
    "meaningless": "the reading has no meaning here",
    "not_comparable": "the figures are not comparable",
    "policy": "the desk does not say this, by policy",
    "cannot": "the desk could not do this",
}

# The error codes the services already speak, by the reason they are. A code
# that is not here is `cannot`: it stopped the desk, and nothing finer is known
# about it. Deterministic, in one place, and read by nothing the model sees.
_REASON_OF_CODE: dict[str, str] = {
    **{c: "not_held" for c in (
        "not_held", "metric_not_filed", "not_a_filed_line", "not_reported_at_this_date", "input_unavailable",
        "no_price_data", "no_prior_run", "no_completed_run", "no_entry_satisfies", "insufficient_history",
        "no_facts_for_issuer", "unknown_portfolio", "unknown_run")},
    **{c: "not_prepared" for c in (
        "not_prepared", "company_not_found", "not_listed", "not_indexed", "active_run_exists",
        "not_investigable", "not_an_sec_filer")},
    **{c: "no_such_name" for c in (
        "unknown_name", "unknown_method", "unknown_primitive", "unknown_binding", "unknown_point")},
    **{c: "param_out_of_range" for c in (
        "invalid_params", "type_mismatch", "type_errors", "malformed_program", "several_figures",
        "untyped_result", "query_or_item")},
    **{c: "meaningless" for c in (
        "not_for_financials", "division_by_zero", "denominator_not_positive", "not_alone")},
    **{c: "not_comparable" for c in (
        "incompatible_units", "misaligned_vectors", "unit_mismatch", "different_books", "mixed_worlds",
        "overlapping_intervals", "different_dates", "double_count")},
    **{c: "policy" for c in ("withheld", "forecast", "no_threshold")},
}

MEANS_KEYS = ("direction", "status", "basis", "flags", "reason", "way_out")
WAY_OUT_CHARS = 400


def reason_of(code: Any) -> str:
    """The absence reason a service's error code is; `cannot` when it names none."""
    return _REASON_OF_CODE.get(code, "cannot") if isinstance(code, str) else "cannot"


def status_word(word: Any) -> str | None:
    """A check status in the registry's words, or None when `word` is not one."""
    if not isinstance(word, str):
        return None
    w = _STATUS_ALIASES.get(word.lower(), word.lower())
    return w if w in STATUS else None


def validate_means(means: Any) -> dict:
    """The `means` a Fact may store, or a ValueError naming what is not in the
    vocabulary. Called at construction (services/facts.Fact.__post_init__)."""
    if means in (None, {}):
        return {}
    if not isinstance(means, dict):
        raise ValueError(f"means is a dict of registry words; got {type(means).__name__}")
    unknown = sorted(set(means) - set(MEANS_KEYS))
    if unknown:
        raise ValueError(f"means carries keys the registry does not define: {unknown}")
    out: dict = {}
    for key, table in (("direction", DIRECTION), ("status", STATUS), ("reason", ABSENCE_REASONS)):
        if means.get(key) is not None:
            if means[key] not in table:
                raise ValueError(f"means.{key} {means[key]!r} is not one of {sorted(table)}")
            out[key] = means[key]
    for key, table in (("basis", BASIS), ("flags", FLAGS)):
        words = means.get(key)
        if words:
            if not isinstance(words, (list, tuple)) or any(w not in table for w in words):
                raise ValueError(f"means.{key} {words!r} must be a list from {sorted(table)}")
            out[key] = list(dict.fromkeys(words))
    if means.get("way_out"):
        if not isinstance(means["way_out"], str):
            raise ValueError("means.way_out is a sentence the desk wrote")
        out["way_out"] = means["way_out"][:WAY_OUT_CHARS]
    return out


def words_beside(obj: Any) -> dict:
    """The registry words a producer wrote BESIDE a figure in its own payload:
    `direction`, `status`, `quotable_individually: False`. Read by the namer and
    the adapters, so the word a service computed travels with its number.

    `direction` is also the ordering's own word (`highest | lowest`) on a rank
    payload; only a word of this vocabulary is taken, so the two never meet."""
    if not isinstance(obj, dict):
        return {}
    out: dict = {}
    if obj.get("direction") in DIRECTION:
        out["direction"] = obj["direction"]
    status = status_word(obj.get("status"))
    if status:
        out["status"] = status
    if obj.get("quotable_individually") is False:
        out["flags"] = ["collinear_legs_not_quotable"]
    return out


def merged(a: dict | None, b: dict | None) -> dict:
    """Two `means`, the second winning a single word and lists joined."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        if k in ("basis", "flags"):
            out[k] = list(dict.fromkeys([*(out.get(k) or []), *v]))
        elif v is not None:
            out[k] = v
    return out


# ── what a measure reads as ───────────────────────────────────────────────────
# The financial name of a measure key. The tables are the ones the pages
# already use (analytics/display_names) and the columns a run declares
# (analytics/resources); step 2 makes every mintable key an entry here, and
# until then a key with no caption appears as itself, words spaced — visible,
# and a missing row rather than a wrong one.

_COLUMN_NAMES: dict[str, str] = {}
for _r in rs._DECLARED:
    for _c in _r.columns:
        _COLUMN_NAMES.setdefault(f"{_r.table}.{_c.name}", f"{_r.table.replace('_', ' ')}: {_c.display}")

_DERIVED_NAMES: dict[str, str] = {
    "portfolio.integration.net_beta": "net beta to",
    "portfolio.integration.gross_beta": "gross beta to",
    "portfolio.integration.room_to_warning": "room to the warning tier",
    "portfolio.integration.room_to_breach": "room to the breach tier",
}


def reads_as(measure: str | None) -> str:
    m = measure or ""
    if m in dn.FORMULA:
        return dn.FORMULA[m]
    if m in dn.METRIC:
        return dn.METRIC[m]
    if m in _COLUMN_NAMES:
        return _COLUMN_NAMES[m]
    for key, name in _DERIVED_NAMES.items():
        if m == key:
            return name.removesuffix(" to")
        if m.startswith(key + "."):
            rest = m[len(key) + 1:].replace("_", " ")
            return f"{name} {rest}" if name.endswith(" to") else f"{name}, {rest}"
    return re.sub(r"[._]+", " ", m).strip()


# ── the words a row is rendered with ─────────────────────────────────────────

CHANGE_OPS = ("yoy", "qoq", "pct", "cagr", "subtract")
_COVER_WORDS = (("missing_at_this_date", "missing at this date"),
                ("no_facts_for_issuer", "never filed by this issuer"),
                ("overlapping_not_added", "overlapping, not added"))


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _names(v: Any) -> str:
    items = v if isinstance(v, (list, tuple)) else [v]
    return ", ".join(str(x).replace("_", " ") for x in items if x)


def composition_words(params: dict) -> list[str]:
    """What a composed figure was built from, from `params.substituted` and
    `params.made_of` (services/formula_service._made_of)."""
    out: list[str] = []
    for wanted, used in (params.get("substituted") or {}).items():
        out.append(f"built on {str(used).replace('_', ' ')} in place of {str(wanted).replace('_', ' ')}")
    for name, info in (params.get("made_of") or {}).items():
        if not isinstance(info, dict):
            continue
        if info.get("formula"):
            out.append(f"{str(name).replace('_', ' ')} = {info['formula']}")
        if info.get("substituted"):
            out.append(f"{str(name).replace('_', ' ')} substitutes {_names(info['substituted'])}")
        for key, said in _COVER_WORDS:
            if info.get(key):
                out.append(f"{said}: {_names(info[key])}")
    return out


def means_words(rec: dict) -> str:
    """The `means` of one stored row, as the clause a reader is shown. A pure
    function of the row: the stored words, then what the row itself implies."""
    means = rec.get("means") or {}
    params = rec.get("params") or {}
    said: list[str] = []
    if rec.get("kind") == "absence":
        text = str(rec.get("text") or "").strip() or ABSENCE_REASONS.get(means.get("reason") or "cannot", "")
        said.append(text)
        if means.get("way_out"):
            said.append(means["way_out"])
        return "; ".join(s for s in said if s)
    if means.get("direction"):
        said.append(DIRECTION[means["direction"]])
    if means.get("status"):
        said.append(STATUS[means["status"]])
    place, of = params.get("place"), params.get("of")
    if isinstance(place, int) and isinstance(of, int):
        said.append(f"{ordinal(place)} highest of {of}")
    elif isinstance(params.get("rank"), int):
        said.append(f"rank {params['rank']}")
    value = rec.get("value")
    if params.get("op") in CHANGE_OPS and isinstance(value, (int, float)) and not isinstance(value, bool):
        said.append("up" if value > 0 else "down" if value < 0 else "flat")
    said.extend(composition_words(params))
    said.extend(BASIS[w] for w in means.get("basis") or [])
    flags = list(means.get("flags") or [])
    said.extend(FLAGS[w] for w in flags)
    if rec.get("standalone") is False and "collinear_legs_not_quotable" not in flags:
        said.append("not quotable on its own")
    return "; ".join(said)


# ── what the desk does not say, as facts a sentence can point at ─────────────
# A line the policy stops has to be filed as "not settled" with the id of a
# boundary, and no tool mints one for a policy: nothing was asked of a tool. So
# the three policies stand on every ledger under fixed ids. The sentences are
# the desk's own, as DESK_RULES has carried them since 2026-08-24.

POLICY_ABSENCES: tuple[dict, ...] = tuple(
    {"id": fid, "kind": "absence", "measure": measure, "subject": None, "unit": None, "value": None,
     "points": None, "text": text, "as_of": "n/a", "window": None, "params": {}, "means": {"reason": "policy"},
     "standalone": False, "sources": [], "group": "boundary"}
    for fid, measure, text in (
        ("f_policy_no_forecast", "policy.no_forecast",
         "The desk does not forecast. Asked for next year's figure, it says so and gives what the issuer's own "
         "filings say would move the figure either way."),
        ("f_policy_no_threshold", "policy.no_threshold",
         "No measure carries a threshold. A number is laid out with what it is compared against and the reading "
         "belongs to the reader."),
        ("f_policy_no_estimate", "policy.no_estimate",
         "A figure the desk does not hold is an absence, said as such with its reason — never a nearby figure "
         "under the asked-for name, never an estimate."),
    ))
POLICY_IDS = frozenset(p["id"] for p in POLICY_ABSENCES)
