"""V14-C — the block exit (offline).

The invariant everything else rests on: a figure reaches the reader through a
slot or it does not reach the reader. What follows is that invariant from both
sides, plus the two assertion classes the numeric gate cannot see because
neither claim contains a number.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services.numeric_verification import COUNT, MONEY, RATIO, EvidenceValue


def _p(*runs):
    return {"type": "paragraph", "runs": list(runs)}


# ── the invariant ─────────────────────────────────────────────────────────────

def test_a_figure_written_into_prose_is_refused():
    """The whole batch in one assertion. There is nothing to transcribe, so
    there is nothing to transcribe wrongly — but only if prose cannot carry a
    figure at all."""
    [p] = ab.validate_shape([_p("the book lost 1.29% on the day")])
    assert p["reason"] == "figure_written_as_text"
    assert p["figures"] == ["1.29%"]


def test_the_same_figure_in_a_slot_is_accepted():
    assert ab.validate_shape([_p("the book lost ", {"ref": "run_x", "value": -0.0129},
                                 " on the day")]) == []


def test_a_date_or_a_form_number_is_still_prose():
    """The exemptions are the gate's own closed list. What stays refused is a
    MEASUREMENT typed as text, not every character that happens to be a digit —
    an answer that cannot say "the 10-Q filed 2026-03-31" is unusable."""
    assert ab.validate_shape([_p("the 10-Q filed 2026-03-31 covers Q1 2026")]) == []


def test_a_table_cell_may_not_carry_a_written_figure_either():
    """A table is where a model would most naturally type numbers, so the rule
    has to hold in the cells or it does not hold."""
    blocks = [{"type": "metric_table", "columns": ["Scenario", "Loss"],
               "rows": [["market_downside", "7.44%"]]}]
    [p] = ab.validate_shape(blocks)
    assert p["reason"] == "figure_written_as_text"
    assert p["at"] == "blocks[0].rows[0][1]"


# ── shape ─────────────────────────────────────────────────────────────────────

def test_an_unknown_block_type_is_refused_rather_than_ignored():
    """An exit that silently drops what it does not understand is an exit that
    can be talked past."""
    [p] = ab.validate_shape([{"type": "callout", "text": "hello"}])
    assert p["reason"] == "unknown_block_type"
    assert set(p["allowed"]) == set(ab.BLOCK_TYPES)


def test_a_short_row_is_refused():
    """A cell shifted under the wrong heading is a figure filed as a different
    measurement entirely, and nothing downstream could detect it."""
    blocks = [{"type": "metric_table", "columns": ["A", "B", "C"],
               "rows": [["one", {"ref": "run_x", "value": 1.0}]]}]
    [p] = ab.validate_shape(blocks)
    assert p["reason"] == "row_width_mismatch"


def test_a_slot_needs_exactly_one_of_label_or_value():
    both = ab.validate_shape([_p({"ref": "run_x", "label": "a.b", "value": 1.0})])
    neither = ab.validate_shape([_p({"ref": "run_x"})])
    assert both[0]["reason"] == "slot_with_both"
    assert neither[0]["reason"] == "slot_without_value"


def test_every_problem_is_reported_not_just_the_first():
    """The argument validator's rule, for the argument validator's reason: a
    model fixing one problem per turn is the ratchet this batch removes."""
    problems = ab.validate_shape([
        _p("we lost 1.29% today"),
        {"type": "metric_table", "columns": ["A"], "rows": [["also 7.44%"]]},
        {"type": "nonsense"},
    ])
    assert len(problems) == 3
    assert {p["reason"] for p in problems} == {
        "figure_written_as_text", "unknown_block_type"}


def test_an_empty_answer_is_refused():
    assert ab.validate_shape([])[0]["reason"] == "no_blocks"


# ── resolution ────────────────────────────────────────────────────────────────

VALUES = [
    EvidenceValue(0.1627, RATIO, "issuer_exposures.MSFT.weight", "run_x"),
    EvidenceValue(0.1467, RATIO, "issuer_exposures.JPM.weight", "run_x"),
    EvidenceValue(10866320.0, MONEY, "exposure_metrics.portfolio_market_value", "run_x"),
    EvidenceValue(-0.800770, RATIO, "portfolio.integration.net_beta.equity_down", "calc_y"),
]


def test_a_slot_resolves_by_label():
    blocks = [_p("MSFT is ", {"ref": "run_x", "label": "issuer_exposures.MSFT.weight"})]
    resolved, problems = ab.resolve(blocks, VALUES)
    assert problems == []
    assert resolved[0].value == pytest.approx(0.1627)
    assert resolved[0].unit_class == RATIO


def test_a_slot_resolves_by_value_and_takes_the_ledgers_name():
    """The migration path, and the reason it is safe: whichever way the slot was
    written, what comes back is the row's own label. A reader hovering the figure
    is shown what the ledger calls it."""
    blocks = [_p("MSFT is ", {"ref": "run_x", "value": 0.1627})]
    resolved, problems = ab.resolve(blocks, VALUES)
    assert problems == []
    assert resolved[0].label == "issuer_exposures.MSFT.weight"


def test_a_value_slot_is_checked_against_its_own_ref_only():
    """Stronger than the prose gate, which matched a figure against everything
    cited. Here the id the answer points at has to be the id that holds it."""
    blocks = [_p({"ref": "calc_y", "value": 0.1627})]
    _resolved, problems = ab.resolve(blocks, VALUES)
    assert problems[0]["reason"] == "figure_not_held_by_this_ref"


def test_a_rounded_value_resolves_at_the_precision_written():
    """Half an ulp of the precision WRITTEN — the gate's own tolerance, so a
    figure written to two places is held to two places. This is what makes
    reader-facing precision possible without a second rule about rounding."""
    blocks = [_p({"ref": "calc_y", "value": -0.80})]
    resolved, problems = ab.resolve(blocks, VALUES)
    assert problems == []
    assert resolved[0].value == pytest.approx(-0.800770)


def test_a_figure_that_does_not_round_to_the_ledgers_is_refused():
    """The other half of the tolerance rule. -0.81 is written to two places, so
    it is held to two, and the row holds -0.80077 — which -0.81 is not a rounding
    of. Precision is a claim about how well the figure is known, and a slot
    cannot claim more than the row supports."""
    blocks = [_p({"ref": "calc_y", "value": -0.81})]
    _resolved, problems = ab.resolve(blocks, VALUES)
    assert problems[0]["reason"] == "figure_not_held_by_this_ref"


def test_an_unknown_label_comes_back_with_the_labels_that_exist():
    """A refusal that names some of the options is a refusal answered by
    guessing again. The list is what makes the second attempt the last one."""
    blocks = [_p({"ref": "run_x", "label": "issuer_exposures.MSFT.market_value"})]
    _resolved, problems = ab.resolve(blocks, VALUES)
    assert problems[0]["reason"] == "unknown_label"
    assert "issuer_exposures.MSFT.weight" in problems[0]["available"]


def test_a_ref_holding_no_figures_says_so():
    """A passage is cited for what it says, not slotted for a figure, and the
    refusal has to distinguish the two or it reads as the id being invalid."""
    blocks = [_p({"ref": "chunk_z", "value": 1.0})]
    _resolved, problems = ab.resolve(blocks, VALUES)
    assert problems[0]["reason"] == "ref_holds_no_figures"


# ── what the answer leans on ──────────────────────────────────────────────────

def test_refs_gathers_slots_and_block_level_ids_alike():
    """One list, because they are validated the same way: an id not returned to
    this session is not evidence, whether it names a figure or a series."""
    blocks = [
        _p({"ref": "run_x", "value": 0.1}),
        {"type": "trend", "text": "it has been rising", "series_ref": "calc_s"},
        {"type": "absence", "text": "they report no such line", "absence_ref": "calc_a"},
        {"type": "metric_table", "columns": ["A"], "rows": [[{"ref": "calc_y", "value": 1.0}]]},
    ]
    assert ab.refs_in(blocks) == ["run_x", "calc_s", "calc_a", "calc_y"]


def test_text_of_returns_only_what_the_model_wrote_as_words():
    """What the quote and trajectory checks read. Slots contribute nothing — they
    hold no words — so those checks see exactly the prose."""
    blocks = [_p("the book lost ", {"ref": "run_x", "value": -0.0129}, " today")]
    assert ab.text_of(blocks) == "the book lost  today"


# ── the two assertion classes ─────────────────────────────────────────────────

class _Row:
    def __init__(self, op, result=None):
        self.operation, self.result = op, result or {}


def test_a_trend_needs_a_series_behind_it():
    """Round 4's clearest hole: "VaR has been climbing all month", from a library
    holding one run, drew zero refusals twice. It contains no number, so nothing
    the numeric gate does could see it."""
    blocks = [{"type": "trend", "text": "VaR has been climbing all month",
               "series_ref": "calc_scalar"}]
    [p] = ab.check_assertion_refs(blocks, {"calc_scalar": _Row("calc.scalar.divide")})
    assert p["reason"] == "not_a_series"


def test_a_trend_on_a_real_series_passes():
    blocks = [{"type": "trend", "text": "revenue has grown each quarter",
               "series_ref": "calc_series"}]
    assert ab.check_assertion_refs(blocks, {"calc_series": _Row("flow.series")}) == []


def test_a_series_recognised_by_its_points_as_well_as_its_name():
    """The operation name is one signal; a row that recorded points IS a series
    whatever it is called, and a check that trusted only the name would refuse a
    claim the ledger fully supports."""
    blocks = [{"type": "trend", "text": "it rose", "series_ref": "calc_p"}]
    assert ab.check_assertion_refs(
        blocks, {"calc_p": _Row("window_return", {"points": [{"value": 1}]})}) == []


def test_an_absence_needs_the_row_a_refused_read_minted():
    """V11 minted absence rows so a refusal could be cited. Nothing required an
    absence CLAIM to rest on one, so a model could assert a company files
    nothing and the gate saw a sentence with no numbers in it."""
    blocks = [{"type": "absence", "text": "they report no debt at all",
               "absence_ref": "calc_real"}]
    [p] = ab.check_assertion_refs(blocks, {"calc_real": _Row("derive.interval")})
    assert p["reason"] == "not_an_absence"


def test_an_absence_on_an_absence_row_passes():
    blocks = [{"type": "absence", "text": "not reported at this date",
               "absence_ref": "calc_abs"}]
    assert ab.check_assertion_refs(blocks, {"calc_abs": _Row("absence.not_reported")}) == []


def test_a_missing_row_fails_both_checks():
    """A ref that is not a calc id at all — a fact, a run — is not a series and
    did not record a refusal. Absent from the lookup, and treated as failing."""
    for block in ({"type": "trend", "text": "rose", "series_ref": "fact_1"},
                  {"type": "absence", "text": "absent", "absence_ref": "run_1"}):
        assert ab.check_assertion_refs([block], {}) != []


# ── what is rendered ──────────────────────────────────────────────────────────

def test_the_models_value_does_not_survive_rendering():
    """What is stored is the ledger's figure and the ledger's name for it. The
    model's rounded copy was a way of pointing at a row, not the thing shown."""
    blocks = [_p("MSFT is ", {"ref": "run_x", "value": 0.163})]
    resolved, _ = ab.resolve(blocks, VALUES)
    [out] = ab.rendered(blocks, resolved)
    slot = out["runs"][1]["slot"]
    assert slot["value"] == pytest.approx(0.1627)
    assert slot["label"] == "issuer_exposures.MSFT.weight"
    assert out["runs"][0] == "MSFT is "


def test_rendering_fills_table_cells_too():
    blocks = [{"type": "metric_table", "columns": ["Name", "Weight"],
               "rows": [["MSFT", {"ref": "run_x", "label": "issuer_exposures.MSFT.weight"}]]}]
    resolved, _ = ab.resolve(blocks, VALUES)
    [out] = ab.rendered(blocks, resolved)
    assert out["rows"][0][0] == "MSFT"
    assert out["rows"][0][1]["slot"]["value"] == pytest.approx(0.1627)


def test_a_count_unit_survives_to_the_renderer():
    """The unit class travels with the figure so a renderer can format it. A
    count printed as a percentage is the same class of error the gate's unit
    rules exist to stop, one layer later."""
    vals = [EvidenceValue(58.0, COUNT, "exposure_metrics.observations", "run_x")]
    blocks = [_p({"ref": "run_x", "value": 58})]
    resolved, problems = ab.resolve(blocks, vals)
    assert problems == []
    assert resolved[0].unit_class == COUNT


def test_a_slot_holding_words_says_so_rather_than_reporting_it_missing():
    """The first thing the exit met in the wild. "A reference to evidence" is
    what a slot looks like from outside, so the model put an alert's whole
    sentence in one — and a refusal reading "give the slot a value" to a model
    that gave one teaches nothing about which kind of value was wanted."""
    [p] = ab.validate_shape([_p({"ref": "alert_x", "value": "Issuer LLY: 13.0% vs limit"})])
    assert p["reason"] == "slot_value_is_text"


def test_an_id_or_a_date_belongs_in_the_text():
    """The corollary, and the reason the rule is learnable: everything that is
    not a figure was always allowed in prose. The exemptions cover ids and dates,
    so a model that stops slotting them has somewhere to put them."""
    assert ab.validate_shape([_p("run_9f2c as of 2026-08-27 covers the book")]) == []


def test_a_misplaced_figure_is_told_which_id_holds_it():
    """Pinning a figure to one ref is stronger than the prose gate, which pooled
    everything cited — and the first thing that strength costs is an answer whose
    figures are right and whose refs are swapped. V11-G's discipline: the refusal
    names the id the answer ALREADY HAS."""
    blocks = [_p({"ref": "calc_y", "value": 0.1627})]
    _resolved, [p] = ab.resolve(blocks, VALUES)
    assert p["reason"] == "figure_not_held_by_this_ref"
    assert p["held_instead_by"][0]["ref"] == "run_x"
    assert p["held_instead_by"][0]["label"] == "issuer_exposures.MSFT.weight"


def test_a_figure_nothing_holds_gets_no_false_lead():
    blocks = [_p({"ref": "calc_y", "value": 42.0})]
    _resolved, [p] = ab.resolve(blocks, VALUES)
    assert "held_instead_by" not in p


def test_the_stored_prose_is_a_complete_sentence():
    """text_of feeds the checks and drops the figures on purpose. What is STORED
    has the opposite requirement: a transcript, an export, or a client older than
    blocks would otherwise show "the weight is , which is past its limit"."""
    blocks = [_p("MSFT is ", {"ref": "run_x", "value": 0.1627}, " of the book")]
    resolved, _ = ab.resolve(blocks, VALUES)
    assert ab.prose_of(ab.rendered(blocks, resolved)) == "MSFT is 0.1627 of the book"


def test_the_stored_prose_carries_the_ledgers_figure_not_the_models():
    blocks = [_p("MSFT is ", {"ref": "run_x", "value": 0.163})]
    resolved, _ = ab.resolve(blocks, VALUES)
    assert "0.1627" in ab.prose_of(ab.rendered(blocks, resolved))


def test_a_large_figure_reads_as_a_number_in_the_stored_prose():
    """%g turns ten million into 1.08663e+07, and this string is what a
    transcript shows. A reader who cannot tell a market value from a serial
    number is being shown the formatter, not the figure."""
    blocks = [_p("the book is worth ", {"ref": "run_x", "value": 10866320.0})]
    resolved, _ = ab.resolve(blocks, VALUES)
    assert "10866320" in ab.prose_of(ab.rendered(blocks, resolved))
    assert "e+" not in ab.prose_of(ab.rendered(blocks, resolved))
