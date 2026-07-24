"""Section chunker (M5) — Item sections -> retrievable chunks.

Deliberately a standalone component: the M2a parse approach is expected to keep
evolving, and isolating chunking means those iterations never touch the
embedding / index / retrieval code.

Rules:
  * Chunk WITHIN a section only. A chunk never spans two SEC Items, so every
    passage keeps an unambiguous item_code for citation.
  * Split on paragraph boundaries, packing paragraphs up to a target size — not
    blind fixed-width slicing (which would cut sentences mid-thought).
  * char_start/char_end are offsets INTO THE SECTION text, so a citation can be
    resolved back to exact source characters.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tuned together with the M2a parse evaluation; see docs/spikes/M2_PARSE_EVAL.md.
TARGET_CHARS = 1500
MAX_CHARS = 2400          # hard ceiling before a paragraph is force-split
OVERLAP_CHARS = 150       # carry-over so a boundary sentence stays retrievable
MIN_CHUNK_CHARS = 80      # drop scraps (headings, stray numbering)


@dataclass(frozen=True)
class Chunk:
    text: str
    char_start: int
    char_end: int
    chunk_order: int


def _split_paragraphs(text: str) -> list[tuple[int, str]]:
    """Return (offset, paragraph) pairs, preserving true offsets into `text`."""
    out: list[tuple[int, str]] = []
    pos = 0
    for para in text.split("\n\n"):
        if para.strip():
            out.append((pos, para))
        pos += len(para) + 2   # +2 for the separator we split on
    return out


def _force_split(offset: int, para: str) -> list[tuple[int, str]]:
    """A single paragraph longer than MAX_CHARS (dense financial tables) is cut on
    whitespace near the limit rather than mid-token."""
    pieces: list[tuple[int, str]] = []
    start = 0
    while start < len(para):
        end = min(start + MAX_CHARS, len(para))
        if end < len(para):
            ws = para.rfind(" ", start + MIN_CHUNK_CHARS, end)
            if ws > start:
                end = ws
        pieces.append((offset + start, para[start:end]))
        start = end
    return pieces


def chunk_section(text: str) -> list[Chunk]:
    """Pack a section's paragraphs into ~TARGET_CHARS chunks with small overlap."""
    if not text or not text.strip():
        return []

    units: list[tuple[int, str]] = []
    for offset, para in _split_paragraphs(text):
        if len(para) > MAX_CHARS:
            units.extend(_force_split(offset, para))
        else:
            units.append((offset, para))

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_start: int | None = None
    buf_end = 0

    def flush() -> None:
        nonlocal buf, buf_start, buf_end
        if not buf or buf_start is None:
            buf, buf_start = [], None
            return
        body = "\n\n".join(buf).strip()
        if len(body) >= MIN_CHUNK_CHARS:
            chunks.append(Chunk(text=body, char_start=buf_start, char_end=buf_end,
                                chunk_order=len(chunks)))
        buf, buf_start = [], None

    for offset, unit in units:
        if buf_start is None:
            buf_start = offset
        buf.append(unit)
        buf_end = offset + len(unit)
        if sum(len(b) for b in buf) >= TARGET_CHARS:
            tail = buf[-1][-OVERLAP_CHARS:] if OVERLAP_CHARS else ""
            tail_start = buf_end - len(tail)
            flush()
            if tail.strip():          # seed the next chunk with the overlap
                buf, buf_start, buf_end = [tail], tail_start, buf_end
    flush()
    return chunks
