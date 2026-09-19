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
    if m in METHODS:
        return METHODS[m].reads_as
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


# ══ the measures (V1 step 2) ═════════════════════════════════════════════════
#
# ONE ENTRY, THREE FACES. A measure this desk computes is written once, here:
# the handbook's "what it is" and "how it reads" are rendered from the entry,
# a tool's `metric` takes its name and declares what it yields, and the Fact it
# births carries its words. Until V1 the entry was `analytics/skill.Method` and
# its reading a separate table the model met as prose; both moved here whole
# (skill re-exports them), and an entry now also says its financial name
# (`reads_as`), what it is built on (`basis`), and which analysts may ask for it
# by name (`faces`). A word that is on the row — a direction, a status — is not
# repeated in a reading: the reading says only what the row cannot.

from dataclasses import dataclass, field, replace  # noqa: E402

from exposure_workbench.analytics import formulas as fm  # noqa: E402

FACES = ("issuer", "market", "risk")

SUBJECT_KINDS = ("issuer", "price", "run", "portfolio", "series")

# Where compute finds the code that runs a method. A name, not a callable, so
# this module imports no service and the registry stays importable anywhere
# (the tool container, a test, the catalogue).
EXECUTORS = (
    "formula", "formula.panel",
    "price.rolling_volatility", "price.beta", "price.momentum_12_1",
    "price.distance_from_52w_high", "price.adv", "price.drawdown", "price.window_return",
    "book.analysis", "book.reconcile", "book.drawdown_episodes", "book.explain_episode",
    "book.sell", "book.buy", "book.position",
)


@dataclass(frozen=True)
class Method:
    """One named method. `describes` is one sentence for a reader; `procedure`
    is what the number is made of; `authority` is who says it is made that way."""

    name: str
    subject_kind: str
    family: str
    describes: str
    procedure: str
    authority: str
    fails_when: str
    executor: str
    params_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {},
                                                          "additionalProperties": False})
    unit_class: str | None = None
    source_url: str = ""
    inputs: tuple[str, ...] = ()
    # Which quantities the result puts on the table, as the reader will see
    # them named — for `describe`, so the model knows what a method yields
    # before paying for it.
    yields: tuple[str, ...] = ()
    # V1: the entry's other two faces. `reads_as` is the financial name a row
    # prints; `basis` the registry words every fact of it carries; `faces` the
    # analysts who may ask for it by name (a scenario is an action and has none).
    reads_as: str = ""
    basis: tuple[str, ...] = ()
    faces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reads_as:
            object.__setattr__(self, "reads_as", dn.FORMULA.get(self.name) or self.name.split(".", 1)[-1].replace("_", " "))
        if any(b not in BASIS for b in self.basis):
            raise ValueError(f"{self.name}: basis {self.basis!r} is not in the registry's vocabulary")
        if any(f not in FACES for f in self.faces):
            raise ValueError(f"{self.name}: faces {self.faces!r} must be among {FACES}")
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(f"{self.name}: subject_kind {self.subject_kind!r} is not one of {SUBJECT_KINDS}")
        if self.executor not in EXECUTORS:
            raise ValueError(f"{self.name}: executor {self.executor!r} is not one compute knows")
        if not self.authority.strip():
            raise ValueError(f"{self.name}: a method states its authority; none given")
        if not self.fails_when.strip():
            raise ValueError(f"{self.name}: a method states when it fails or is meaningless; none given")
        if self.params_schema.get("type") != "object":
            raise ValueError(f"{self.name}: params_schema must describe an object")


# ── issuer methods: the formula registry, one entry per formula ──────────────

_ISSUER_PARAMS = {"type": "object", "properties": {
    "months": {"type": ["integer", "null"], "enum": [3, 6, 9, 12, None],
               "description": "window for flow-based measures (default 12)"},
    "at": {"type": ["string", "null"], "description": "YYYY-MM-DD: the balances at this date and every flow over the `months` window ending there (a reported period end); omitted = latest"},
    "last_n": {"type": ["integer", "null"], "minimum": 2, "maximum": 16,
               "description": "the measure over its last N periods (months each) as ONE series, for yoy/cagr/trend; omitted = one value"},
}, "additionalProperties": False}


# the working-capital days are built on ENDING balances, not averages, and every
# fact of them says so (the handbook said it in prose; the row says it now)
_ENDING_BALANCE_MEASURES = ("days_sales_outstanding", "days_inventory", "days_payable", "cash_conversion_cycle")


def _fails_when_formula(f: fm.Formula) -> str:
    parts = ["an input the issuer did not file at the window or instant asked"]
    if f.not_for_financials is not None:
        parts.append("the issuer is a financial company: " + f.not_for_financials.split(":")[0])
    if f.denominator_must_be_positive:
        parts.append(f.denominator_must_be_positive)
    return "; ".join(parts)


def _issuer_methods() -> dict[str, Method]:
    out: dict[str, Method] = {}
    for name, f in fm.FORMULAS.items():
        out[name] = Method(
            name=name, subject_kind="issuer", family=f.family, describes=f.expression,
            procedure=f"{f.op} over {', '.join(f.inputs)}", authority=f.citation,
            source_url=f.source_url, fails_when=_fails_when_formula(f), executor="formula",
            params_schema=_ISSUER_PARAMS, unit_class=f.unit_class, inputs=f.inputs,
            yields=(name,), faces=("issuer",),
            basis=(("ending_balance",) if name in _ENDING_BALANCE_MEASURES else ()),
        )
    out["issuer.panel"] = Method(
        name="issuer.panel", subject_kind="issuer", family="panel",
        describes="every named issuer measure this desk knows, evaluated once, with each one's own refusal where an input is missing",
        procedure="evaluate every entry of the formula registry", authority="the registry's own entries, each with its citation",
        fails_when="never as a whole; each measure fails on its own terms",
        executor="formula.panel", params_schema=_ISSUER_PARAMS, yields=tuple(fm.FORMULAS),
        reads_as="every issuer measure at once", faces=("issuer",),
    )
    return out


# ── price methods: what price_analytics_service computes, as data ────────────

_TICKER_WINDOW = {"type": "object", "properties": {
    "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", "3y", None],
               "description": "named span (default 1y)"},
}, "additionalProperties": False}

_PRICE_METHODS: tuple[Method, ...] = (
    Method(
        name="price.volatility", subject_kind="price", family="risk",
        reads_as="annualised volatility", basis=("adjusted_close",), faces=("market", "risk"),
        describes="annualised volatility of the last N daily returns; a short window reacts, a long one is the baseline",
        procedure="standard deviation of daily simple returns over the window × √252",
        authority="CFA Program, Quantitative Methods (return volatility); √252 annualisation is the industry convention",
        fails_when="fewer than 20 sessions in the window (VOL_MIN_OBS): refused with the counts, never shortened",
        executor="price.rolling_volatility", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "window_days": {"type": ["integer", "null"], "enum": [21, 30, 63, 126, 252, None],
                            "description": "sessions in the window (default 30)"}},
            "additionalProperties": False},
        yields=("{ticker}.vol.{n}d",),
    ),
    Method(
        name="price.beta", subject_kind="price", family="risk",
        reads_as="beta to a benchmark", basis=("adjusted_close", "name_return"), faces=("market", "risk"),
        describes="a name's sensitivity to a benchmark: OLS beta, alpha and R² of its daily returns on the benchmark's (default SPY; TLT for rates, HYG for credit — the per-name sensitivity)",
        procedure="ordinary least squares of adjusted daily returns on the benchmark's, aligned by date",
        authority="Sharpe (1964) market model; CFA Program, Portfolio Management (beta estimation)",
        fails_when="fewer than 60 aligned observations (BETA_MIN_OBS); a benchmark with no price history",
        executor="price.beta", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "benchmark": {"type": ["string", "null"], "description": "benchmark ticker (default SPY); a factor ETF such as TLT gives the name's sensitivity to that factor"},
            "window": _TICKER_WINDOW["properties"]["window"]},
            "additionalProperties": False},
        yields=("{ticker}.beta", "{ticker}.alpha", "{ticker}.r_squared"),
    ),
    Method(
        name="price.momentum_12_1", subject_kind="price", family="momentum",
        reads_as="12-1 momentum", basis=("adjusted_close",), faces=("market",),
        describes="cumulative adjusted return from ~12 months back through 21 sessions back, the last month skipped",
        procedure="adjusted close 21 sessions back ÷ adjusted close ~252 sessions back − 1",
        authority="Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers",
        fails_when="fewer than 200 sessions of history (MOMENTUM_MIN_OBS); a formation window under 252 sessions is flagged",
        executor="price.momentum_12_1", unit_class="ratio", yields=("{ticker}.momentum_12_1",),
    ),
    Method(
        name="price.distance_from_52w_high", subject_kind="price", family="momentum",
        reads_as="distance from the 52-week high", basis=("adjusted_close",), faces=("market",),
        describes="how far the adjusted close sits below its trailing-year high, with the date the high was set",
        procedure="close ÷ max(close over the trailing year) − 1",
        authority="George & Hwang (2004), The 52-Week High and Momentum Investing",
        fails_when="fewer than 200 sessions of history (MOMENTUM_MIN_OBS)",
        executor="price.distance_from_52w_high", unit_class="ratio",
        yields=("{ticker}.distance_from_52w_high",),
    ),
    Method(
        name="price.adv", subject_kind="price", family="liquidity",
        reads_as="average daily volume", basis=("as_traded_close",), faces=("market", "risk"),
        describes="average daily volume over the last N sessions, in shares a session and in dollars a session — the liquidity a position is measured against: a position's market value divided by dollar ADV is its days to liquidate",
        procedure="mean of daily volume, and of close × volume, over the window; sessions without volume dropped and counted",
        authority="average daily volume as the standard market-depth measure; days to liquidate = position ÷ (participation rate × dollar ADV), the days-to-cash framing of SEC Rule 22e-4",
        fails_when="fewer than 20 sessions (ADV_MIN_OBS) or no recorded volume",
        executor="price.adv", unit_class="count_per_day",
        params_schema={"type": "object", "properties": {
            "window_days": {"type": ["integer", "null"], "enum": [20, 30, 60, None],
                            "description": "sessions in the window (default 20)"}},
            "additionalProperties": False},
        yields=("{ticker}.adv.shares", "{ticker}.adv.dollars"),
    ),
    Method(
        name="price.drawdown", subject_kind="price", family="risk",
        reads_as="deepest drawdown", basis=("adjusted_close",), faces=("market",),
        describes="the deepest peak-to-trough fall of the adjusted close over a window: peak, trough, fall and depth, dated, with the recovery date if regained",
        procedure="max over the window of (running peak − close); fall = peak − trough, depth = fall ÷ peak",
        authority="the standard drawdown definition (Magdon-Ismail, Atiya, Pratap & Abu-Mostafa, 2004)",
        fails_when="fewer than 20 sessions (DRAWDOWN_MIN_OBS); a window that never fell is stated, not zero",
        executor="price.drawdown", unit_class="ratio", params_schema=_TICKER_WINDOW,
        yields=("{ticker}.drawdown.peak", "{ticker}.drawdown.trough", "{ticker}.drawdown.fall", "{ticker}.drawdown.depth"),
    ),
    Method(
        name="price.window_return", subject_kind="price", family="return",
        reads_as="return over a window", basis=("adjusted_close",), faces=("market",),
        describes="total return over a named window, and relative to a benchmark when one is given",
        procedure="adjusted close at the window's end ÷ at its start − 1; relative = the name's return − the benchmark's",
        authority="total-return convention on split- and dividend-adjusted closes",
        fails_when="no price on or before either end of the window",
        executor="price.window_return", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", None], "description": "default 1y"},
            "benchmark": {"type": ["string", "null"], "description": "benchmark ticker for the relative return; null for none"}},
            "additionalProperties": False},
        yields=("{ticker}.window_return", "{ticker}.window_return.relative"),
    ),
)


# ── book methods: what the run's readers derive, as data ─────────────────────

_BOOK_METHODS: tuple[Method, ...] = (
    Method(
        name="book.analysis", subject_kind="run", family="book",
        reads_as="the book's net exposures and room to its tiers", basis=("book_return",), faces=("risk",),
        describes="one run's factor exposures netted per risk (net beta), positions ordered by weight, and the room from every limit check to its warning and breach tiers",
        procedure="net beta per risk = Σ beta_i × sense_i, the sense being the risk's effect on the book for a positive beta: −1 for SPY, QQQ and IWM (equity_down), for TLT (rates_up) and for HYG (credit_spreads_widen); room = tier − current; positions ordered by weight",
        authority="arithmetic over the run's own rows; instrument directions are properties of the factor ETFs, not of any issuer",
        fails_when="the run is not completed; a risk no factor in the regression measures is reported unmeasured, not zero",
        executor="book.analysis", unit_class="ratio",
        yields=("portfolio.integration.net_beta.<risk>", "portfolio.integration.gross_beta.<risk>",
                "portfolio.integration.room_to_warning.<check>", "portfolio.integration.room_to_breach.<check>"),
    ),
    Method(
        name="book.reconcile", subject_kind="run", family="attribution",
        reads_as="one day's move, reconciled", faces=("risk",),
        describes="one day's portfolio move reconciled: position contributions against the day's return, and the factor-explained share against the residual",
        procedure="Σ position contributions = portfolio return; Σ factor contributions + alpha + residual = portfolio return; factor_share = Σ factor / total",
        authority="the two accounting identities of return attribution (Brinson-style position attribution; the factor model's own decomposition)",
        fails_when="the position identity does not hold within tolerance — then no share of the move is reported at all",
        executor="book.reconcile", unit_class="ratio",
        # every figure the reconciliation records (resources.CALC_RESULTS), so the
        # page offers the factor sum the second identity needs (V38/S5)
        yields=("portfolio.reconcile.sum_of_position_contributions", "portfolio.reconcile.sum_of_factor_contributions",
                "portfolio.reconcile.alpha_plus_residual", "portfolio.reconcile.factor_share",
                "portfolio.reconcile.unexplained_share"),
    ),
    Method(
        name="book.drawdown_episodes", subject_kind="portfolio", family="risk",
        reads_as="the book's drawdown episodes", faces=("risk",),
        describes="every peak-to-trough episode of the book at least 5% deep in a span, deepest first, with trough and recovery dates",
        procedure="episodes of the portfolio value path; depth = (peak − trough) ÷ peak",
        authority="the standard drawdown definition; the 5% floor is a producer parameter",
        fails_when="fewer sessions than the span needs; a span that never fell 5% has no episodes",
        executor="book.drawdown_episodes", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "span": {"type": ["string", "null"], "enum": ["3m", "6m", "1y", "3y", None], "description": "default 1y"}},
            "additionalProperties": False},
        yields=("portfolio.drawdown_episodes.deepest_depth", "portfolio.drawdown_episodes.episode_depths"),
    ),
    Method(
        name="book.explain_episode", subject_kind="portfolio", family="risk",
        reads_as="what one drawdown episode was made of", faces=("risk",),
        describes="what one drawdown episode was made of: the book's return over the window and each holding's contribution to it",
        procedure="window return of the book and of each position between the peak and trough dates",
        authority="arithmetic over the price series the book holds",
        fails_when="no prices on the peak or trough date",
        executor="book.explain_episode", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "peak": {"type": "string", "description": "YYYY-MM-DD"},
            "trough": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["peak", "trough"], "additionalProperties": False},
    ),
    Method(
        name="book.sell", subject_kind="run", family="scenario",
        reads_as="the book after a sale",
        describes="the book after selling all or part of some names: weights renormalised over what remains, sector weights, market value, and every concentration and exposure limit check re-run; the proceeds leave the book. The subject is a run (run_…) or another scenario's calc_ row, so trades chain",
        procedure="remove the sold market value; weight_i = mv_i ÷ Σ mv remaining; check_limits over the result with the portfolio's own thresholds",
        authority="arithmetic over the run's positions; thresholds from the portfolio's risk_limits (analytics/limits)",
        fails_when="a name not held, a fraction outside (0, 1], a name sold twice, a sale emptying the book, an unpriced holding; factor exposures are not re-fitted and are stated unmeasured",
        executor="book.sell", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "sales": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "fraction": {"type": "number", "exclusiveMinimum": 0, "maximum": 1,
                             "description": "share of the position sold; omitted means all of it"}},
                "required": ["ticker"], "additionalProperties": False}}},
            "required": ["sales"], "additionalProperties": False},
        yields=("issuer_exposures.<T>.weight", "sector_exposures.<S>.weight", "exposure_metrics.portfolio_market_value",
                "limit_checks.<check>.current_value", "count.alerts"),
    ),
    Method(
        name="book.buy", subject_kind="run", family="scenario",
        reads_as="the book after a purchase",
        describes="the book after adding names at target weights of the new book: every existing weight scaled down, sector weights, market value, and every concentration and exposure limit check re-run; the money comes from outside the book. The subject is a run (run_…) or another scenario's calc_ row (a sale, then this purchase on its result)",
        procedure="mv_added = w × mv_old ÷ (1 − Σ w); weight_i = mv_i ÷ Σ mv; check_limits over the result",
        authority="arithmetic over the run's positions; thresholds from the portfolio's risk_limits; the new name's sector from the desk's company record",
        fails_when="a target weight outside (0, 1), targets summing to 1 or more, a name the desk cannot place in a sector, a name already held (trim or add to it through its weight instead); factor exposures are stated unmeasured",
        executor="book.buy", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "buys": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "weight": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1,
                           "description": "target share of the book AFTER the purchase"}},
                "required": ["ticker", "weight"], "additionalProperties": False}}},
            "required": ["buys"], "additionalProperties": False},
        yields=("issuer_exposures.<T>.weight", "sector_exposures.<S>.weight", "exposure_metrics.portfolio_market_value",
                "limit_checks.<check>.current_value", "count.alerts"),
    ),
)


# ── cross-resource: what one analyst needs from another's family, by name ─────
# A face is a resource family (tools/faces); a need that crosses two is met by a
# measure on the asker's list, never by a wider face.

_CROSS_METHODS: tuple[Method, ...] = (
    Method(
        name="book.position", subject_kind="issuer", family="book",
        reads_as="the name's place in the book", faces=("issuer",),
        describes="a name's own rows in the latest completed run of each book that holds it: its weight, market value and contribution, and the issuer-concentration check on it with its tiers",
        procedure="the run's own figures for the name, read by name; nothing is computed",
        authority="the run's own rows (issuer_exposures, limit_checks)",
        fails_when="no book on this desk holds the name in its latest completed run",
        executor="book.position", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "book": {"type": ["string", "null"], "description": "a port_… or run_… id; omitted = every book that holds the name"}},
            "additionalProperties": False},
        yields=("issuer_exposures.weight", "issuer_exposures.market_value", "issuer_exposures.contribution",
                "limit_checks.current_value", "limit_checks.warning_level", "limit_checks.breach_level"),
    ),
)


METHODS: dict[str, Method] = {
    **_issuer_methods(),
    **{m.name: m for m in _PRICE_METHODS},
    **{m.name: m for m in _BOOK_METHODS},
    **{m.name: m for m in _CROSS_METHODS},
}


# The names a RUN's own tables hold, which `column` and `pick` read. A scenario
# method yields them too, because it re-prices the book — so routing a plain table
# name to `sell` would answer a question nobody asked.
_RUN_TABLE_PREFIXES = ("issuer_exposures.", "sector_exposures.", "limit_checks.",
                       "factor_attributions.", "exposure_metrics.", "risk_alerts.", "count.")


def method_for_yield(name: str) -> Method | None:
    """The method whose result carries a figure of this name, if one does (V37).

    A run's table names are read with `column` and `pick`; a name like
    `portfolio.integration.net_beta.market` is on no table at all — it is what
    `book.analysis` YIELDS — so a refusal that only says the run holds no such
    figure leaves the analyst asking the run for something no run has. Round B's
    Q16 asked four times, in three spellings, and the answer told the reader the
    book's net beta was unavailable while the desk's own method computes it.

    A lookup over the methods' declared yields, with `<risk>` / `<check>` / `<T>`
    standing for a name the caller fills in.
    """
    import fnmatch
    import re as _re
    if name.startswith(_RUN_TABLE_PREFIXES):
        return None                      # a run's own table: column / pick read it
    for m in METHODS.values():
        if m.subject_kind not in ("run", "portfolio"):
            continue                     # the caller asked a BOOK for this name
        if len(m.yields) <= 1 and (not m.yields or m.yields[0] == m.name):
            continue                     # a method that yields one figure under its own name
        for y in m.yields:
            pat = _re.sub(r"<[A-Za-z_]+>", "*", y)
            if fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(name, pat + ".*"):
                return m
    return None


def methods_for(subject_kind: str) -> list[Method]:
    return [m for m in METHODS.values() if m.subject_kind == subject_kind]


def nearest(name: str, n: int = 5) -> list[str]:
    """The registry names closest to an unknown one — a closed lookup, so an
    `unknown_method` refusal can point at `roic` when `return_on_capital` was asked."""
    import difflib
    return difflib.get_close_matches(name, list(METHODS), n=n, cutoff=0.4)


# ── the arithmetic ops compute also takes, named once ────────────────────────

SCALAR_OPS = ("add", "subtract", "multiply", "divide")
SCALE_OP = "scale"          # one operand × a constant (params.factor); the typed calculator's scale
RANK_OP = "rank"
REGRESS_OP = "regress"


# ── how a measure READS, and what the instruments are (V1 step 5) ────────────
#
# The handbook's "how it reads" is rendered from here, never hand-copied. A
# reading says what the ROW cannot: a word that is on the row — a direction, a
# status, a basis, which line stood in — is not repeated, no figure of any run
# or corpus is quoted, and nothing says how a tool is called. (The five pre-V1
# readings carried a corpus statistic, a sign convention and one run's net beta;
# they went with the prompt that rendered them.)

READS: dict[str, str] = {
    "ebit": "EBIT and EBITDA start from net income, adding back interest and tax — not from operating income. Where an "
            "issuer carries large non-operating income the two differ, and a correct EBIT is then mostly non-operating.",
    "free_cash_flow": "Free cash flow has no uniform definition, so the definition is said beside the number. A negative "
                      "figure with capital expenditure above operating cash flow is the capital-expenditure line at work.",
    "total_debt": "Total debt is composed from the debt lines the issuer files, without double-counting a total and its "
                  "parts; the row says what it was built from and what was left out at the date — say it with the figure.",
    "ebit_interest_coverage": "Coverage may rest on the non-operating interest line where an issuer no longer files "
                              "interest expense under its own tag; the row names the line used — say which when the "
                              "coverage is quoted.",
    "gross_margin": "A margin names the revenue line it divided by; an issuer that files revenue under two tags is read "
                    "on the one the desk maps.",
    "price.beta": "Against a rates or credit instrument, a name's beta is its own sensitivity to that risk — the per-name "
                  "figure the book-level factor fit does not give; the book-level fit is over the book's return and says "
                  "nothing per name.",
    "book.analysis": "A net beta is the book's move per unit of the risk it names, and the row says which way the book "
                     "moves. When the fit is collinear the net is quotable and a single leg is not. A risk no factor "
                     "measures is unmeasured, never zero. Room is the distance from a check's reading to its tier, and "
                     "the row says where the check stands.",
    "book.reconcile": "The factor-explained share and the unexplained share sum to one by construction; a share is not a "
                      "return and not a loss.",
    "issuer_exposures.weight": "A weight is a share of its own book's market value and of nothing else: a tier in dollars "
                               "is the book's market value times the tier, and two books' weights are compared by "
                               "difference, never summed.",
    "issuer_exposures.contribution": "A day's contribution to the book's return is not a sensitivity. A name's rate or "
                                     "credit sensitivity is its beta to the rates or credit instrument; a beta that "
                                     "cannot be fitted is unmeasured, never zero.",
}

# The factor instruments: what each IS. The model knows what an S&P 500 ETF is;
# it is told which instrument stands for which risk on this desk, and nothing
# about how a coefficient is signed — the row says which way the book moves.
INSTRUMENTS: tuple[tuple[str, str, str], ...] = (
    ("SPY", "the S&P 500 ETF", "the broad US equity market"),
    ("QQQ", "the Nasdaq-100 ETF", "US growth and technology"),
    ("IWM", "the Russell 2000 ETF", "US small caps"),
    ("TLT", "the 20+ year Treasury ETF", "long rates: it carries duration directly"),
    ("HYG", "the high-yield corporate bond ETF", "credit spreads: it carries spread directly"),
    ("GLD", "the gold ETF", "gold, a risk-off proxy"),
    ("USO", "the oil ETF", "oil and energy"),
)

for _key in READS:
    if _key not in METHODS and _key not in _COLUMN_NAMES:
        raise RuntimeError(f"a reading for {_key!r}, which is neither a measure nor a declared column")


def metrics_for(face: str) -> list[Method]:
    """The measures one analyst may ask for by name — its `metric` tool's enum."""
    if face not in FACES:
        raise ValueError(f"face {face!r} is not one of {FACES}")
    return [m for m in METHODS.values() if face in m.faces]
