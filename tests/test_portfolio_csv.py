"""CSV holdings parser (V2-B, offline). Every malformed line must surface as a
problem with its row number — never silently dropped — and the caller rejects
the whole upload if any problem exists."""

from __future__ import annotations

from exposure_workbench.services.portfolio_csv import MAX_ROWS, parse_csv


def test_valid_with_header_and_optional_cost():
    rows, problems = parse_csv("ticker,quantity,cost_basis\nAAPL,10,150\nMSFT,5\n")
    assert problems == []
    assert [(r.ticker, r.quantity, r.cost_basis) for r in rows] == [
        ("AAPL", 10.0, 150.0), ("MSFT", 5.0, None),
    ]


def test_header_optional():
    rows, problems = parse_csv("nvda,3\n")
    assert problems == []
    assert rows[0].ticker == "NVDA" and rows[0].quantity == 3.0


def test_ticker_uppercased_and_trimmed():
    rows, _ = parse_csv("  aapl , 2 \n")
    assert rows[0].ticker == "AAPL"


def test_bad_quantity_flagged_with_row():
    rows, problems = parse_csv("AAPL,abc\nMSFT,5\n")
    assert any(p.row == 1 and p.ticker == "AAPL" and "quantity" in p.reason for p in problems)
    # the good row still parses (caller enforces atomicity, not the parser)
    assert [r.ticker for r in rows] == ["MSFT"]


def test_nonpositive_quantity_flagged():
    _, problems = parse_csv("AAPL,0\nMSFT,-3\n")
    reasons = {p.ticker: p.reason for p in problems}
    assert "AAPL" in reasons and "MSFT" in reasons
    assert all("> 0" in r for r in reasons.values())


def test_wrong_field_count_flagged():
    _, problems = parse_csv("AAPL\nMSFT,5,150,extra\n")
    assert {p.row for p in problems} == {1, 2}


def test_bad_cost_basis_flagged():
    _, problems = parse_csv("AAPL,10,notnum\n")
    assert problems and "cost_basis" in problems[0].reason


def test_duplicate_ticker_flagged():
    rows, problems = parse_csv("AAPL,10\nAAPL,5\n")
    assert len(rows) == 1
    assert any("duplicate" in p.reason for p in problems)


def test_empty_is_a_problem():
    rows, problems = parse_csv("   \n\n")
    assert rows == [] and problems and "empty" in problems[0].reason


def test_too_many_rows_flagged():
    text = "\n".join(f"AAPL{i},1" for i in range(MAX_ROWS + 5))
    _, problems = parse_csv(text)
    assert any("too many rows" in p.reason for p in problems)


def test_blank_lines_ignored_row_numbers_preserved():
    rows, problems = parse_csv("AAPL,10\n\nMSFT,bad\n")
    assert [r.ticker for r in rows] == ["AAPL"]
    # MSFT is on input line 3 despite the blank line 2
    assert any(p.row == 3 and p.ticker == "MSFT" for p in problems)


def test_non_finite_quantities_rejected():
    """NaN/Inf/overflow must be rejected in the parser, never reach the DB —
    bare float() accepts them and NaN slips past the >0 guard (regression)."""
    for bad in ("nan", "NaN", "inf", "Inf", "-inf", "1e400"):
        rows, problems = parse_csv(f"AAPL,{bad}\n")
        assert rows == [], f"{bad!r} produced a row"
        assert problems and problems[0].ticker == "AAPL"


def test_non_finite_cost_basis_rejected():
    rows, problems = parse_csv("AAPL,10,nan\n")
    assert rows == []
    assert problems and "cost_basis" in problems[0].reason
