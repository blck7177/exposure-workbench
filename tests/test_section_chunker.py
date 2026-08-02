"""M5 section chunker (offline, pure)."""

from __future__ import annotations

from exposure_workbench.services.section_chunker import (
    MAX_CHARS,
    MIN_CHUNK_CHARS,
    TARGET_CHARS,
    chunk_section,
)


def test_empty_section_yields_nothing():
    assert chunk_section("") == []
    assert chunk_section("   \n\n  ") == []


def test_short_section_is_one_chunk():
    text = "Item 7A. Market Risk\n\n" + ("We face interest rate risk. " * 10)
    chunks = chunk_section(text)
    assert len(chunks) == 1
    assert chunks[0].chunk_order == 0


def test_long_section_splits_and_offsets_are_within_bounds():
    para = "Supply chain concentration remains a material risk to operations. " * 12  # ~800 chars
    text = "\n\n".join([para] * 8)
    chunks = chunk_section(text)
    assert len(chunks) > 1
    for c in chunks:
        assert c.char_start >= 0
        assert c.char_end <= len(text)
        assert c.char_start < c.char_end
    # chunk_order is dense and ascending — citations rely on it
    assert [c.chunk_order for c in chunks] == list(range(len(chunks)))


def test_chunks_do_not_exceed_hard_ceiling_by_much():
    para = "x" * 5000   # one pathological paragraph (dense financial table)
    chunks = chunk_section(para)
    assert chunks, "a huge single paragraph must still produce chunks"
    for c in chunks:
        assert len(c.text) <= MAX_CHARS + 200


def test_scraps_below_min_are_dropped():
    # a heading-only section should not become a chunk
    assert chunk_section("Item 4.") == []


def test_offsets_point_at_real_source_text():
    a = "Alpha paragraph about revenue growth. " * 20
    b = "Beta paragraph about margin pressure. " * 20
    text = a + "\n\n" + b
    chunks = chunk_section(text)
    # every chunk's span should overlap the region its text came from
    for c in chunks:
        assert text[c.char_start:c.char_end].strip(), "span must map onto real source text"


def test_the_chunker_constants_are_pinned_because_the_golden_set_depends_on_them():
    """V3-D1. Retrieval labels are SEC item codes rather than chunk ids, which
    survives re-ingest — but the chunk BOUNDARIES that decide which item a
    retrieved passage reports are a function of these four numbers. Changing one
    silently re-scores all 24 golden queries against a corpus that is no longer
    the one they were measured on, so a change goes red here and the baseline is
    regenerated deliberately."""
    from exposure_workbench.services import section_chunker as sc

    assert (sc.TARGET_CHARS, sc.MAX_CHARS, sc.OVERLAP_CHARS, sc.MIN_CHUNK_CHARS) == (1500, 2400, 150, 80), (
        "chunker geometry changed: re-run scripts/eval_retrieval.py --write-baseline "
        "and record the before/after in V3_COVERAGE"
    )
