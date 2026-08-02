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

Pure functions, no DB, no I/O. resolve_cited_values() adds the only database
dependency and lives below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

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

# Ordered longest-form-first: "$111.184 billion" must not be read as "$111.184".
# IGNORECASE on the scale forms because "$81.615B" and "$111.184 billion" are the
# same claim written two ways — and a case-sensitive alternation silently read
# the first as eighty-one dollars.
_NUMBER_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, flags))
    for name, pattern, flags in (
        ("money_scaled", rf"[+-]?\$\s?{_LIT}\s*(?:{_SCALE_ALT})\b", re.IGNORECASE),
        ("money_plain", rf"[+-]?\$\s?{_LIT}", 0),
        ("percent", rf"[+-]?{_LIT}\s*%", 0),
        ("multiple", rf"[+-]?{_LIT}\s?x\b", 0),
        ("scaled", rf"[+-]?{_LIT}\s*(?:{_SCALE_ALT})\b", re.IGNORECASE),
        ("bare", rf"[+-]?{_LIT}", 0),
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
    key: str            # digits as written, separators stripped — the prose probe


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
                span=span, surface=surface.strip(), value=value,
                unit_class=unit_class, atol=atol, key=literal.lstrip("+-"),
            ))

    found.sort(key=lambda n: n.span)
    return found


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
