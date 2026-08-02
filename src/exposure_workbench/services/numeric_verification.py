"""Numeric verification (V3-A1) — a number in an answer must come from evidence.

The citation gate proves an id is real. It says nothing about the NUMBER standing
next to it, and "right citation, wrong number" is the failure a finance desk
cares about most. This module is the other half: extract every substantive number
from generated text, resolve the values the cited evidence actually holds, and
refuse the answer when a number matches none of them.

Three properties are load-bearing, and each replaced something weaker that was
measured against the live corpus first:

  1. UNIT CLASSES, not a scaling family. The tempting rule is "accept the number
     at any magnitude" — {v, v/1e3, v/1e6, v/1e9, v*100}. That is a five-way "I
     do not know the unit", i.e. a fallback in the one module whose whole job is
     refusing. It also opens a real hole: one live risk_alerts row carries
     current_value 0.158, limit_value 0.15 and utilization 0.792 at once, so a
     scale-blind check accepts "at 15.8% of its limit" when the answer is 79.2%.
     Every unit here is derivable — from the fact's `unit` column, from the calc
     `operation` name, from which column of which run child table — so it is
     derived, and only PERCENT<->RATIO converts, by an exact factor of 100.
     Measured on 95 real numbers: last-digit corruption accepted 53.7% under the
     scaling family, 3.2% under this rule.

  2. HALF AN ULP OF THE WRITTEN PRECISION, not a relative tolerance. rtol=0.005
     is simultaneously too tight and too loose: a weight of 0.04061908 written as
     the correct "4.1%" is 0.94% off and would be REFUSED, while rtol on
     "$82.886B" opens a ±$414M window that ACCEPTS a corrupted last digit. The
     tolerance has to follow the digits the model chose to write, and it means
     exactly one thing: the true value must round to what was written. Tools hand
     the model raw floats at full stored precision (portfolio_service._f is
     `float(v)`), so the entire discrepancy budget is the model's own rounding
     for readability — which is precisely what half an ulp measures.

  3. AN ENUMERATED, CLOSED EXEMPTION SET. Years, dates, ids, period labels, form
     types, list ordinals, product designators, durations and accession numbers
     are digits that are not claims. The set is closed: adding a category is an
     edit to _EXEMPTION_PATTERNS plus a test, never a widening of the tolerance.
     A four-category set was tried first and measured 8 guaranteed false
     rejections in seven live answers ("H200", "the S&P 500", "42.4% over the
     last 1 year"), so the categories below are the ones the corpus demanded.

  4. THE SIGN IS PART OF THE NUMBER. Added in V3-R after the adversarial review
     reproduced its absence: the literal pattern begins at a digit, so a matched
     "-" reached the surface and never the value, and "-$81.615B" was checked as
     POSITIVE 81.615 billion. That is a false accept on the one corruption this
     domain punishes hardest — an inverted figure — and, at the same time, a
     false rejection of every negative the database holds: 117 of 127 factor
     contributions are negative, and none of them could be cited. A written sign
     now reaches the value and is matched exactly, which also means a claim that
     carries its sign in a verb ("the factor detracted 0.8%") is refused rather
     than guessed at. Accepting either sign would be a two-way "I do not know
     the sign" in the module whose job is refusing.

Extraction and matching are pure functions and testable without a database;
resolve_cited_values() is the only part that reads one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import (
    CalcLedger,
    ExposureMetrics,
    FactorAttribution,
    FilingChunk,
    FinancialFact,
    IssuerExposure,
    ResearchSource,
    RiskAlert,
    SectorExposure,
)

# ── unit classes ───────────────────────────────────────────────────────────────
# What a number MEANS, so that comparison is between commensurable things. The
# written form determines the class of an extracted number; the schema determines
# the class of an evidence value. Only PERCENT and RATIO interconvert.
PERCENT = "PERCENT"      # canonicalised to a fraction: "16.2%" -> 0.162
RATIO = "RATIO"          # a dimensionless fraction as stored (weights, returns)
MONEY = "MONEY"          # absolute currency units: "$94.9B" -> 9.49e10
COUNT = "COUNT"          # a bare number whose unit the text does not state
MULTIPLE = "MULTIPLE"    # "1.28x"

_SCALES = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}
_SCALE_ALT = "|".join(sorted(_SCALES, key=len, reverse=True))

# Every id prefix minted anywhere in this system, not just the six that can be
# cited. A legitimate zero-citation reply in the live corpus reads "You can
# follow it with run id rrun_0bef53cb5360" — keying the exemption to the citable
# six would refuse it. The tail is [A-Za-z0-9_]{3,} rather than hex because real
# rows include run_seed_prev_01 and run_rvprobe1, and a hex-only pattern leaves
# the trailing "01" behind as a bare number.
_ID_PREFIXES_ANY = (
    "fact", "chunk", "calc", "src", "co", "rrun", "run", "filing", "alert",
    "brief", "msg", "sess", "task", "pack", "step", "port", "pos", "report",
)

# A number literal that cannot end on a thousands separator: "$10,406,776, with"
# must yield "$10,406,776", not a surface with the sentence's comma glued on.
_LIT = r"\d(?:[\d,]*\d)?(?:\.\d+)?"

# Anything that marks the number as a measurement. Used as a negative lookahead
# by the designator exemption: "H200" is a name, "AAPL 15.8%" is a claim, and the
# only thing separating them is what follows the digits.
_UNIT_MARKER = rf"(?!\.\d)(?!\s*%)(?!\s*[xX]\b)(?!\s*(?:{_SCALE_ALT})\b)"

_EXEMPTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, flags))
    for name, pattern, flags in (
        # An id token, whole. Must come first: it swallows the digits inside it.
        ("id", rf"\b(?:{'|'.join(_ID_PREFIXES_ANY)})_[A-Za-z0-9_]{{3,}}\b", 0),
        # SEC accession, e.g. 0000320193-24-000123
        ("accession", r"\b\d{10}-\d{2}-\d{6}\b", 0),
        ("date_iso", r"\b\d{4}-\d{2}-\d{2}\b", 0),
        ("date_long",
         r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4}\b", 0),
        # 10-K, 10-Q, 8-K, 20-F, S-1 — a form name, not a quantity.
        ("form_type", r"\b(?:10-[KQ]|8-K|20-F|6-K|S-[13]|DEF\s?14A)\b", 0),
        ("period_label", r"\b(?:[QH][1-4]|FY\d{2,4}|CY\d{2,4})\b", 0),
        # A product or index whose name contains digits: H200, S&P 500,
        # Nasdaq 100, Microsoft 365, Russell 2000. The capital letter before the
        # digits is what says "name"; _UNIT_MARKER is what stops this from eating
        # the claim in "AAPL 15.8%" — measured: without it, two of the three
        # issuer weights in a real live answer were silently never checked.
        ("designator",
         rf"\b(?:[A-Z][A-Za-z&.]{{0,14}}\s)?[A-Z][A-Za-z&.]{{0,14}}\s?\d{{2,4}}\b{_UNIT_MARKER}", 0),
        # "over the last 3 months", "a 1-year relative return"
        ("duration", r"\b\d{1,3}[-\s](?:day|week|month|quarter|year)s?\b", 0),
        # A standalone calendar year. The lookahead rejects "2024.5" but must NOT
        # reject a year that ends a sentence — "shipping in 2027." is still a year.
        ("year", r"(?<![\d.])\b(?:19|20)\d{2}\b(?![\d%])(?!\.\d)", 0),
        # "1)" / "2." at the start of a line — enumeration, not measurement.
        ("list_ordinal", r"^\s{0,4}\d{1,2}[.)]\s", re.MULTILINE),
    )
)

# A leading sign, and only where a sign is what it is. "15-20%" is a range,
# "COVID-19" is a name and "$5-10B" is a span: in all three the '-' has a word
# character running into it from the left, and none of them is negative. The
# lookbehind therefore sits INSIDE the optional group, so it constrains only the
# case where a sign is actually consumed — in front of the whole pattern it would
# also refuse "US$5B", whose match starts on a character preceded by a letter,
# and silently demote it to a unitless count.
_SIGN = r"(?:(?<![\w.])[+-])?"

# Ordered longest-form-first: "$111.184 billion" must not be read as "$111.184".
# IGNORECASE on the scale forms because "$81.615B" and "$111.184 billion" are the
# same claim written two ways — and a case-sensitive alternation silently read
# the first as eighty-one dollars.
_NUMBER_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, flags))
    for name, pattern, flags in (
        ("money_scaled", rf"{_SIGN}\$\s?{_LIT}\s*(?:{_SCALE_ALT})\b", re.IGNORECASE),
        ("money_plain", rf"{_SIGN}\$\s?{_LIT}", 0),
        ("percent", rf"{_SIGN}{_LIT}\s*%", 0),
        ("multiple", rf"{_SIGN}{_LIT}\s?x\b", 0),
        ("scaled", rf"{_SIGN}{_LIT}\s*(?:{_SCALE_ALT})\b", re.IGNORECASE),
        ("bare", rf"{_SIGN}{_LIT}", 0),
    )
)

_DIGITS = re.compile(_LIT)


@dataclass(frozen=True)
class ExtractedNumber:
    """One substantive number, as written and as meant.

    value/atol are CANONICAL for the unit class (a percent is stored as its
    fraction) so that comparison never has to re-parse; `surface` keeps the
    verbatim text so an error message can quote the model back to itself.
    """

    span: tuple[int, int]
    surface: str
    value: float
    unit_class: str
    atol: float
    key: str            # digits as written, unsigned, separators stripped — the prose probe


def _decimals(literal: str) -> int:
    return len(literal.split(".")[1]) if "." in literal else 0


def _exempt_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for _name, pattern in _EXEMPTION_PATTERNS:
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _overlaps(span: tuple[int, int], spans: Iterable[tuple[int, int]]) -> bool:
    lo, hi = span
    return any(lo < e and s < hi for s, e in spans)


def extract_numbers(text: str) -> list[ExtractedNumber]:
    """Every substantive number in `text`, in encounter order.

    A number is substantive unless it falls inside an exempt span (an id, a date,
    a form name, a duration...). Overlapping matches resolve longest-first, so
    "$111.184 billion" yields one number rather than three.
    """
    if not text:
        return []

    exempt = _exempt_spans(text)
    taken: list[tuple[int, int]] = []
    found: list[ExtractedNumber] = []

    for kind, pattern in _NUMBER_PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if _overlaps(span, exempt) or _overlaps(span, taken):
                continue
            surface = m.group(0)
            lit_match = _DIGITS.search(surface.replace("$", ""))
            if lit_match is None:
                continue
            literal = lit_match.group(0).replace(",", "")
            try:
                magnitude = float(literal)
            except ValueError:
                continue
            # The sign is read off the SURFACE, because the literal cannot carry
            # it: _LIT begins at a digit, and _DIGITS re-parses the surface from
            # the first one. That gap is the whole defect this closes — every
            # negative in the corpus was checked as its own positive.
            if surface.startswith("-"):
                magnitude = -magnitude

            decimals = _decimals(literal)
            scale = 1.0
            if kind in ("money_scaled", "scaled"):
                word = re.search(rf"({_SCALE_ALT})\b", surface, re.IGNORECASE)
                if word:
                    scale = _SCALES[word.group(1).lower()]

            if kind == "percent":
                unit_class, value = PERCENT, magnitude / 100.0
                # Half an ulp of the LAST WRITTEN DIGIT, carried into the same
                # canonical unit as the value: "25%" tolerates ±0.005 as a
                # fraction, "16.187%" tolerates ±0.000005.
                atol = 0.5 * (10 ** -decimals) / 100.0
            elif kind in ("money_scaled", "money_plain"):
                unit_class, value = MONEY, magnitude * scale
                atol = 0.5 * (10 ** -decimals) * scale
            elif kind == "multiple":
                unit_class, value = MULTIPLE, magnitude
                atol = 0.5 * (10 ** -decimals)
            else:
                unit_class, value = COUNT, magnitude * scale
                atol = 0.5 * (10 ** -decimals) * scale

            taken.append(span)
            found.append(ExtractedNumber(
                # `key` is the literal, which is unsigned by construction, and
                # deliberately stays that way: it feeds the prose route, and a
                # filing table writes a negative as "(16,450)" as readily as
                # "-16,450". The sign is checked on the structured route.
                span=span, surface=surface.strip(), value=value,
                unit_class=unit_class, atol=atol, key=literal,
            ))

    found.sort(key=lambda n: n.span)
    return found


# The prose route matches the number AS WRITTEN, unit and all, not its bare
# digits. Found in live acceptance: a brief claimed H200 shipments face "a 25%
# import tariff" citing two chunks containing neither "H200" nor "tariff", and it
# was accepted because "25" occurs somewhere in one of them — nine of that
# chunk's seventeen digit keys are two characters or shorter. Requiring "25%" to
# appear as a percentage kills the coincidence without refusing the very common
# "revenue grew 17%" quoted straight out of a filing, which a bare minimum-length
# rule did refuse (measured: six such figures in three briefs).
#
# A bare number still needs length, because there is no unit to make it
# improbable: three significant digits.
_MIN_BARE_QUOTED_DIGITS = 3


def quoted_keys(text: str) -> set[str]:
    """The digit sequences a passage literally contains.

    The prose route, used for chunk_ and src_ citations. It is an EXISTENCE check
    on the digits, not a magnitude check: a filing table's scale ("in millions")
    lives in a header the chunker may not have kept, so the passage cannot always
    say what its own numbers mean. It cannot speak to SIGN either, for a sister
    reason — a table writes a negative as "(16,450)" at least as often as
    "-16,450", so requiring the minus to appear verbatim would refuse the
    ordinary case. Both are recorded as A1's irreducible limits rather than
    papered over: a scale- and sign-blind accept is still strictly narrower than
    accepting any number that has a citation attached, which is what happened
    before, and the structured route (calc_, fact_, alert_, run_) checks both
    exactly.
    """
    text = text or ""
    keys: set[str] = set()
    for m in _DIGITS.finditer(text):
        digits = m.group(0).replace(",", "")
        before = text[max(0, m.start() - 2):m.start()]
        after = text[m.end():m.end() + 2]
        if after.lstrip().startswith("%"):
            keys.add(f"%:{digits}")
        elif "$" in before:
            keys.add(f"$:{digits}")
        keys.add(f":{digits}")          # the untagged form, for bare numbers
    return keys


def raw_forms(numbers: Iterable[ExtractedNumber]) -> list[str]:
    """The surfaces, deduped BY SPAN, in encounter order — what to show the model.

    By span rather than by value: "revenue grew to $94.9B from $81.6B, up 16.2%"
    must report three numbers, and two different spans holding the same magnitude
    are still two claims.
    """
    seen: set[tuple[int, int]] = set()
    out: list[str] = []
    for n in sorted(numbers, key=lambda x: x.span):
        if n.span in seen:
            continue
        seen.add(n.span)
        out.append(n.surface)
    return out


# ══ resolving what the cited evidence actually holds ═══════════════════════════
# Everything below this line touches the database. Above it is pure.


@dataclass(frozen=True)
class EvidenceValue:
    """One number a cited row actually holds, with what it means and where from.

    `label` is the correction signal: "you wrote 15.8%, the nearest thing this
    alert holds is 79.2% (utilization)" is actionable, where a bare float is not.
    """

    value: float
    unit_class: str
    label: str
    source_id: str


# Which written class may be compared with which stored class. A bare number
# states no unit, so it may match anything; a percent may only meet a ratio; and
# money may only meet money. This table IS the safety property — see the module
# docstring for the live row that a scale-blind rule mis-reads.
_COMPATIBLE: dict[str, tuple[str, ...]] = {
    PERCENT: (RATIO,),
    MULTIPLE: (RATIO,),
    MONEY: (MONEY,),
    COUNT: (RATIO, MONEY, COUNT),
}

# A calc's unit is fully determined by its operation name and nothing else.
# Ratio-valued operations divide two commensurable things or measure change;
# everything else carries the unit of the metric underneath, which for every
# citable fact in this database is USD.
_CALC_RATIO_OPS = frozenset({
    "change.yoy", "change.qoq", "change.pct", "combine.divide",
    "stat.cagr", "window_return", "window_return.relative",
})

# run_ resolves through its children: exposure_runs itself has no numeric column.
# (model, column, unit_class) — the label names the row so the model can tell
# which of ten issuer weights it nearly matched.
_RUN_CHILDREN: tuple[tuple[type, tuple[str, ...], tuple[str, ...], str | None], ...] = (
    (ExposureMetrics,
     ("portfolio_market_value", "daily_pnl", "gross_exposure", "net_exposure"),
     ("daily_return", "gross_exposure_pct", "net_exposure_pct", "rolling_vol_30d",
      "rolling_vol_60d", "var_95_1d", "expected_shortfall_95", "max_drawdown",
      "stress_loss_tech", "stress_loss_rates", "stress_loss_credit", "stress_loss_market"),
     None),
    (IssuerExposure, ("market_value", "daily_pnl"),
     ("weight", "weight_change", "daily_return"), "ticker"),
    (SectorExposure, ("market_value",), ("weight", "weight_change"), "sector"),
    (FactorAttribution, (), ("beta", "factor_return", "contribution", "r_squared"), "factor_name"),
)


def _numbers_in(payload, prefix: str, out: list, source_id: str) -> None:
    """Numeric leaves of a JSONB blob, as COUNT values.

    Used for calc quality_flags, which is where a real live answer's "the series
    only returned 2 recent points" comes from: the 2 is genuinely in the cited
    calc row, under insufficient_history.have.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            _numbers_in(v, f"{prefix}.{k}", out, source_id)
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            _numbers_in(v, f"{prefix}[{i}]", out, source_id)
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        out.append(EvidenceValue(float(payload), COUNT, prefix, source_id))


async def _from_calc(db: AsyncSession, cid: str) -> tuple[list[EvidenceValue], set[str]]:
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == cid))).scalar_one_or_none()
    if row is None:
        return [], set()
    unit = RATIO if row.operation in _CALC_RATIO_OPS else MONEY
    result = row.result or {}
    values: list[EvidenceValue] = []
    if "points" in result:
        for p in result.get("points") or []:
            v = (p or {}).get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.append(EvidenceValue(
                    float(v), unit, f"{row.operation}@{(p or {}).get('period_end')}", cid))
    v = result.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        values.append(EvidenceValue(float(v), unit, row.operation, cid))
    _numbers_in(result.get("quality_flags") or {}, "quality_flags", values, cid)
    return values, set()


async def _from_fact(db: AsyncSession, fid: str) -> tuple[list[EvidenceValue], set[str]]:
    row = (await db.execute(select(FinancialFact).where(FinancialFact.id == fid))).scalar_one_or_none()
    if row is None or row.value is None:
        return [], set()
    # Facts are stored in absolute units with no scaling applied anywhere; `unit`
    # is the only magnitude-bearing column. Every fact that can reach a tool
    # result is USD (the non-USD rows have no normalized_metric, and the loader
    # filters on it), so anything else is reported as unitless rather than
    # guessed at.
    unit = MONEY if (row.unit or "").upper() == "USD" else COUNT
    return [EvidenceValue(float(row.value), unit,
                          f"{row.normalized_metric or row.raw_concept}@{row.period_end}", fid)], set()


async def _from_alert(db: AsyncSession, aid: str) -> tuple[list[EvidenceValue], set[str]]:
    row = (await db.execute(select(RiskAlert).where(RiskAlert.id == aid))).scalar_one_or_none()
    if row is None:
        return [], set()
    out = [
        EvidenceValue(float(getattr(row, col)), RATIO, col, aid)
        for col in ("current_value", "limit_value", "utilization")
        if getattr(row, col) is not None
    ]
    return out, set()


async def _from_run(db: AsyncSession, rid: str) -> tuple[list[EvidenceValue], set[str]]:
    """exposure_runs has no numeric columns — every number lives on a child."""
    out: list[EvidenceValue] = []
    for model, abs_cols, ratio_cols, name_col in _RUN_CHILDREN:
        rows = (await db.execute(select(model).where(model.run_id == rid))).scalars().all()
        for row in rows:
            who = f".{getattr(row, name_col)}" if name_col else ""
            for cols, unit in ((abs_cols, MONEY), (ratio_cols, RATIO)):
                for col in cols:
                    v = getattr(row, col, None)
                    if v is not None:
                        out.append(EvidenceValue(
                            float(v), unit, f"{model.__tablename__}{who}.{col}", rid))
    return out, set()


async def _from_chunk(db: AsyncSession, cid: str) -> tuple[list[EvidenceValue], set[str]]:
    row = (await db.execute(select(FilingChunk).where(FilingChunk.id == cid))).scalar_one_or_none()
    return ([], quoted_keys(row.text)) if row is not None else ([], set())


async def _from_source(db: AsyncSession, sid: str) -> tuple[list[EvidenceValue], set[str]]:
    row = (await db.execute(select(ResearchSource).where(ResearchSource.id == sid))).scalar_one_or_none()
    if row is None:
        return [], set()
    return [], quoted_keys(f"{row.title or ''} {row.snippet or ''}")


# Data, not an if-chain: the symmetry test asserts this covers every prefix the
# citation gate accepts, so a newly citable prefix cannot arrive without a value
# source and be reported as the model's fault.
_VALUE_SOURCES = {
    "calc_": _from_calc,
    "fact_": _from_fact,
    "alert_": _from_alert,
    "run_": _from_run,
    "chunk_": _from_chunk,
    "src_": _from_source,
}


async def resolve_cited_values(
    db: AsyncSession, citation_ids: Iterable[str]
) -> tuple[list[EvidenceValue], set[str]]:
    """Every number the cited rows hold, plus the digits their prose contains."""
    values: list[EvidenceValue] = []
    quoted: set[str] = set()
    for cid in citation_ids:
        for prefix, fn in _VALUE_SOURCES.items():
            if cid.startswith(prefix):
                v, q = await fn(db, cid)
                values.extend(v)
                quoted |= q
                break
    return values, quoted


def _is_quoted(n: ExtractedNumber, quoted: set[str]) -> bool:
    """Whether a cited passage contains this number as the KIND of thing it is."""
    if n.unit_class == PERCENT:
        return f"%:{n.key}" in quoted
    if n.unit_class == MONEY:
        # A money claim may be quoted with or without the sign in the source
        # ("$111.184 billion" vs a table cell reading 111,184), so both count —
        # but only at bare-number length when the sign is absent.
        if f"$:{n.key}" in quoted:
            return True
        return (len(n.key.replace(".", "")) >= _MIN_BARE_QUOTED_DIGITS
                and f":{n.key}" in quoted)
    return (len(n.key.replace(".", "")) >= _MIN_BARE_QUOTED_DIGITS
            and f":{n.key}" in quoted)


def verify(
    numbers: Iterable[ExtractedNumber],
    values: Iterable[EvidenceValue],
    quoted: set[str] | None = None,
) -> list[dict]:
    """Problems, one per number that no cited evidence supports.

    A number is supported when some compatible evidence value is within half an
    ulp of what was written, or when its digits appear verbatim in a cited
    passage. Each problem carries the nearest compatible value, because the point
    is for the model to re-cite or re-fetch, not to guess again.
    """
    quoted = quoted or set()
    values = list(values)
    problems: list[dict] = []

    for n in numbers:
        if _is_quoted(n, quoted):
            continue
        allowed = _COMPATIBLE.get(n.unit_class, ())
        candidates = [v for v in values if v.unit_class in allowed]
        if any(abs(v.value - n.value) <= n.atol for v in candidates):
            continue
        nearest = min(candidates, key=lambda v: abs(v.value - n.value), default=None)
        problems.append({
            "number": n.surface,
            "reason": "not_in_cited_evidence",
            "nearest": None if nearest is None else {"value": nearest.value, "label": nearest.label,
                                                     "id": nearest.source_id},
        })
    return problems
