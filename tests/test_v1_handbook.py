"""V1 step 5 (docs/IMPLEMENTATION_PLAN_V1.md §2.5): the handbook — three chapters,
six sections, five things it never says. Every ban is a scan, so "one more
sentence in the handbook" cannot quietly be the fix again.
"""

from __future__ import annotations

import re

import pytest

from exposure_workbench.analytics import handbook as H
from exposure_workbench.analytics import registry as R
from exposure_workbench.tools import primitives as P

SECTIONS = ("1. THE QUESTIONS", "2. THE MEASURES", "3. HOW THEY READ", "4. COMPARE AND CLOSE",
            "5. WHAT THE DESK HOLDS", "6. POLICY")


def _written(c: H.Chapter) -> list[str]:
    """Every sentence a person WROTE in a chapter (sections 1, 4, 5 and the header)."""
    out = [c.answers, c.data, *c.holds, *[what for what, _why in c.absent]]
    for t in c.topics:
        out += [t.name, *t.asked, *t.compare, *t.close]
    return out


ALL_WRITTEN = [(c.analyst, s) for c in H.CHAPTERS.values() for s in _written(c)]
RENDERED = {a: H.chapter_text(a) for a in H.ANALYSTS}


# ── the shape ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("analyst", H.ANALYSTS)
def test_a_chapter_has_six_sections_in_order(analyst):
    text = RENDERED[analyst]
    at = [text.index(s) for s in SECTIONS]
    assert at == sorted(at) and len(set(at)) == 6


def test_there_are_three_chapters_and_they_are_the_three_faces():
    assert tuple(H.CHAPTERS) == H.ANALYSTS == R.FACES == P.FACES


@pytest.mark.parametrize("analyst", H.ANALYSTS)
def test_sections_two_three_and_six_come_from_the_registry(analyst):
    text = RENDERED[analyst]
    for m in R.metrics_for(analyst):
        assert f"- {m.reads_as}: {m.describes}" in text, m.name
    for key in H._read_keys(analyst):
        assert R.READS[key] in text
    for p in R.POLICY_ABSENCES:
        assert p["text"] in text


# ── ban 1: no call syntax, parameter values, key names or programs ───────────

_VERBS = [v for face in P.FACES for v in P.FACE_TOOLS[face]] + ["submit"]
_SYNTAX = re.compile(r"[{}$`]|\b\w+\(|\b[a-z]+_[a-z_]+\b|\bf_|\br_|\bcalc_|\brun_|\bport_")


@pytest.mark.parametrize("analyst,sentence", ALL_WRITTEN)
def test_no_written_sentence_holds_call_syntax_or_a_key(analyst, sentence):
    assert not _SYNTAX.search(sentence), sentence


@pytest.mark.parametrize("analyst", H.ANALYSTS)
def test_no_chapter_names_a_verb_or_a_measures_key(analyst):
    text = RENDERED[analyst]
    for verb in (v for v in _VERBS if "_" in v):
        assert verb not in text
    keys = [m.name for m in R.METHODS.values() if "_" in m.name or "." in m.name]
    assert not [k for k in keys if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", text)]


# ── ban 2: no output conventions ─────────────────────────────────────────────

# "equity at or below zero makes ROE meaningless" is a PRECONDITION of a measure, stated by
# the registry; what is banned is teaching how an OUTPUT's sign or unit reads.
_CONVENTION = re.compile(r"(?<!at or )below zero|above zero|is negative|negative means|a negative\b.*\bmeans|positive means|"
                         r"is a fraction|as a fraction|the sign of|signed|0\.\d+|\bmeans the check\b|long equities|"
                         r"net short|not short", re.I)


@pytest.mark.parametrize("analyst", H.ANALYSTS)
def test_no_chapter_teaches_how_to_read_a_sign_a_unit_or_a_field(analyst):
    found = _CONVENTION.findall(RENDERED[analyst])
    assert not found, found


def test_the_meaning_layer_teaches_no_convention_either():
    assert not _CONVENTION.findall(H.meaning_layer())


# ── ban 3: no rule of the answer check ───────────────────────────────────────

_CHECK_RULES = re.compile(r"superlative|bracket|\bthe ledger\b|written exactly|is refused unless|the answer check|"
                          r"by eye|rests on a rank", re.I)


@pytest.mark.parametrize("analyst", H.ANALYSTS)
def test_no_chapter_repeats_a_rule_the_answer_check_enforces(analyst):
    assert not _CHECK_RULES.findall(RENDERED[analyst])


# ── ban 4: no live data ──────────────────────────────────────────────────────

_ALLOWED_CAPS = {"EBIT", "EBITDA", "ROE", "ROA", "ROIC", "NOPAT", "SEC", "US", "ETF", "OLS", "CFA", "NYU"}


@pytest.mark.parametrize("analyst,sentence", ALL_WRITTEN)
def test_no_written_sentence_holds_a_figure_or_a_ticker(analyst, sentence):
    assert not re.search(r"\d", sentence), f"a digit in the handbook's own prose: {sentence!r}"
    caps = set(re.findall(r"\b[A-Z]{2,5}\b", sentence)) - _ALLOWED_CAPS
    assert not caps, f"{caps}: a ticker as a subject is live data"


def test_a_reading_quotes_no_figure_of_any_run_or_corpus():
    for key, text in R.READS.items():
        assert not re.search(r"\d", text), key


# ── ban 5: no sentence twice ─────────────────────────────────────────────────

def test_no_sentence_is_written_twice():
    seen: dict[str, str] = {}
    for analyst, sentence in ALL_WRITTEN:
        key = re.sub(r"\W+", " ", sentence).strip().lower()
        if len(key.split()) < 5:
            continue                    # a topic's name is a label, not a sentence
        assert key not in seen, f"{sentence!r} is in both {seen.get(key)} and {analyst}"
        seen[key] = analyst
    assert len(set(R.READS.values())) == len(R.READS)


# ── can be asked ⇔ can be answered ───────────────────────────────────────────

def test_every_question_has_a_way_to_compare_and_close():
    for c in H.CHAPTERS.values():
        for t in c.topics:
            assert t.asked and t.compare and t.close, f"{c.analyst} / {t.name}"


def test_every_topic_turns_on_measures_of_its_own_face_or_on_its_own_reads():
    # a topic with no measure is answered from the family's raw read (a book's
    # tables, a filing's text): the analyst has that verb and no other family's
    raw = {"issuer": "filings_read", "market": "prices_read", "risk": "book_read"}
    for c in H.CHAPTERS.values():
        mine = {m.name for m in R.metrics_for(c.analyst)}
        assert raw[c.analyst] in P.FACE_TOOLS[c.analyst]
        for t in c.topics:
            assert set(t.measures) <= mine


def test_a_chapter_cannot_turn_on_another_familys_measure():
    with pytest.raises(ValueError):
        H.Chapter("market", "x", "a", "d", topics=(H.Topic("t", ("a",), ("c",), ("z",), measures=("roe",)),),
                  holds=(), absent=())


def test_every_measure_on_a_face_is_reachable_from_some_topic_or_is_the_panel():
    for c in H.CHAPTERS.values():
        turned_on = {k for t in c.topics for k in t.measures}
        unreachable = {m.name for m in R.metrics_for(c.analyst)} - turned_on - {"issuer.panel"}
        # a formula that is only an INPUT of another (EBIT of coverage) needs no topic of its own
        inputs = {i for m in R.metrics_for(c.analyst) for i in m.inputs}
        assert unreachable <= inputs | {"invested_capital", "nopat", "quick_assets", "debt_to_operating_cash_flow"}, unreachable


# ── the lead's view ──────────────────────────────────────────────────────────

def r_asked(roster: list[dict]) -> list[str]:
    return [a for r in roster for a in r["can_be_asked"]]


def test_the_roster_is_three_entries_with_no_vocabulary():
    roster = H.roster()
    assert [r["analyst"] for r in roster] == list(H.ANALYSTS)
    said = [*[r["answers"] for r in roster], *r_asked(roster), *[a["what"] for r in roster for a in r["absent"]]]
    assert not [s for s in said if _SYNTAX.search(s)]
    assert all(r["can_be_asked"] and r["absent"] for r in roster)


def test_the_meaning_layer_holds_readings_and_policy_and_no_key():
    layer = H.meaning_layer()
    assert all(text in layer for text in R.READS.values())
    assert all(p["text"] in layer for p in R.POLICY_ABSENCES)
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", layer), "a measure key or a verb in the lead's layer"


# ── the sixteen desk rules each have one home ────────────────────────────────

RULE_PHRASES = {
    "start from net income": "registry.READS",
    "no uniform definition": "registry.READS",
    "refused for a financial issuer": "issuer §5",
    "quoted from the filing's own sentences": "issuer §5",
    "said to be in preparation": "issuer §5",
    "share of its own book's market value": "registry.READS",
    "carries duration directly": "registry.INSTRUMENTS",
    "is not a sensitivity": "registry.READS",
    "does not re-fit betas": "risk §5",
    "withheld pending validation": "risk §5",
    "the desk fixes none": "risk §4",
    "The desk does not forecast": "policy",
    "No measure carries a threshold": "policy",
    "never an estimate": "policy",
    "level and slope": "issuer §4",
}


@pytest.mark.parametrize("phrase", sorted(RULE_PHRASES))
def test_a_desk_rule_lives_in_exactly_one_place(phrase):
    source = "\n".join([*(s for _a, s in ALL_WRITTEN), *R.READS.values(),
                        *(f"{t} {w} {r}" for t, w, r in R.INSTRUMENTS), *(p["text"] for p in R.POLICY_ABSENCES)])
    assert source.count(phrase) == 1, f"{phrase!r} ({RULE_PHRASES[phrase]}): written {source.count(phrase)} times"
