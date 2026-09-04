"""V21-S5 — the critic outside the gate: does the prose call a figure what it is?

WHAT THE GATE PROVES AND DOES NOT. Every figure in an answer is a slot
{ref, name}; the resolver proves the name is on the table and shows the
reader the table's own value. That is proof of provenance. It is not proof
of the words beside the figure: "market cap at $919.77" passed with the slot
`LLY.close` (a closing share price), "Peak-to-trough decline | $205.10" with
the slot `NVDA.adj_close@2026-06-05` (the trough). V19 removed the model's
hand from table headers and row labels (derived from the slot names) and
put a computed direction under every trend; a paragraph's sentence is the
one place a label is still the model's, and by the 9/1 contract no lexical
rule and no model goes INTO the gate to read it (the gate is five closed
lookups; a judgement about words is neither closed nor a lookup).

So the judgement is made here, outside: a second model reads each paragraph
with its slots marked, is told the desk's own name for each figure, and says
what the sentence claims the figure is and whether that agrees. It is a
measurement (a rubric_battery criterion with a finer unit — the slot, not
the answer) and, if the desk chooses, an annotation the reader sees beside
the sentence. It is not a gate: nothing here can refuse an answer, and this
module is imported by no exit (test pins it).

Three verdicts and no score: `agrees`, `disagrees`, `unclear`. Binary where it
can be, and honest where it cannot — "the stock traded at $919.77" beside
`LLY.close` agrees; "market cap at $919.77" disagrees; "$919.77" alone is
unclear and is not a finding.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable

from exposure_workbench.analytics import display_conventions as dc

VERDICTS = ("agrees", "disagrees", "unclear")

# The marker a slot becomes in the prose the critic reads. Corner brackets, so
# nothing the model or a filing writes collides with it.
_MARK = "⟦{k}⟧"


@dataclass(frozen=True)
class SlotInProse:
    block_index: int
    k: int                    # 1-based marker within the block
    ref: str
    name: str                 # the desk's name: LLY.close, NVDA.adj_close@2026-06-05, issuer_exposures.MSFT.weight
    value: float | None
    unit_class: str
    shown: str                # the figure at reader precision, as the page shows it


@dataclass(frozen=True)
class Paragraph:
    block_index: int
    marked: str               # the prose with each slot replaced by ⟦k⟧ (value)
    slots: list[SlotInProse]


@dataclass(frozen=True)
class Finding:
    block_index: int
    k: int
    ref: str
    name: str
    shown: str
    prose_says: str
    verdict: str
    reason: str
    sentence: str

    def as_dict(self) -> dict:
        return asdict(self)


# ── 1. the paragraphs, with their slots marked ────────────────────────────────

def paragraphs(rendered_blocks) -> list[Paragraph]:
    """Every paragraph block that carries at least one slot, prose marked.

    Reads RENDERED blocks (answer_blocks.rendered): a slot is
    {"slot": {"ref", "label", "value", "unit_class"}}. Tables, trends, charts,
    absences and actions are not read — their labels are derived or computed
    (V19), which is what leaves the paragraph as the one place to look.
    """
    out: list[Paragraph] = []
    for i, b in enumerate(rendered_blocks if isinstance(rendered_blocks, list) else []):
        if not isinstance(b, dict) or b.get("type") != "paragraph" or not b.get("runs"):
            continue
        parts: list[str] = []
        slots: list[SlotInProse] = []
        for run in b["runs"]:
            if isinstance(run, str):
                parts.append(run)
                continue
            slot = (run or {}).get("slot") if isinstance(run, dict) else None
            if not slot:
                continue
            k = len(slots) + 1
            shown = dc.display(slot["value"], slot.get("unit_class") or "") if slot.get("value") is not None else "—"
            slots.append(SlotInProse(block_index=i, k=k, ref=str(slot.get("ref")), name=str(slot.get("label")),
                                     value=slot.get("value"), unit_class=slot.get("unit_class") or "", shown=shown))
            parts.append(f"{_MARK.format(k=k)}({shown})")
        if slots:
            out.append(Paragraph(block_index=i, marked="".join(parts), slots=slots))
    return out


def sentence_around(marked: str, k: int) -> str:
    """The sentence the k-th marker sits in, for the report."""
    mark = _MARK.format(k=k)
    pos = marked.find(mark)
    if pos < 0:
        return marked
    start = max(marked.rfind(". ", 0, pos), marked.rfind("\n", 0, pos))
    start = 0 if start < 0 else start + 2
    end_candidates = [e for e in (marked.find(". ", pos), marked.find("\n", pos)) if e >= 0]
    end = min(end_candidates) + 1 if end_candidates else len(marked)
    return marked[start:end].strip()


# ── 2. the question put to the critic ─────────────────────────────────────────

_NAME_GRAMMAR = """How the desk names a figure (the "desk name" below):
- `TICKER.close` — the as-traded closing share price on the latest session; `TICKER.adj_close` — the split- and dividend-adjusted close; `TICKER.adj_close@DATE` — the adjusted close on that date (one point of a price series).
- `TICKER.drawdown.peak|trough|fall|depth` — the deepest fall in a window: the two levels, their difference per share, and that difference as a ratio of the peak.
- `TICKER.rolling_volatility`, `TICKER.beta`, `TICKER.momentum_12_1`, `TICKER.distance_from_52w_high`, `TICKER.adv.shares|dollars` — the single-name estimators, named as read.
- `TICKER.adj_close.latest` / `metric.latest` — the last point of a series (the current value). `metric.abs@DATE`, `.pct@DATE`, `.yoy@DATE`, `.qoq@DATE` — a CHANGE in the metric ending at that date (absolute, percent, year-on-year, quarter-on-quarter): "shares_outstanding.abs@2026-01-25 = −173,000,000" IS a change in the share count, not a share count. `metric.cagr`, `.avg`, `.max`, `.min` — the statistic named, over the series.
- `metric@PERIOD` or `TICKER metric` — a filed financial line (revenue, net income, total debt…) over the stated period; `formula.rank.TICKER` — a place in a computed ranking.
- `risk_alerts.CHECK.current_value` — the value a mandate check measured (for `stress_loss:SCENARIO`, the estimated LOSS under that scenario, not the shock that caused it); `exposure_metrics.daily_return` — the whole book's day return, not one position's contribution.
- `issuer_exposures.TICKER.weight|market_value|contribution`, `sector_exposures.SECTOR.weight`, `exposure_metrics.market_value|daily_return|rolling_vol_30d|max_drawdown`, `factor_attributions.FACTOR.beta|contribution`, `limit_checks.CHECK.current_value|breach_level` — a run's own quantities, table.entity.column.
A share PRICE is not a market cap, a market value, a return, a change or a total. A closing price on a date is not a decline. A weight is a share of the book, not a return."""

_INSTRUCTION = """You are checking LABELS, not numbers. Each figure below is correct and comes from the desk's table; the question is only whether the words around it call it what it is.

For each marker ⟦k⟧ in the paragraph, read the words around it and state in a few words what quantity the sentence claims the figure is (for example "market cap", "closing price", "decline from the peak", "revenue for the quarter", "weight in the book"). Then compare with the desk name given for that marker and give one verdict:
- "agrees": the sentence calls the figure what the desk name says it is (a paraphrase is fine: "the stock closed at" agrees with `LLY.close`).
- "disagrees": the sentence calls it a different quantity (a price called a market cap; a trough price called a decline; a weight called a return).
- "unclear": the sentence does not say what the figure is, or you cannot tell.
Answer with JSON only, exactly this shape and nothing else:
{"verdicts": [{"k": 1, "prose_says": "...", "verdict": "agrees|disagrees|unclear", "reason": "..."}]}
One entry per marker, in order."""


def messages_for(p: Paragraph) -> list[dict]:
    legend = "\n".join(f"⟦{s.k}⟧ shows {s.shown}; desk name: `{s.name}`"
                       + (f" ({s.unit_class})" if s.unit_class else "") for s in p.slots)
    user = f"{_NAME_GRAMMAR}\n\nParagraph:\n{p.marked}\n\nMarkers:\n{legend}"
    return [{"role": "system", "content": _INSTRUCTION}, {"role": "user", "content": user}]


# ── 3. reading the answer ─────────────────────────────────────────────────────

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_verdicts(text: str, expected: int) -> list[dict]:
    """The critic's JSON, or one `unclear` per marker if it did not answer in
    shape — a critic that cannot be read has said nothing, and nothing is
    not a disagreement."""
    raw = _FENCE.sub("", (text or "").strip())
    try:
        data = json.loads(raw)
        items = data.get("verdicts") if isinstance(data, dict) else data
        by_k = {int(v["k"]): v for v in items if isinstance(v, dict) and "k" in v}
    except (ValueError, TypeError, KeyError, AttributeError):
        by_k = {}
    out: list[dict] = []
    for k in range(1, expected + 1):
        v = by_k.get(k) or {}
        verdict = str(v.get("verdict", "unclear")).strip().lower()
        out.append({"k": k,
                    "prose_says": str(v.get("prose_says", "")).strip(),
                    "verdict": verdict if verdict in VERDICTS else "unclear",
                    "reason": str(v.get("reason", "")).strip()})
    return out


Chat = Callable[..., Awaitable[tuple[str, str, int, int]]]


async def critique(rendered_blocks, *, chat: Chat, model: str | None = None) -> list[Finding]:
    """One finding per slot in prose. `chat` is llm.client.chat_complete or a
    stand-in with its signature; passed in, never imported here, so the module
    that decides whether a critic runs is the one that pays for it."""
    findings: list[Finding] = []
    for p in paragraphs(rendered_blocks):
        text, *_ = await chat(messages_for(p), model=model, temperature=0.0, max_tokens=1024)
        for s, v in zip(p.slots, parse_verdicts(text, len(p.slots))):
            findings.append(Finding(
                block_index=p.block_index, k=s.k, ref=s.ref, name=s.name, shown=s.shown,
                prose_says=v["prose_says"], verdict=v["verdict"], reason=v["reason"],
                sentence=sentence_around(p.marked, s.k),
            ))
    return findings


def summary(findings: list[Finding]) -> dict:
    counts = {v: sum(1 for f in findings if f.verdict == v) for v in VERDICTS}
    return {"slots_in_prose": len(findings), **counts,
            "disagreements": [f.as_dict() for f in findings if f.verdict == "disagrees"]}
