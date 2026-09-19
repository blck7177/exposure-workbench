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
from exposure_workbench.analytics import registry
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
            sources=list(f.sources), group=f.group, means=dict(f.means),
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
        if isinstance(v, bool) or k in ("node", "pull", "tool"):
            # `node` is the program's BINDING NAME — a variable, never a measure
            # and never an identity (it named a program's variable until V1). V33D: the node
            # `amzn_rel_1y_vs_spy` put "1" among this fact's identity tokens, and
            # the analyst's "1-year" resolved to it.
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
    _series: list[dict] = field(default_factory=list)
    _tol: dict = field(default_factory=dict)           # (value, unit) -> the desk's own precision

    def __post_init__(self) -> None:
        # WHAT THE DESK DOES NOT SAY STANDS ON EVERY LEDGER (V1). A line a policy
        # stops is filed "not settled" with the id of a boundary, and no tool
        # mints one for a policy — nothing was asked of a tool. The three
        # policies are facts under fixed ids (analytics/registry), here before
        # anything a session shows, so a sentence can point at them and the
        # check resolves the pointer like any other.
        for rec in registry.POLICY_ABSENCES:
            self.add(dict(rec))

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
        if rec.get("kind") == F.SERIES and isinstance(rec.get("points"), list):
            self._series.append(rec)
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

    def means(self, fid: str) -> dict:
        """The registry words the fact carries (its direction, status, flags)."""
        r = self.by_id.get(fid)
        return dict(r.get("means") or {}) if r else {}

    @property
    def shown(self) -> dict[str, dict]:
        """The facts this SESSION put on the ledger — without the standing policies."""
        return {k: v for k, v in self.by_id.items() if k not in registry.POLICY_IDS}

    @property
    def measures(self) -> set[str]:
        return {r.get("measure") for r in self.by_id.values() if isinstance(r.get("measure"), str)}

    # ── G3: a number written in prose ──
    # ONE rule, asked of the written token: did the writer use the desk's unit
    # marker? A percent sign, a dollar, a multiple's ×, a money scale, a flow's
    # "/day" say "this is the figure as you showed it" and the number is read in
    # that marker's terms; a bare number is read as the stored value itself.
    # Everything else the reader may vary — rounding, "M" vs "million", the
    # dropped "/day" — falls out of the tolerance, which is half a unit of the
    # last digit written (a hair more, so 0.1625 written as 16.3% does not miss
    # by one float ulp). No other coercion: V33D's "1-year" became "1.07%" and
    # V33B's bare "16.3" matched three unrelated ratios through the ones deleted
    # here (a bare number guessed as a percentage, a money scale swept blind).
    _WRITTEN = re.compile(r"\s*([+\-−]?)\s*(\$?)\s*([\d,]*\.?\d+)\s*(%|×|x|X)?\s*"
                          r"([KkMmBb]|bn|mn|million|billion|thousand)?\s*(?:/\s*day|\s+a\s+day)?\s*")
    _SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
               "b": 1e9, "bn": 1e9, "billion": 1e9}

    @staticmethod
    def written(token: str) -> tuple[float, float, bool, int] | None:
        """(value, the writer's own tolerance, whether a unit marker was used,
        decimals) of a written figure in the STORED quantity's terms, or None
        when the token is not a figure. `16.0%` is 0.160 marked, `$10.63M` is
        10 630 000 marked, `0.78×` is 0.78 marked, a bare `0.1625` is 0.1625."""
        m = Ledger._WRITTEN.fullmatch(token or "")
        if not m:
            return None
        sign, dollar, core, mark, suffix = m.groups()
        try:
            v = float(core.replace(",", ""))
        except ValueError:
            return None
        if sign in ("-", "−"):
            v = -v
        decimals = len(core.split(".")[1]) if "." in core else 0
        tol = 0.5 * 10 ** (-decimals) * (1 + 1e-9) + 1e-12
        factor = 1.0
        if mark == "%":
            factor = 0.01
        if suffix:
            factor *= Ledger._SCALES.get(suffix.lower(), 1.0)
        marked = bool(dollar or mark or suffix)
        return v * factor, tol * factor, marked, decimals

    def _readings_of(self, rec: dict):
        """(period, value) for every reading one fact holds: a scalar holds one
        on its own date, a series one per point."""
        if rec.get("kind") == F.SCALAR and isinstance(rec.get("value"), (int, float)):
            yield None, float(rec["value"])
        for pt in rec.get("points") or []:
            try:
                yield str(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                continue

    def _tolerance(self, val: float, unit: str | None) -> float:
        """Half a unit of the last digit the DESK showed. The analyst was told to
        write the figure as it was shown, so the desk's precision is the match's:
        at the writer's own precision a bare "1" is a correct rounding of 0.78,
        which is how V33D's "1-year" reached a MULTIPLE."""
        key = (val, unit)
        if key not in self._tol:
            shown = dc.display(val, unit) if unit else f"{val!r}"
            parsed = self.written(shown)
            self._tol[key] = parsed[1] if parsed else 1e-12
        return self._tol[key]

    @staticmethod
    def _reads_as(val: float, w: tuple[float, float, bool, int], shown_tol: float) -> bool:
        """Whether one stored value is the figure the analyst wrote."""
        v, writer_tol, marked, decimals = w
        if marked:
            # the analyst copied the form the desk showed: the desk's precision decides
            return abs(val - v) <= shown_tol
        # a bare number is the stored quantity itself, at the precision written —
        # and a bare WHOLE number is a whole quantity, not a coarse rounding of
        # one (V33D: "1-year" is not a reading of 0.78×)
        if decimals == 0 and not float(val).is_integer():
            return False
        return abs(val - v) <= writer_tol

    def readings(self, token: str) -> list[tuple[str, str | None]]:
        """(fact id, period) for every reading the written figure equals. The
        period is None for a scalar and the point's own date for a series, so
        the citation stays the series' while the figure is that point."""
        w = self.written(token)
        if w is None:
            return []
        out: list[tuple[str, str | None]] = []
        for rec in (*self._scalars, *self._series):
            unit = rec.get("unit")
            for period, val in self._readings_of(rec):
                if self._reads_as(val, w, self._tolerance(val, unit)):
                    out.append((rec["id"], period))
        return out

    def resolve_number(self, token: str) -> list[str]:
        """The scalar facts a written figure equals — `readings` without the
        series. The claims grammar (brief path) addresses a series point as
        `f_…@period` instead, so it asks only this."""
        return list(dict.fromkeys(fid for fid, period in self.readings(token) if period is None))

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

    # THE SPACING IS THE WRITER'S, THE WORDS ARE THE SOURCE'S (V37). The token's
    # spaces were stripped and the passage's were not, so a figure written WITH
    # its scale word could never be found: the filing says "$99.3 billion" and
    # the pattern looked for "99.3billion". Only the bare form worked, which is
    # the one form the desk's own rule does not ask for.
    #
    # It cost round B its Q03. The 10-K states the buyback authorization only in
    # prose; the analyst pointed a figure at the passage that states it and read
    # "that passage does not state this figure", then quoted two words of it and
    # read "quote the passage that states it" — the two ways out pointing at each
    # other, five submissions apart — and the lead then invented $14.7B and an id
    # to carry it. Both messages were true to the code and false to the passage.
    def short_bare_in_passages(self, token: str, cited: Sequence[str]) -> list[str]:
        """The passages that DO hold a token `resolve_in_passages` will not take
        because it is a short number written bare. Not a resolution — the rule
        above stands — but what a refusal needs in order to be true to the passage:
        "does not state this figure" was said of a passage reading "Debt to capital
        14.0" (V1 live smoke), and the writer, told nothing it could act on, sent
        the same sentence again and lost the answer."""
        tok = (token or "").strip()
        core = re.sub(r"[$,%]", "", tok).strip()
        if not core or self._MARKED.search(tok) or len(re.sub(r"\D", "", core)) >= self._MIN_BARE_DIGITS:
            return []
        pat = re.compile(r"(?<![\d.])" + re.escape(core) + r"(?![\d])")
        return [pid for pid in cited if pid in self.passages and pat.search(self.passages[pid])]

    def dates_in_passages(self, iso: str, cited: Sequence[str]) -> list[str]:
        """The cited passages that state this date in any spelling."""
        from exposure_workbench.services import answer as _answer
        return [pid for pid in cited if pid in self.passages and iso in _answer.dates_stated(self.passages[pid])]

    def resolve_in_passages(self, token: str, cited: Sequence[str]) -> list[str]:
        tok = (token or "").strip()
        core = re.sub(r"[$,%]", "", tok)
        if not core.strip():
            return []
        if not self._MARKED.search(tok) and len(re.sub(r"\D", "", core)) < self._MIN_BARE_DIGITS:
            return []
        # The digits and the scale word are matched as they are written, with the
        # spacing between them free: "$99.3 billion", "$99.3billion" and the
        # filing's own "$99.3 billion" are one figure. The WORDS are not coerced —
        # "bn" is not looked up as "billion", because the spacing is the writer's
        # and the words are the source's.
        parts = re.findall(r"\d[\d.]*|[A-Za-z]+", core)
        if not parts:
            return []
        pat = re.compile(r"(?<![\d.])" + r"\s*".join(re.escape(x) for x in parts) + r"(?![\d])", re.IGNORECASE)
        return [pid for pid in cited if pid in self.passages and pat.search(self.passages[pid])]


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
        "means": row.means or {},
        "group": row.group, "session_id": row.session_id, "step_id": row.step_id, "message_id": row.message_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
