"""Numeric verification (V3-A1) — a number in PROSE must come from evidence.

V15: this is the v1 path. The block exit (services/resolver.py) resolves names
against the table and never extracts a number from text; what remains here
serves the daily report — prose, server-assembled evidence set, no citations —
and the read-time faithfulness eval over v1 answers. The value resolvers moved
to services/quantities.py, the one namer; what is re-exported below is so the
report gate and its tests read as they always have.

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
     refusing, and it multiplies every acceptance window by five. Every unit here
     is derivable — from the fact's `unit` column, from the calc `operation`
     name, from which column of which run child table — so it is derived, and
     only PERCENT<->RATIO converts, by an exact factor of 100. Measured on 95
     real numbers: last-digit corruption accepted 53.7% under the scaling family,
     3.2% under this rule.

     What this does NOT close is confusion WITHIN a class, and it is worth being
     exact about that rather than implying otherwise. One live risk_alerts row
     carries current_value 0.158, limit_value 0.15 and utilization 0.792 at once,
     and "AAPL is at 15.8% of its limit" is ACCEPTED — 0.158 is one of the three
     numbers that row holds — when the utilization is 79.2%. A1 checks that a
     number exists in the cited evidence; it does not read the sentence around
     it. The limit is recorded in V3_COVERAGE, and the test below asserts what
     actually happens rather than what would be nicer to claim.

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
     the sign" in the module whose job is refusing. Two spellings joined later:
     a minus written as U+2212 (which used to match from the '$', dropping the
     sign — a loss read as a gain) and a sign inside the currency mark,
     "$-141,973" (which used to break the money pattern and fall through as an
     unchecked COUNT). Both are ways of writing the same sign, so both
     normalise; what a sign may MEAN is unchanged.

Extraction and matching are pure functions and testable without a database;
resolve_cited_values() is the only part that reads one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import quantities as _qn

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
# The second branch is the leading-zero-less decimal: without it ".5%" was read
# as "5%", because the literal had to begin on a digit and the re-parse started
# at the first one it found. A number silently ten times too big is worse than a
# number that goes unextracted.
_LIT = r"(?:\d(?:[\d,]*\d)?(?:\.\d+)?|\.\d+)"

# Anything that marks the number as a measurement. Used as a negative lookahead
# by the designator exemption: "H200" is a name, "AAPL 15.8%" is a claim, and the
# only thing separating them is what follows the digits.
_UNIT_MARKER = rf"(?!\.\d)(?!\s*%)(?!\s*[xX]\b)(?!\s*(?:{_SCALE_ALT})\b)"

# Names that contain a space AND digits. There is no shape that tells "S&P 500"
# from "AAPL 5000" — both are a capitalised word followed by digits — so the
# spaced ones are ENUMERATED rather than described, which is the rule the whole
# exemption set is built on. Adding a name is an edit to this tuple plus a test.
# Matched case-insensitively: these are proper names, and lowercasing one does
# not turn it into a measurement.
_SPACED_DESIGNATORS = (
    "S&P 500", "S&P 400", "S&P 600",
    "Nasdaq 100", "Russell 1000", "Russell 2000", "Russell 3000",
    "Fortune 500", "Microsoft 365", "Dow 30",
)
_SPACED_ALT = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in _SPACED_DESIGNATORS)

# A scale word, with the boundary that stops "M&A" and "T-bills" from being read
# as millions and trillions: the letter is a scale only when it is not the head
# of a compound. A hyphen followed by a LETTER starts one ("T-bills"); a hyphen
# followed by a digit is a range ("$5B-10B"), and blocking that would read the
# first figure as five dollars — the same class of silent misread the
# case-insensitivity fix closed. Used by the scaled patterns and by the year
# exemption, which needs it to tell "1950 million" from "in 1950".
_SCALE_WORD = rf"(?i:{_SCALE_ALT})\b(?:(?![&])(?!-[A-Za-z]))"

_EXEMPTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, flags))
    for name, pattern, flags in (
        # An id token, whole. Must come first: it swallows the digits inside it.
        ("id", rf"\b(?:{'|'.join(_ID_PREFIXES_ANY)})_[A-Za-z0-9_]{{3,}}\b", 0),
        # SEC accession, e.g. 0000320193-24-000123
        ("accession", r"\b\d{10}-\d{2}-\d{6}\b", 0),
        ("date_iso", r"\b\d{4}-\d{2}-\d{2}\b", 0),
        # "March 28, 2026" and the bare "quarter ended March 28". The year is
        # optional because the corpus says the old designator pattern was the
        # only thing covering the bare form — accidentally, and it is gone. The
        # day is closed with \b so the pattern cannot back off to "March 1" and
        # leave "5%" behind, and _UNIT_MARKER keeps "In March 15% of revenue"
        # a claim rather than a date.
        ("date_long",
         r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b"
         rf"(?:,\s*\d{{4}}\b)?{_UNIT_MARKER}", 0),
        # 10-K, 10-Q, 8-K, 20-F, S-1 — a form name, not a quantity.
        ("form_type", r"\b(?:10-[KQ]|8-K|20-F|6-K|S-[13]|DEF\s?14A)\b", 0),
        # A regulation reference is a CITATION, not a claim about the world, and
        # refusing it pointed the wrong way. This desk's whole argument is that
        # the definition travels with the number because the regulator requires
        # it — and "C&DI 103.02", the section that defines EBIT, extracted as
        # 103.02 and was refused. Measured on a real turn (sess_6acc3b20069d):
        # asked why EBIT is computed that way, the model could only reach for
        # "the formula returned by the issuer panel". "Item 1A" leaked as 1 and
        # "Rule 17a-4" as 17 and 4, so a filings answer could not name the item
        # it had just read either.
        #
        # Anchored on the naming word, like confidence_level: a bare 103.02
        # elsewhere is still a claim, and the trailing _UNIT_MARKER keeps
        # "Item 3 15%" from swallowing the percentage.
        ("regulation_ref",
         r"\b(?:C&DI|Item|Rule|Reg(?:ulation)?|Section|§|ASC|ASU|IFRS|IAS|SFAS)\s*"
         rf"\d+[0-9A-Za-z]*(?:[.\-][0-9A-Za-z]+)*\b{_UNIT_MARKER}", re.IGNORECASE),
        ("period_label", r"\b(?:[QH][1-4]|FY\d{2,4}|CY\d{2,4})\b", 0),
        # A product whose name ENDS IN DIGITS, with nothing between them: H200,
        # GB200, RTX4090, S&P500. Attachment is what says "name" — a space is
        # not, which is the hole this replaced. The old pattern accepted any
        # capitalised word followed by digits, so "AAPL 5000" and "Backlog 2500"
        # were read as product names and never checked, and a reply made
        # entirely of share counts extracted to nothing and passed the
        # citations-required gate untouched. _UNIT_MARKER is what stops even the
        # attached form from eating a claim.
        ("designator_attached", rf"\b[A-Z][A-Za-z&.]{{0,14}}\d{{2,4}}\b{_UNIT_MARKER}", 0),
        # ...and the names that do carry a space, enumerated (see above).
        ("designator_spaced", rf"\b(?:{_SPACED_ALT})\b{_UNIT_MARKER}", re.IGNORECASE),
        # "over the last 3 months", "a 1-year relative return"
        ("duration", r"\b\d{1,3}[-\s](?:day|week|month|quarter|year)s?\b", 0),
        # The same thing abbreviated and attached: "30d Annualised Vol",
        # "60d", "1y return". The separator-and-full-word form above does not
        # reach it, and the exposure report's own headings are written this way —
        # so every report carried a guaranteed false rejection of the window
        # label in its volatility line. _UNIT_MARKER is what keeps "30d" a label
        # while leaving "30 %" a claim.
        ("duration_abbrev", rf"\b\d{{1,3}}[dwmy]\b{_UNIT_MARKER}", 0),
        # A confidence level is a PARAMETER of the measure, not a measurement:
        # "VaR (95%, 1d)", "1-day 95% VaR", "95% confidence". Enumerated to the
        # three levels anyone quotes and required to sit against the word it
        # parameterises, because a bare "95%" elsewhere in a report is a claim
        # about the book and must still be checked.
        ("confidence_level",
         r"\b(?:90|95|97\.5|99)%\s*(?:VaR|ES|CVaR|confidence|CI)\b"
         r"|\b(?:VaR|ES|CVaR)\s*\(?\s*(?:90|95|97\.5|99)%", re.IGNORECASE),
        # A standalone calendar year. The lookahead rejects "2024.5" but must NOT
        # reject a year that ends a sentence — "shipping in 2027." is still a year.
        # A currency mark in front or a scale word behind means it was never a
        # year: "$2000" is a price and "1950 million" is a quantity, and both
        # were silently exempted as years by the first three guards alone.
        ("year", rf"(?<![\d.$])\b(?:19|20)\d{{2}}\b(?![\d%])(?!\.\d)(?!\s*{_SCALE_WORD})", 0),
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
#
# U+2212, the typographic minus, is another way of WRITING a sign — the same
# class of edit as "percent" beside "%", never a widening of the tolerance.
# Before it was accepted here, "−$141,973" matched from the '$' and the sign was
# silently dropped: a loss read as a gain, produced by the gate's own parsing
# rather than by the model, on the one corruption this domain punishes hardest.
# The lookbehind covers it the same way — "15−20%" is still a range.
_SIGN = r"(?:(?<![\w.])[+\-−])?"

# A sign written INSIDE the currency mark. "$-141,973" is malformed, but the
# money patterns failing at the '-' did not refuse it — the bare pattern picked
# the digits up as a COUNT, sign intact and unit checking silently bypassed for
# exactly the spelling most likely to accompany a malformed claim. Closed to
# the one position between '$' and the digits; no lookbehind, because the '$'
# it must follow already rules out the range and name shapes.
_SIGN_AFTER_CURRENCY = r"[+\-−]?"

# Ordered longest-form-first: "$111.184 billion" must not be read as "$111.184".
# IGNORECASE on the scale forms because "$81.615B" and "$111.184 billion" are the
# same claim written two ways — and a case-sensitive alternation silently read
# the first as eighty-one dollars.
_NUMBER_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, flags))
    for name, pattern, flags in (
        ("money_scaled", rf"{_SIGN}\$\s?{_SIGN_AFTER_CURRENCY}{_LIT}\s*{_SCALE_WORD}", re.IGNORECASE),
        ("money_plain", rf"{_SIGN}\$\s?{_SIGN_AFTER_CURRENCY}{_LIT}", 0),
        # "82 percent" is the same claim as "82%", and a filing that spells it out
        # made it uncitable in BOTH spellings: written as words it typed as a
        # COUNT and fell under the three-digit floor for bare numbers, written
        # with the sign it looked for a "%:82" key the passage does not contain.
        # LLY's 10-K states its revenue concentration that way — "collectively
        # accounted for 82 percent of our total revenues in 2025" — and the gate
        # refused the verbatim quotation, which the answer then replaced with "a
        # small set of products accounted for a very large share". 77 of 3078
        # chunks in this corpus spell it out. A closed edit to the pattern, in
        # the terms the module already allows: another way of writing a unit,
        # never a widening of the tolerance.
        ("percent", rf"{_SIGN}{_LIT}\s*(?:%|percent\b)", re.IGNORECASE),
        ("multiple", rf"{_SIGN}{_LIT}\s?x\b", 0),
        ("scaled", rf"{_SIGN}{_LIT}\s*{_SCALE_WORD}", re.IGNORECASE),
        ("bare", rf"{_SIGN}{_LIT}", 0),
    )
)

_DIGITS = re.compile(_LIT)

# Everything a matched surface can hold in front of its first digit: sign(s),
# the currency mark, spaces. Stops at '.' as well as at a digit so that a
# leading-zero-less ".5%" keeps its empty head.
_HEAD = re.compile(r"[^\d.]*")


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
            # negative in the corpus was checked as its own positive. Read from
            # everything in front of the first digit, not surface[0]: the sign
            # may sit inside the currency mark ("$-141,973"), and a minus is a
            # minus whether written as '-' or U+2212.
            head = surface[:_HEAD.match(surface).end()]
            if "-" in head or "−" in head:
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








# ══ resolving what the cited evidence actually holds ═══════════════════════════
# V15-S4: the resolvers live in services/quantities.py — one namer for the table
# the model reads and the values this gate compares against. Re-exported here
# for the report gate and the v1 eval.

EvidenceValue = _qn.EvidenceValue
resolve_cited_values = _qn.resolve_cited_values
quoted_keys = _qn.quoted_keys


def raw_forms(numbers: Iterable[ExtractedNumber]) -> list[str]:
    """The surfaces, deduped BY SPAN, in encounter order — what to show the model."""
    seen: set[tuple[int, int]] = set()
    out: list[str] = []
    for n in sorted(numbers, key=lambda x: x.span):
        if n.span in seen:
            continue
        seen.add(n.span)
        out.append(n.surface)
    return out


# The prose route matches the number AS WRITTEN, unit and all. A bare number
# still needs length: three significant digits.
_MIN_BARE_QUOTED_DIGITS = 3

# Which written class may be compared with which stored class. A bare number
# states no unit, so it may match anything; a percent may only meet a ratio; and
# money may only meet money. This table IS the safety property.
_COMPATIBLE: dict[str, tuple[str, ...]] = {
    PERCENT: (RATIO,),
    MULTIPLE: (RATIO,),
    MONEY: (MONEY,),
    COUNT: (RATIO, MONEY, COUNT),
}


async def resolve_cited_passages(db: AsyncSession, citation_ids: Iterable[str]) -> list[str]:
    """The text of every cited passage, for checking what quotation marks assert."""
    out: list[str] = []
    for cid in citation_ids:
        if cid.startswith(("chunk_", "src_")):
            r = await _qn.of_ref(db, cid)
            if r.text is not None:
                out.append(r.text)
    return out


def _is_quoted(n: ExtractedNumber, quoted: set[str]) -> bool:
    """Whether a cited passage contains this number as the KIND of thing it is."""
    if n.unit_class == PERCENT:
        return f"%:{n.key}" in quoted
    if n.unit_class == MONEY:
        if f"$:{n.key}" in quoted:
            return True
        return (len(n.key.replace(".", "")) >= _MIN_BARE_QUOTED_DIGITS
                and f":{n.key}" in quoted)
    return (len(n.key.replace(".", "")) >= _MIN_BARE_QUOTED_DIGITS
            and f":{n.key}" in quoted)


# ── quoted text (V11-Q) ───────────────────────────────────────────────────────
# The block exit checks quotations in services/resolver.py against the block's
# own cites. This copy serves the v1 eval over stored prose answers.
from exposure_workbench.services.resolver import quoted_spans, verify_quotes  # noqa: E402,F401


def verify(
    numbers: Iterable[ExtractedNumber],
    values: Iterable[EvidenceValue],
    quoted: set[str] | None = None,
) -> list[dict]:
    """Problems, one per number that no cited evidence supports.

    The gate's own entry point, unchanged in signature and in judgement. It
    delegates so that the ONE place a number is decided against evidence stays
    one place; see verify_with_matches for why the other half is wanted.
    """
    return verify_with_matches(numbers, values, quoted)[0]


def verify_with_matches(
    numbers: Iterable[ExtractedNumber],
    values: Iterable[EvidenceValue],
    quoted: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """The same pass, returning what it REFUSED and what it ACCEPTED (V13-S3).

    A number is supported when some compatible evidence value is within half an
    ulp of what was written, or when its digits appear verbatim in a cited
    passage. Each problem carries the nearest compatible value. There is no
    search for a derivation (V11-G, retired in V15: equivalent derivations ran
    to a median of 24 per figure, so the hint named one of many and the model
    followed it).
    """
    quoted = quoted or set()
    values = list(values)
    problems: list[dict] = []
    matches: list[dict] = []

    def _match(n: ExtractedNumber, kind: str, v: EvidenceValue | None = None) -> None:
        matches.append({
            "span": list(n.span), "surface": n.surface, "how": kind,
            **({} if v is None else {"label": v.label, "source_id": v.source_id,
                                     "value": v.value, "unit_class": v.unit_class}),
        })

    for n in numbers:
        if _is_quoted(n, quoted):
            _match(n, "quoted")
            continue
        allowed = _COMPATIBLE.get(n.unit_class, ())
        candidates = [v for v in values if v.unit_class in allowed]
        matched = [v for v in candidates if abs(v.value - n.value) <= n.atol]
        if matched:
            if any(v.not_alone is None for v in matched):
                _match(n, "value", next(v for v in matched if v.not_alone is None))
                continue
            problems.append({
                "number": n.surface,
                "reason": "not_quotable_individually",
                "detail": matched[0].not_alone,
                "matched": [v.label for v in matched],
            })
            continue
        nearest = min(candidates, key=lambda v: abs(v.value - n.value), default=None)
        problems.append({
            "number": n.surface,
            "reason": "not_in_cited_evidence",
            "nearest": None if nearest is None else {"value": nearest.value, "label": nearest.label,
                                                     "id": nearest.source_id},
        })
    return problems, matches
