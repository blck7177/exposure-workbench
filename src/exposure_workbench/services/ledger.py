"""The session ledger (V24): every Fact this session has shown, by id, and the
indices the gate resolves against.

WHY THIS EXISTS. The table it replaces (services/table.py) was rebuilt from
storage on every load: each declared id re-queried, each number re-named,
run scopes narrowed until the slice fit. What the model saw and what the gate
held were two builds of one thing, and they differed exactly where the
batteries failed. The ledger is not built: it is READ. A tool's facts are
recorded on the step in their record form (`{"facts": [...]}` in
agent_steps.evidence_refs) at the moment they were shown, and the ledger is
the union of those records for the session. No query per fact, no naming, no
narrowing — an id the model was shown is on the ledger, by construction.

THREE INDICES, for the gate's three lookups (IMPLEMENTATION_PLAN_V24 §8 C):
    by_id            G1  is this id on the ledger; what kind is it       (G2)
    values           G3  which facts does a number written in prose equal —
                         exactly, at the precision it was written, or under a
                         money scale
    identity_tokens  G3  which facts carry this token as a FIELD: an as-of
                         date or its year, a period, a window, a parameter
                         (a confidence level, a benchmark, a rank), a digit run
                         in the measure's own name
    passages         G3  a passage fact's text, for the quotation check and for
                         a figure written from a cited passage
Every one is a dictionary lookup. The digit-run regex that FINDS tokens in
prose lives in the gate; nothing here reads prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.db.models import AgentStep, FactRecord
from exposure_workbench.services import facts as F

_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")

# The money scales a reader writes: "$1.79M", "$38.1bn", "1,785,420".
MONEY_SCALES = ((1.0, ""), (1e3, "K"), (1e6, "M"), (1e9, "B"))

STEP_ENTRY_KEY = "facts"   # the evidence_refs entry that carries a step's facts


# ── the record on the step ────────────────────────────────────────────────────

def step_entry(facts: Sequence[F.Fact]) -> dict:
    """The evidence_refs entry a step carries for its facts."""
    return {STEP_ENTRY_KEY: [F.for_record(f) for f in facts]}


def rows_for(facts: Sequence[F.Fact], *, session_id: str, step_id: str | None,
             message_id: str | None) -> list[FactRecord]:
    """The facts table rows for one step's facts."""
    out = []
    for f in facts:
        out.append(FactRecord(
            id=f.id, session_id=session_id, step_id=step_id, message_id=message_id,
            kind=f.kind, subject=f.subject, measure=f.measure, unit=f.unit, value=f.value,
            points=[list(p) for p in f.points] if f.points else None, text=f.text,
            as_of=f.as_of, window=f.window, params=dict(f.params), standalone=f.standalone,
            sources=list(f.sources), group=f.group,
        ))
    return out


def facts_in(entries: Iterable[Any]) -> list[dict]:
    """The fact records among a step's evidence_refs entries (pre-V24 entries are
    declarations `{type, id, scope}` and are not facts; they are skipped)."""
    out: list[dict] = []
    for e in entries or []:
        if isinstance(e, dict) and isinstance(e.get(STEP_ENTRY_KEY), list):
            out.extend(r for r in e[STEP_ENTRY_KEY] if isinstance(r, dict) and F.is_fact_id(r.get("id")))
    return out


# ── the ledger ────────────────────────────────────────────────────────────────

def _year(d: str | None) -> str | None:
    m = _DATE.match(d or "")
    return m.group(1) if m else None


def identity_tokens(rec: dict) -> set[str]:
    """The strings a Fact's identity fields would appear as in prose."""
    toks: set[str] = set()

    def date(d):
        if isinstance(d, str) and d:
            toks.add(d)
            y = _year(d)
            if y:
                toks.add(y)

    date(rec.get("as_of"))
    for v in (rec.get("window") or {}).values():
        if isinstance(v, str):
            if _DATE.match(v):
                date(v)                              # a date gives itself and its year, never its day
            else:
                toks.add(v)
                toks.update(_DIGITS.findall(v))      # "1y" -> "1"; "30d" -> "30"
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            toks.add(f"{v:g}")
    for k, v in (rec.get("params") or {}).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            toks.add(f"{v:g}")
            if 0 < v < 1:                            # a confidence level: 0.95 -> 95, 95%
                toks.add(f"{v * 100:g}")
                toks.add(f"{v * 100:g}%")
        elif isinstance(v, str):
            if _DATE.match(v):
                date(v)
            else:
                toks.add(v)
                toks.update(_DIGITS.findall(v))
    for p in rec.get("points") or []:
        if isinstance(p, (list, tuple)) and p:
            date(str(p[0]))
    toks.update(_DIGITS.findall(rec.get("measure") or ""))   # momentum_12_1 -> 12, 1; var_95_1d -> 95, 1
    toks.discard("")
    return toks


@dataclass
class Ledger:
    by_id: dict[str, dict] = field(default_factory=dict)
    passages: dict[str, str] = field(default_factory=dict)          # passage id -> text
    _tokens: dict[str, set[str]] = field(default_factory=dict)      # token -> fact ids
    _scalars: list[dict] = field(default_factory=list)

    # ── building ──
    def add(self, rec: dict) -> None:
        if not F.is_fact_id(rec.get("id")):
            return
        self.by_id.setdefault(rec["id"], rec)
        if rec.get("kind") == F.PASSAGE and isinstance(rec.get("text"), str):
            # thousands separators dropped once here, so "1,860" and "1860" are
            # one number for the lookup; the drawer shows the text as written
            self.passages[rec["id"]] = re.sub(r"(?<=\d),(?=\d)", "", rec["text"])
        if rec.get("kind") == F.SCALAR and isinstance(rec.get("value"), (int, float)):
            self._scalars.append(rec)
        for t in identity_tokens(rec):
            self._tokens.setdefault(t, set()).add(rec["id"])

    @classmethod
    def of(cls, records: Iterable[dict]) -> "Ledger":
        led = cls()
        for r in records:
            led.add(r)
        return led

    @classmethod
    def of_facts(cls, facts: Iterable[F.Fact]) -> "Ledger":
        return cls.of(F.for_record(f) for f in facts)

    # ── G1 / G2 ──
    def holds(self, fid: str) -> bool:
        return fid in self.by_id

    def kind(self, fid: str) -> str | None:
        r = self.by_id.get(fid)
        return r.get("kind") if r else None

    def standalone(self, fid: str) -> bool:
        r = self.by_id.get(fid)
        return bool(r.get("standalone", True)) if r else False

    @property
    def measures(self) -> set[str]:
        return {r.get("measure") for r in self.by_id.values() if isinstance(r.get("measure"), str)}

    # ── G3: a number written in prose ──
    def resolve_number(self, token: str) -> list[str]:
        """Fact ids whose value the written number equals: exactly, at the
        precision it was written, or under a money scale. A percent sign or a
        ratio unit compares against value×100. Empty when none."""
        m = re.fullmatch(r"\s*([+\-−]?)\s*(\$?)\s*([\d,]*\.?\d+)\s*(%?)\s*([KkMmBb]|bn|mn|million|billion|thousand)?\s*", token or "")
        if not m:
            return []
        sign, dollar, core, pct, suffix = m.groups()
        try:
            v = float(core.replace(",", ""))
        except ValueError:
            return []
        if sign in ("-", "−"):
            v = -v
        decimals = len(core.split(".")[1]) if "." in core else 0
        # Half a unit of the last digit written, and a hair more: a figure that
        # sits EXACTLY on the boundary (0.1625 written as 16.3%) misses by one
        # float ulp otherwise, and the reader is looking at the same number.
        tol = 0.5 * 10 ** (-decimals) * (1 + 1e-9) + 1e-12
        scale = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
                 "b": 1e9, "bn": 1e9, "billion": 1e9}.get((suffix or "").lower(), None)
        hits: list[str] = []
        for r in self._scalars:
            val, unit = float(r["value"]), r.get("unit")
            if pct or unit in ("RATIO", "PERCENT") and not dollar:
                if abs(val * 100 - v) <= tol * (1 if pct else 1) and (pct or _plausible_pct(v, val)):
                    hits.append(r["id"])
                    continue
            if not pct:
                if abs(val - v) <= tol:
                    hits.append(r["id"])
                    continue
                if unit == "MONEY" and (scale or dollar):
                    for s, _n in MONEY_SCALES if scale is None else ((scale, ""),):
                        if s != 1.0 and abs(val / s - v) <= tol:
                            hits.append(r["id"])
                            break
            # the exact string a reader sees ("$10.87M", "16.3%")
            if r["id"] not in hits and unit and dc.display(val, unit).lower() == (token or "").strip().lower():
                hits.append(r["id"])
        return list(dict.fromkeys(hits))

    # ── G3: an identity field ──
    def resolve_identity(self, token: str) -> list[str]:
        t = (token or "").strip()
        if not t:
            return []
        return sorted(self._tokens.get(t, set()) | self._tokens.get(t.rstrip("%"), set()))

    # ── G3: a figure from a passage ──
    # A number a passage STATES carries its unit — "$22,965 million", "82
    # percent". A bare short integer does not, and a twelve-thousand-character
    # filing contains nearly every one of them, so a substring match would
    # MANUFACTURE a source: the 2026-09-05 battery linked a forecast the desk
    # invented ("low-20s percent") to a 10-K passage that happened to contain
    # the digits 20.
    _MARKED = re.compile(r"[$%]|(?:bn|mn|[KMB]|million|billion|thousand)\s*$", re.IGNORECASE)
    _MIN_BARE_DIGITS = 4

    def resolve_in_passages(self, token: str, cited: Sequence[str]) -> list[str]:
        tok = (token or "").strip()
        core = re.sub(r"[$,%\s]", "", tok)
        if not core:
            return []
        if not self._MARKED.search(tok) and len(re.sub(r"\D", "", core)) < self._MIN_BARE_DIGITS:
            return []
        pat = re.compile(r"(?<![\d.])" + re.escape(core) + r"(?![\d])")
        return [pid for pid in cited if pid in self.passages and pat.search(self.passages[pid])]


def _plausible_pct(written: float, ratio: float) -> bool:
    """A bare '16.3' equals a ratio 0.163 only when the writer plainly meant a
    percentage — the ratio itself is under 1 and the written number is not."""
    return abs(ratio) < 1.0 and abs(written) >= 1.0


# ── loading ───────────────────────────────────────────────────────────────────

async def load(db: AsyncSession, session_id: str) -> Ledger:
    """The session's ledger: the fact records of every completed step, read as
    stored. Session-scoped by construction (a step of another session is not
    here); nothing is queried per fact."""
    rows = (await db.execute(
        select(AgentStep.evidence_refs).where(
            AgentStep.session_id == session_id, AgentStep.status == "completed")
        .order_by(AgentStep.seq))).all()
    led = Ledger()
    for (refs,) in rows:
        for rec in facts_in(refs):
            led.add(rec)
    return led


async def record(db: AsyncSession, fid: str) -> dict | None:
    """One fact from the table, in record form — the drawer's read."""
    row = (await db.execute(select(FactRecord).where(FactRecord.id == fid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id, "kind": row.kind, "measure": row.measure, "subject": row.subject, "unit": row.unit,
        "value": row.value, "points": row.points, "text": row.text, "as_of": row.as_of, "window": row.window,
        "params": row.params or {}, "standalone": row.standalone, "sources": row.sources or [],
        "group": row.group, "session_id": row.session_id, "step_id": row.step_id, "message_id": row.message_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
