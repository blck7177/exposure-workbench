"""V30 Phase B — the claims gate, on a synthetic ledger.

The five reader-visible false statements of the 2026-09-07 battery, each as a
claim the gate must refuse with the named reason; each relation's accept
case; digits in prose under the D3 decision (allowed when the ledger accounts
for them); the rendered shape the web client reads.
"""
from __future__ import annotations

import pytest

from exposure_workbench.services import claims as C
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger

RUN = "run_x"


def _f(kind, measure, **kw):
    return F.fact(kind, measure, **kw)


@pytest.fixture
def led():
    facts = [
        _f(F.SCALAR, "limit_checks.current_value", subject="issuer_concentration:MSFT", unit="RATIO", value=0.1625, as_of="2026-09-04", sources=(RUN,)),
        _f(F.SCALAR, "limit_checks.warning_level", subject="issuer_concentration:MSFT", unit="RATIO", value=0.15, as_of="2026-09-04", sources=(RUN,)),
        _f(F.SCALAR, "limit_checks.breach_level", subject="issuer_concentration:MSFT", unit="RATIO", value=0.20, as_of="2026-09-04", sources=(RUN,)),
        _f(F.SCALAR, "issuer_exposures.weight", subject="MSFT", unit="RATIO", value=0.161, as_of="2026-09-04", params={"node": "w", "label": "MSFT", "rank": 1}, sources=(RUN,)),
        _f(F.SCALAR, "issuer_exposures.weight", subject="JPM", unit="RATIO", value=0.149, as_of="2026-09-04", params={"node": "w", "label": "JPM"}, sources=(RUN,)),
        _f(F.SCALAR, "divide(issuer_exposures.market_value, adv)", subject="MSFT", unit="COUNT", value=0.0006, as_of="2026-09-04", params={"node": "days", "op": "divide"}),
        _f(F.SCALAR, "divide(exposure_metrics.portfolio_market_value, issuer_exposures.market_value)", subject=RUN, unit="RATIO", value=6.21, as_of="2026-09-04", params={"node": "x", "op": "divide"}),
        _f(F.SCALAR, "revenue", subject="GOOGL", unit="MONEY", value=65.18e9, as_of="2025-12-31", window={"start": "2025-01-01", "end": "2025-12-31"}, params={"node": "r1"}),
        _f(F.SCALAR, "revenue", subject="GOOGL", unit="MONEY", value=45.04e9, as_of="2024-12-31", window={"start": "2024-01-01", "end": "2024-12-31"}, params={"node": "r0"}),
        _f(F.SERIES, "revenue.yoy", subject="GOOGL", unit="RATIO", points=(("2024-12-31", 0.32), ("2025-12-31", 0.447)), as_of="2025-12-31", params={"node": "g", "op": "yoy"}),
        _f(F.ABSENCE, "total_debt", subject="MSFT", text="incomplete_cover: …", as_of="n/a", params={"node": "td"}),
        _f(F.PASSAGE, "10-K Item 7", subject="LLY", text="Mounjaro and Zepbound together accounted for 56% of total revenues in 2025.", as_of="2026-02-20"),
    ]
    return Ledger.of_facts(facts), {f.measure + "|" + str(f.subject): f.id for f in facts}


def _id(ids, measure, subject):
    return ids[f"{measure}|{subject}"]


def _ok(v):
    assert v.ok, (v.error, v.problems)


# ── the five false statements, refused by type ────────────────────────────────

def test_a_tier_read_as_a_reading_is_refused(led):
    l, ids = led
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": _id(ids, "limit_checks.breach_level", "issuer_concentration:MSFT")}],
                 "prose": ["MSFT is already at {c1}."]}, l)
    assert v.error == "relation_does_not_fit" and v.problems[0]["reason"] == "tier_as_level"
    _ok(C.check({"claims": [{"id": "c1", "relation": "tier", "of": _id(ids, "limit_checks.breach_level", "issuer_concentration:MSFT")}],
                 "prose": ["MSFT breaches at {c1}."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "tier", "of": _id(ids, "issuer_exposures.weight", "MSFT")}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "kind_does_not_fit"


def test_the_same_point_twice_is_not_a_change(led):
    l, ids = led
    r1 = _id(ids, "revenue", "GOOGL")
    v = C.check({"claims": [{"id": "c1", "relation": "change", "of": r1, "against": r1}], "prose": ["revenue grew {c1}."]}, l)
    assert v.problems[0]["reason"] == "same_period"


def test_a_superlative_needs_an_ordering(led):
    l, ids = led
    v = C.check({"claims": [{"id": "c1", "relation": "rank", "of": _id(ids, "issuer_exposures.weight", "JPM")}], "prose": ["The largest is {c1}."]}, l)
    assert v.problems[0]["reason"] == "no_ordering"
    _ok(C.check({"claims": [{"id": "c1", "relation": "rank", "of": _id(ids, "issuer_exposures.weight", "MSFT")}], "prose": ["The largest is {c1}."]}, l))


def test_a_money_over_money_quotient_cannot_be_days_but_a_count_can(led):
    l, ids = led
    # the 620.9%-days case: the figure is a RATIO; the model may only state it as a ratio
    x = _id(ids, "divide(exposure_metrics.portfolio_market_value, issuer_exposures.market_value)", RUN)
    _ok(C.check({"claims": [{"id": "c1", "relation": "ratio", "of": x}], "prose": ["The book is {c1} the position."]}, l))
    days = _id(ids, "divide(issuer_exposures.market_value, adv)", "MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": days}], "prose": ["It takes {c1} days."]}, l))
    weight = _id(ids, "issuer_exposures.weight", "JPM")
    _ok(C.check({"claims": [{"id": "c1", "relation": "ratio", "of": weight}], "prose": ["{c1}"]}, l))   # dimensionless column


def test_room_needs_the_checks_own_tier(led):
    l, ids = led
    cur = _id(ids, "limit_checks.current_value", "issuer_concentration:MSFT")
    warn = _id(ids, "limit_checks.warning_level", "issuer_concentration:MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "room", "of": cur, "against": warn}], "prose": ["MSFT sits {c1}."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "room", "of": cur, "against": _id(ids, "issuer_exposures.weight", "MSFT")}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "no_tier"


# ── the relations, accepted ───────────────────────────────────────────────────

def test_change_over_two_readings_and_over_a_yoy_node(led):
    l, ids = led
    r1, r0 = _id(ids, "revenue", "GOOGL"), ids["revenue|GOOGL"]
    later = [f for f in l.by_id.values() if f["measure"] == "revenue" and f["as_of"] == "2025-12-31"][0]["id"]
    earlier = [f for f in l.by_id.values() if f["measure"] == "revenue" and f["as_of"] == "2024-12-31"][0]["id"]
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": later, "against": earlier}], "prose": ["Revenue went {c1}."]}, l))
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": _id(ids, "revenue.yoy", "GOOGL")}], "prose": ["Growth: {c1}."]}, l))


def test_absent_quote_series_table(led):
    l, ids = led
    p = _id(ids, "10-K Item 7", "LLY")
    _ok(C.check({"claims": [
        {"id": "c1", "relation": "absent", "of": _id(ids, "total_debt", "MSFT")},
        {"id": "c2", "relation": "quote", "of": p, "span": "accounted for 56% of total revenues"},
        {"id": "c3", "relation": "series", "of": _id(ids, "revenue.yoy", "GOOGL")},
        {"id": "c4", "relation": "table", "rows": [[_id(ids, "issuer_exposures.weight", "MSFT")], [_id(ids, "issuer_exposures.weight", "JPM")]]}],
        "prose": ["Total debt is {c1}. The filing says {c2}."]}, l))
    v = C.check({"claims": [{"id": "c2", "relation": "quote", "of": p, "span": "accounted for 82% of revenues"}], "prose": ["{c2}"]}, l)
    assert v.problems[0]["reason"] == "unverified_quote"


# ── prose digits (D3) ─────────────────────────────────────────────────────────

def test_digits_in_prose_must_account_to_the_ledger_or_the_question(led):
    l, ids = led
    w = _id(ids, "issuer_exposures.weight", "MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": w}], "prose": ["MSFT is {c1}, i.e. 16.1% of the book as of 2026-09-04."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": w}], "prose": ["MSFT is {c1}, roughly 17% of the book."]}, l)
    assert v.error == "unsourced_figure"
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": w}], "prose": ["If rates back up 100bp, MSFT at {c1} …"]}, l, question="rates back up 100bp"))
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": w}], "prose": [f"MSFT is {{c1}}, that is {w}."]}, l)
    assert v.error == "id_in_prose"


def test_shape_refusals(led):
    l, ids = led
    w = _id(ids, "issuer_exposures.weight", "MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": w}], "prose": ["No placeholder here."]}, l))   # an unplaced claim is a cite
    # V30 C2 (N12): "no completed run for port_1" passed as text over a misspelled
    # id — an absence is a fact the desk produced, or it is not claimed
    v = C.check({"claims": [{"id": "c1", "relation": "absent", "text": "the desk does not forecast"}], "prose": ["I cannot: {c1}."]}, l)
    assert v.problems[0]["reason"] == "claim_without_of"
    v = C.check({"claims": [{"id": "c1", "relation": "absent"}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "claim_without_of"
    v = C.check({"claims": [], "prose": ["See {c9}."]}, l)
    assert v.problems[0]["reason"] == "unknown_placeholder"
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": "f_nope"}], "prose": ["{c1}"]}, l)
    assert v.error == "not_on_ledger"


# ── rendering ─────────────────────────────────────────────────────────────────

def test_rendered_shape_matches_the_web_client(led):
    l, ids = led
    cur = _id(ids, "limit_checks.current_value", "issuer_concentration:MSFT")
    warn = _id(ids, "limit_checks.warning_level", "issuer_concentration:MSFT")
    ans = {"claims": [{"id": "c1", "relation": "room", "of": cur, "against": warn},
                      {"id": "c2", "relation": "table", "rows": [[_id(ids, "issuer_exposures.weight", "MSFT")], [_id(ids, "issuer_exposures.weight", "JPM")]], "title": "Weights"},
                      {"id": "c3", "relation": "series", "of": _id(ids, "revenue.yoy", "GOOGL")}],
           "prose": ["MSFT sits {c1} as of 2026-09-04."]}
    v = C.check(ans, l)
    _ok(v)
    out = C.accepted(ans, v, l)
    blocks = out["blocks"]
    assert blocks[0]["type"] == "paragraph"
    runs = blocks[0]["runs"]
    assert isinstance(runs[0], str) and "fact" in runs[1] and runs[2] == " against " and "fact" in runs[3]
    assert any(isinstance(r, dict) and "link" in r and r["link"]["as_written"] == "2026-09-04" for r in runs)
    assert blocks[1]["type"] == "table" and blocks[1]["labels"] == ["MSFT", "JPM"] and blocks[1]["title"] == "Weights"
    assert blocks[2]["type"] == "chart" and blocks[2]["fact"]["kind"] == "series"
    assert "16.3%" in out["text"] or "16.2%" in out["text"]
    assert out["verified"]["figures"] >= 3


def test_schema_is_provider_legal():
    s = C.ANSWER_SCHEMA
    assert s["type"] == "object"
    for kw in ("oneOf", "anyOf", "allOf", "not"):
        assert kw not in s


def test_tier_suffixes_are_real_columns():
    from exposure_workbench.analytics import resources
    cols = {c.name for r in resources.RUN_CHILDREN for c in r.columns}
    for s in C.TIER_SUFFIXES:
        assert any(c.endswith(s) for c in cols), s


# ── V30 round 2: the shapes the B1 replay refused that the grammar admits ─────

def test_a_series_point_address_and_a_series_as_a_level(led):
    l, ids = led
    s = _id(ids, "revenue.yoy", "GOOGL")
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": s}], "prose": ["Growth is {c1}."]}, l))
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": f"{s}@2025-12-31", "against": f"{s}@2024-12-31"}], "prose": ["It went {c1}."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": f"{s}@2023-12-31"}], "prose": ["{c1}"]}, l)
    assert v.error == "not_on_ledger"
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": s}], "prose": ["Growth went {c1}."]}, l))


def test_versus_is_two_subjects_not_two_periods(led):
    l, ids = led
    a, b = _id(ids, "issuer_exposures.weight", "MSFT"), _id(ids, "issuer_exposures.weight", "JPM")
    _ok(C.check({"claims": [{"id": "c1", "relation": "versus", "of": a, "against": b}], "prose": ["MSFT sits {c1}."]}, l))
    later = [f for f in l.by_id.values() if f["measure"] == "revenue" and f["as_of"] == "2025-12-31"][0]["id"]
    earlier = [f for f in l.by_id.values() if f["measure"] == "revenue" and f["as_of"] == "2024-12-31"][0]["id"]
    v = C.check({"claims": [{"id": "c1", "relation": "versus", "of": later, "against": earlier}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "is_a_change"
    # two measures of one subject (30d against 60d volatility) is a versus too; a weight against its tier is room
    cur = _id(ids, "limit_checks.current_value", "issuer_concentration:MSFT"); warn = _id(ids, "limit_checks.warning_level", "issuer_concentration:MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "room", "of": _id(ids, "issuer_exposures.weight", "MSFT"), "against": warn}], "prose": ["MSFT {c1}."]}, l))
    _ok(C.check({"claims": [{"id": "c1", "relation": "level", "of": cur}], "prose": "MSFT is at {c1}.\n\nThat is above the tier."}, l))


def test_a_quote_may_elide_and_a_quotient_may_be_days(led):
    l, ids = led
    p = _id(ids, "10-K Item 7", "LLY")
    _ok(C.check({"claims": [{"id": "c1", "relation": "quote", "of": p, "span": "Mounjaro and Zepbound … of total revenues in 2025"}], "prose": ["{c1}"]}, l))
    days = _id(ids, "divide(issuer_exposures.market_value, adv)", "MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "ratio", "of": days}], "prose": ["{c1} days"]}, l))


# ── V30 C2 (2026-09-09): the two gate holes the second claims round showed ────

def test_an_absence_born_of_a_misspelling_is_not_an_absence():
    """N12: run(portfolio='port_1') refused, and the answer told the reader the
    desk had no completed run for the book. The refusal was an address the desk
    did not recognise; the reader is not told it as an absence."""
    spelt = _f(F.ABSENCE, "w", text="w was not computed: _w_1 was refused — unknown_portfolio: no portfolio 'port_1'",
               as_of="n/a", params={"node": "w", "error": "depends_on_refused", "root": {"node": "_w_1", "error": "unknown_portfolio"}})
    data = _f(F.ABSENCE, "lev", text="lev was not computed — input_unavailable: no depreciation_amortization for MSFT",
              as_of="n/a", params={"node": "lev", "error": "input_unavailable"})
    l = Ledger.of_facts([spelt, data])
    v = C.check({"claims": [{"id": "c1", "relation": "absent", "of": spelt.id}], "prose": ["The book has no run: {c1}."]}, l)
    assert v.error == "relation_does_not_fit" and v.problems[0]["reason"] == "refused_not_absent"
    assert "unknown_portfolio" in v.problems[0]["detail"]
    _ok(C.check({"claims": [{"id": "c1", "relation": "absent", "of": data.id}], "prose": ["Leverage is not computable here: {c1}."]}, l))


def test_a_yoy_node_is_not_its_own_baseline(led):
    """N01 t2: the answer rendered "6.50% (2026-01-25) from 6.50% (2026-01-25)" —
    a change claim whose `against` was the yoy point itself."""
    l, ids = led
    g = _id(ids, "revenue.yoy", "GOOGL")
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": f"{g}@2025-12-31"}], "prose": ["Revenue grew {c1}."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "change", "of": f"{g}@2025-12-31", "against": f"{g}@2025-12-31"}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "same_figure"
    w = _id(ids, "issuer_exposures.weight", "MSFT")
    v = C.check({"claims": [{"id": "c1", "relation": "change", "of": f"{g}@2025-12-31", "against": w}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "different_measures"
    # the earlier reading of the base measure is the one `against` may be
    r0 = _id(ids, "revenue", "GOOGL")
    _ok(C.check({"claims": [{"id": "c1", "relation": "change", "of": f"{g}@2025-12-31", "against": r0}], "prose": ["Revenue grew {c1}."]}, l))


def test_a_one_point_series_renders_its_point():
    """N02: a yoy over five quarterly balances has one point, and the reader saw
    "accounts receivable rose accounts receivable yoy"."""
    from exposure_workbench.services import answer as A
    one = _f(F.SERIES, "accounts_receivable.yoy", subject="NVDA", unit="RATIO", points=(("2026-07-26", 0.2677),), as_of="2026-07-26", params={"node": "ar_g", "op": "yoy"})
    l = Ledger.of_facts([one])
    out = C.accepted({"claims": [{"id": "c1", "relation": "change", "of": one.id}], "prose": ["Receivables rose {c1}."]},
                     C.check({"claims": [{"id": "c1", "relation": "change", "of": one.id}], "prose": ["Receivables rose {c1}."]}, l), l)
    assert "26.8% (2026-07-26)" in out["text"], out["text"]
    assert A.fill(F.for_record(one))["display"] == "26.8% (2026-07-26)"


def test_an_unsourced_absence_is_told_which_absence_facts_exist():
    """C3 (2026-09-09): refused for an absent claim with no fact, the model dropped
    the absence in 7 of 10 turns. The refusal names what it could have pointed at."""
    data = _f(F.ABSENCE, "lev", text="lev was not computed — input_unavailable: …", as_of="n/a", params={"node": "lev", "error": "input_unavailable"})
    spelt = _f(F.ABSENCE, "w", text="w was not computed — unknown_portfolio: …", as_of="n/a", params={"node": "w", "error": "unknown_portfolio"})
    l = Ledger.of_facts([data, spelt])
    v = C.check({"claims": [{"id": "c1", "relation": "absent", "text": "leverage is not computable"}], "prose": ["{c1}"]}, l)
    assert v.error == "malformed_answer" and v.problems[0]["reason"] == "claim_without_of"
    cands = {a["id"]: a for a in v.problems[0]["absences_on_ledger"]}
    assert cands[data.id]["citable"] and cands[data.id]["refusal"] == "input_unavailable"
    assert not cands[spelt.id]["citable"]


def test_a_coverage_refusal_is_an_absence_and_an_address_error_is_not():
    """V30 C3: `unknown_name` names what the run DOES hold ("available: …") — a
    coverage statement the reader is entitled to. `unknown_portfolio` is a
    guessed id, and nothing about the desk's coverage."""
    coverage = _f(F.ABSENCE, "qty", text="qty was not computed — unknown_name: run_x holds no column issuer_exposures.<label>.quantity",
                  as_of="n/a", params={"node": "qty", "error": "unknown_name"})
    guess = _f(F.ABSENCE, "w", text="w was not computed — unknown_portfolio: no portfolio 'port_1'",
               as_of="n/a", params={"node": "w", "error": "unknown_portfolio"})
    l = Ledger.of_facts([coverage, guess])
    _ok(C.check({"claims": [{"id": "c1", "relation": "absent", "of": coverage.id}], "prose": ["No quantity column: {c1}."]}, l))
    v = C.check({"claims": [{"id": "c1", "relation": "absent", "of": guess.id}], "prose": ["{c1}"]}, l)
    assert v.problems[0]["reason"] == "refused_not_absent"


def test_a_figure_relation_aimed_at_a_passage_is_sent_to_quote(led):
    """V30 C3: 18 of 25 kind_does_not_fit refusals were `level` (or `absent`) on a
    filing passage. A passage holds words; the relation that fits carries them."""
    l, ids = led
    passage = _id(ids, "10-K Item 7", "LLY")
    for rel in ("level", "absent", "ratio", "rank"):
        v = C.check({"claims": [{"id": "c1", "relation": rel, "of": passage}], "prose": ["{c1}"]}, l)
        assert v.problems[0]["reason"] == "kind_does_not_fit", (rel, v.problems)
        assert "relation 'quote'" in v.problems[0]["detail"], (rel, v.problems[0]["detail"])
    _ok(C.check({"claims": [{"id": "c1", "relation": "quote", "of": passage,
                             "span": "Mounjaro and Zepbound together accounted for 56% of total revenues in 2025."}],
                 "prose": ["The filing says {c1}."]}, l))


def test_the_claim_schema_does_not_invite_what_the_gate_refuses():
    """An absence with no fact is prose, not a claim. The schema used to advertise
    a `text` field for exactly that ("the desk does not forecast"), which the gate
    then refused — a round trip the model could not avoid by reading the schema."""
    props = C.ANSWER_SCHEMA["properties"]["claims"]["items"]["properties"]
    assert "text" not in props, "a field the gate never honours is a wasted round trip"
    assert set(props) == {"id", "relation", "of", "against", "rows", "span", "title"}


def test_a_superlative_refusal_names_the_binding_it_would_rank(led):
    """Superlatives without a computed ordering are flat across every arm and both
    protocols (V26: 37 / 36 / 37 per 140 turns). The generic sentence has not moved
    it, so the refusal names the node the ordering would be built from."""
    l, ids = led
    jpm = _id(ids, "issuer_exposures.weight", "JPM")          # entry 'JPM' of node 'w', no rank
    v = C.check({"claims": [{"id": "c1", "relation": "rank", "of": jpm}], "prose": ["The biggest is {c1}."]}, l)
    assert v.problems[0]["reason"] == "no_ordering"
    d = v.problems[0]["detail"]
    assert "'JPM' of node $w" in d and '{"fn": "rank", "of": "$w"}' in d, d
    # a fact with no node/label still gets the general sentence
    lone = _f(F.SCALAR, "free_cash_flow", subject="MSFT", unit="MONEY", value=1.0, as_of="2026-06-30")
    l2 = Ledger.of_facts([lone])
    v = C.check({"claims": [{"id": "c1", "relation": "rank", "of": lone.id}], "prose": ["{c1}"]}, l2)
    assert "A superlative rests on a rank node" in v.problems[0]["detail"]
    # the accepted case is unchanged: an entry of a rank node carries its rank
    msft = _id(ids, "issuer_exposures.weight", "MSFT")
    _ok(C.check({"claims": [{"id": "c1", "relation": "rank", "of": msft}], "prose": ["The biggest is {c1}."]}, l))
