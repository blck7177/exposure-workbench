"""The answer check (V33): a natural-language answer against the session ledger.

WHY THIS EXISTS. The exit it replaces (services/claims.py) asked the model to
type its own assertions — eleven relations over fact ids, `{cN}` placeholders
kept in step with a claims list by hand — and the 20-question round
(docs/spikes/v33) showed what that bought: 61 respond calls, 42 refused, and
twelve of the nineteen accepted answers false to a reader anyway, because the
gate checked the pointers and never the sentence. Q08 stated two superlatives
backwards over six legal `series` claims; Q17 shifted ten figures onto the
wrong companies when it renumbered claims; Q14 filled a date slot with a depth.

Here the model writes prose. This module reads it the way the reader will:

    G1  every number resolves — to a fact it equals at the written precision,
        to a fact's date/window/parameter, to a quoted passage that states it,
        or to the user's own question               unsourced_figure
    G2  a number that equals several different facts is pinned by the sentence
        it sits in (its subject, its measure, its date) or by a mark `[f_…]`
        after it                                    ambiguous_figure / mark_mismatch
    G3  the sentence around a figure agrees with the figure's identity:
          a superlative sits on a fact that carries a place in an ordering
          a change joins two readings of one measure of one subject, or one
            change node, and points the way the values moved
          a comparison joins two figures of one unit
          a tier word (warning, breach, limit) sits beside the tier it names
          a date word (started, troughed, as of) is followed by a date
          a company named in the sentence is the figure's company
                                                    superlative_without_rank / change_conflict /
                                                    unit_conflict / tier_mismatch / date_expected /
                                                    subject_mismatch / measure_mismatch
    G4  quotation marks hold a passage's own words   unverified_quote
    G5  `[table: node]` / `[chart: node]` name a node whose facts are on the
        ledger; `[f_…]` names a fact on it            unknown_node / not_on_ledger

Every check is a lookup on the ledger (services/ledger.py) or a word from a
short closed list; nothing here judges meaning beyond what a fact's own fields
can settle. Problems are reported ALL AT ONCE, each with the way out. The
render (`accepted`) puts the ledger's value and identity where the number
stood, in the block shape the web already reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services.gate import _core, quoted_spans, _normalise
from exposure_workbench.services.ledger import Ledger

# ── the marks a writer may put in prose ──────────────────────────────────────
MARK_FACT = re.compile(r"\[(f_[0-9A-Za-z]{4,})\]")
MARK_BLOCK = re.compile(r"\[(table|chart):\s*([A-Za-z_][A-Za-z0-9_]*)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z“\"(\[])")

# ── the closed word lists G3 reads ───────────────────────────────────────────
SUPERLATIVES = frozenset("""largest smallest biggest highest lowest most least top bottom worst best weakest
strongest greatest deepest longest shortest nearest closest farthest furthest heaviest lightest tightest widest
narrowest fastest slowest jumpiest leads leading dominant""".split())
UP_WORDS = frozenset("rose up increased grew higher climbed expanded improved gained widened above outperformed".split())
DOWN_WORDS = frozenset("fell down decreased declined lower dropped shrank narrowed slipped deteriorated weakened below underperformed".split())
CHANGE_WORDS = frozenset("from to change changed moved moving move since versus vs against compared".split()) | UP_WORDS | DOWN_WORDS
TIER_WORDS = frozenset("warning breach limit tier room headroom cap".split())
DATE_WORDS = ("started", "troughed", "peaked", "bottomed", "began", "ended", "recovered", "as of", "dated")
TIER_SUFFIXES = ("warning_level", "breach_level", "limit_value")
CHANGE_OPS = ("yoy", "qoq", "pct", "cagr", "subtract")
_WORD = re.compile(r"[A-Za-z][A-Za-z_']*")
_MIN_QUOTED_WORDS = 4


@dataclass
class Verdict:
    problems: list[dict] = field(default_factory=list)
    error: str | None = None
    detail: str | None = None
    links: dict[tuple[int, int], dict] = field(default_factory=dict)     # (para, token start) -> {to, ids, as_written}
    marks: list[dict] = field(default_factory=list)                       # block marks: {para, start, end, kind, node, ids}
    refs: list[str] = field(default_factory=list)                         # every fact id the answer rests on

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_refusal(self) -> dict:
        return {"error": self.error, "problems": self.problems, "detail": self.detail}


# ── helpers over the ledger ──────────────────────────────────────────────────

def _short_subject(subject: str | None) -> str | None:
    """`issuer_concentration:MSFT` -> MSFT; `Technology` -> Technology; a row id -> None."""
    if not isinstance(subject, str) or not subject:
        return None
    if subject.startswith(("calc_", "run_", "port_", "task_", "rrun_")):
        return None
    return subject.rsplit(":", 1)[-1]


def _identity(rec: dict) -> tuple:
    return (rec.get("measure"), rec.get("subject"), rec.get("as_of"), str(rec.get("window")))


def _is_tier(rec: dict) -> bool:
    return any((rec.get("measure") or "").endswith(s) for s in TIER_SUFFIXES)


# Words a producer puts in a measure's own name when the figure IS a place in an
# ordering: the deepest episode, a max drawdown, the first of a list. Such a
# fact backs a superlative the way a rank entry does.
_ORDER_WORDS = frozenset("deepest largest smallest highest lowest worst best top max min first last peak trough".split())


def _ordered(rec: dict) -> bool:
    if "rank" in (rec.get("params") or {}):
        return True
    parts = set(re.split(r"[^A-Za-z0-9]+", (rec.get("measure") or "").lower())) | ({"first"} if "[0]" in (rec.get("measure") or "") else set())
    return bool(parts & _ORDER_WORDS)


def _words(text: str) -> set[str]:
    return {w.lower().strip("'") for w in _WORD.findall(text)}


def _measure_words(measure: str | None) -> list[str]:
    """The last segment of a measure as words: `portfolio.reconcile.factor_share` -> 'factor share'."""
    if not measure:
        return []
    tail = re.split(r"[.:()]", measure)[-1] if "(" not in measure else measure
    return [w for w in tail.replace("_", " ").split() if w]


def _same_check(a: str | None, b: str | None) -> bool:
    """Whether a tier and a reading belong to one check: `issuer_concentration:MSFT`
    against itself, against `MSFT`, or against the check's default row."""
    ta, tb = str(a or ""), str(b or "")
    if not ta or not tb:
        return True
    return (ta == tb or ta.endswith(":" + tb) or tb.endswith(":" + ta)
            or ta.split(":")[0] == tb.split(":")[0])


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for s, e in spans:
        out = out[:s] + " " * (e - s) + out[e:]
    return out


# ── the check ────────────────────────────────────────────────────────────────

def check(text: str, ledger: Ledger, question: str | None = None) -> Verdict:
    v = Verdict()
    paras = [p for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    if not paras:
        v.error, v.detail = "empty_answer", "the answer has no text"
        return v
    asked = {_core(t["token"]) for t in A.tokens_in(question or "")}
    all_passages = list(ledger.passages)
    subjects_on_ledger = {s for s in (_short_subject(r.get("subject")) for r in ledger.by_id.values()) if s}
    two_word_measures = {" ".join(_measure_words(r.get("measure"))).lower(): r.get("measure")
                         for r in ledger.by_id.values() if len(_measure_words(r.get("measure"))) >= 2}

    for i, para in enumerate(paras):
        # G5 — the marks
        mark_spans: list[tuple[int, int]] = []
        for m in MARK_BLOCK.finditer(para):
            kind, node = m.group(1), m.group(2)
            ids = [fid for fid, r in ledger.by_id.items() if (r.get("params") or {}).get("node") == node
                   and r.get("kind") in (F.SCALAR, F.SERIES)]
            if not ids:
                v.problems.append({"at": f"prose[{i}]", "reason": "unknown_node", "node": node,
                                   "fix": "a [table: …] or [chart: …] names a binding of a program this turn ran, and its facts are on the ledger"})
            else:
                v.marks.append({"para": i, "start": m.start(), "end": m.end(), "kind": kind, "node": node, "ids": ids})
                v.refs += ids
            mark_spans.append((m.start(), m.end()))
        fact_marks: dict[int, str] = {}                     # mark start -> fact id
        for m in MARK_FACT.finditer(para):
            fid = m.group(1)
            if not ledger.holds(fid):
                v.problems.append({"at": f"prose[{i}]", "reason": "not_on_ledger", "id": fid,
                                   "fix": "a [f_…] names a fact a tool result showed this session"})
            else:
                fact_marks[m.start()] = fid
                v.refs.append(fid)
            mark_spans.append((m.start(), m.end()))
        blanked = _blank(para, mark_spans)

        # G4 — quotations: verified spans exempt their digits
        quoted_ok: list[tuple[int, int]] = []
        for span in quoted_spans(blanked):
            hit = [pid for pid in all_passages if _normalise(span) in _normalise(ledger.passages[pid])]
            start = blanked.find(span)
            if hit:
                quoted_ok.append((start, start + len(span)))
                v.refs += hit[:1]
            else:
                v.problems.append({"at": f"prose[{i}]", "reason": "unverified_quote", "quote": span[:120],
                                   "fix": "quotation marks say these words are verbatim in a passage read this turn: reproduce the source wording, or drop the marks"})

        sentences = _sentences(blanked)
        tokens = A.tokens_in(blanked)
        linked_by_sentence: dict[int, list[tuple[dict, list[dict]]]] = {}     # sentence idx -> [(token, alias records)]

        # G1 / G2 — every token
        for t in tokens:
            tok, kind, start, end = t["token"], t["kind"], t["start"], t["end"]
            if any(s <= start < e for s, e in quoted_ok):
                continue
            if kind == "id":
                v.problems.append({"at": f"prose[{i}]", "reason": "id_in_prose", "id": tok,
                                   "fix": "an id is not a word the reader sees: write the figure, and put [f_…] after it only when it is ambiguous"})
                continue
            si = next((k for k, (s, e) in enumerate(sentences) if s <= start < e), 0)
            sentence = blanked[sentences[si][0]:sentences[si][1]]
            swords = _words(sentence)
            pinned = next((fid for ms, fid in fact_marks.items() if end <= ms <= end + 1), None)
            ids = ledger.resolve_number(tok) if kind == "num" else []
            if pinned:
                if pinned not in ids and pinned not in ledger.resolve_identity(tok):
                    rec = ledger.by_id[pinned]
                    v.problems.append({"at": f"prose[{i}]", "reason": "mark_mismatch", "figure": tok, "id": pinned,
                                       "fact": {"measure": rec.get("measure"), "subject": rec.get("subject"), "value": rec.get("value")},
                                       "fix": "the marked fact does not hold this number: mark the fact that does, or write its value as shown"})
                    continue
                ids = [pinned]
            if ids:
                chosen, why, evidenced = _pin(ids, ledger, sentence, swords)
                if chosen is not None and not evidenced and not pinned and _core(tok) in asked:
                    # the user wrote this number and nothing in the sentence ties it to
                    # the ledger's reading of it: it is the user's ("at 20% of ADV")
                    v.links[(i, start)] = {"to": "question", "ids": [], "as_written": tok}
                    continue
                if chosen is None:
                    if _core(tok) in asked:
                        v.links[(i, start)] = {"to": "question", "ids": [], "as_written": tok}
                        continue
                    v.problems.append({"at": f"prose[{i}]", "reason": "ambiguous_figure", "figure": tok, "candidates": why,
                                       "fix": "several facts hold this number: name the subject or measure in the sentence, or put [f_…] after the number"})
                    continue
                primary = pinned or _primary(chosen, ledger, swords)
                v.links[(i, start)] = {"to": "fact", "ids": chosen, "primary": primary, "as_written": tok}
                linked_by_sentence.setdefault(si, []).append((t, [ledger.by_id[f] for f in chosen]))
                continue
            ids = ledger.resolve_identity(tok)
            if ids:
                v.links[(i, start)] = {"to": "fact", "ids": ids, "as_written": tok}
                continue
            pids = ledger.resolve_in_passages(tok, all_passages)
            if pids:
                v.links[(i, start)] = {"to": "passage", "ids": pids, "as_written": tok}
                continue
            if _core(tok) in asked:
                v.links[(i, start)] = {"to": "question", "ids": [], "as_written": tok}
                continue
            v.problems.append({"at": f"prose[{i}]", "reason": "unsourced_figure", "figure": tok,
                               "fix": "a number the ledger cannot account for: request the figure, quote the passage that states it, or drop it"})

        # G3 — the sentence around the figures
        for si, (s, e) in enumerate(sentences):
            sentence = blanked[s:e]
            linked = linked_by_sentence.get(si, [])
            words = _words(sentence)
            _check_sentence(v, i, sentence, s, words, linked, tokens, ledger, subjects_on_ledger, two_word_measures)

    v.refs = list(dict.fromkeys([*v.refs, *[l.get("primary") or fid for l in v.links.values() for fid in l["ids"][:1]]]))
    if v.problems:
        order = ("not_on_ledger", "unknown_node", "id_in_prose", "mark_mismatch", "unsourced_figure", "ambiguous_figure",
                 "unverified_quote", "date_expected", "subject_mismatch", "measure_mismatch", "superlative_without_rank",
                 "change_conflict", "unit_conflict", "direction_conflict", "tier_mismatch")
        reasons = {p["reason"] for p in v.problems}
        v.error = next((r for r in order if r in reasons), v.problems[0]["reason"])
        v.detail = (f"{len(v.problems)} problem(s), all listed; the first: " + _one_line(v.problems[0]))
    return v


def _one_line(p: dict) -> str:
    what = p.get("figure") or p.get("id") or p.get("node") or p.get("quote") or p.get("word") or ""
    return f"{p['at']} {p['reason']}" + (f" ({what!r})" if what else "") + (f": {p['fix']}" if p.get("fix") else "")


def _group_key(rec: dict) -> tuple:
    """Facts that hold one written value and share a subject and a date are one
    READING under several names — a holding's weight, the concentration check's
    current_value that reads it, the rank entry over it. They are aliases, not
    an ambiguity; the ambiguity the reader cares about is two subjects or two
    dates holding the same number."""
    return (_short_subject(rec.get("subject")) or rec.get("subject"), rec.get("as_of"))


def _pin(ids: list[str], ledger: Ledger, sentence: str, words: set[str]) -> tuple[list[str] | None, list[dict], bool]:
    """(alias ids, candidates, evidenced) for a written number. One group of
    aliases is taken as is; several are narrowed by the sentence's own words in
    stages — its subject first, then its measure, then its date — each stage
    keeping the groups it names and passing when it names none. `evidenced`
    says whether the sentence named the chosen group at all, which is what lets
    a number the user also wrote be read as the ledger's rather than the user's."""
    groups: dict[tuple, list[str]] = {}
    for fid in ids:
        groups.setdefault(_group_key(ledger.by_id[fid]), []).append(fid)
    low = sentence.lower()

    def by_subject(g: list[str]) -> bool:
        for r in (ledger.by_id[f] for f in g):
            short = _short_subject(r.get("subject"))
            if short and (short.lower() in words or short.lower() in low):
                return True
        return False

    def by_measure(g: list[str]) -> bool:
        return any(len(w) > 3 and w.lower() in words for f in g for w in _measure_words(ledger.by_id[f].get("measure")))

    def by_date(g: list[str]) -> bool:
        return any(str(ledger.by_id[f].get("as_of") or "\0") in sentence for f in g)

    if len(groups) == 1:
        g = next(iter(groups.values()))
        return g, [], by_subject(g) or by_measure(g) or by_date(g)
    evidenced = False
    for stage in (by_subject, by_measure, by_date):
        kept = {k: g for k, g in groups.items() if stage(g)}
        if kept:
            evidenced = True
            groups = kept
        if len(groups) == 1:
            return next(iter(groups.values())), [], evidenced
    # the default tier row (`issuer_concentration`) beside issuers' own rows is one tier
    if all(_is_tier(ledger.by_id[g[0]]) for g in groups.values()):
        specific = {k: g for k, g in groups.items() if ":" in str(ledger.by_id[g[0]].get("subject") or "")}
        if len(specific) == 1:
            return next(iter(specific.values())), [], True
        if not specific:
            return next(iter(groups.values())), [], evidenced
    cands = [{"id": g[0], "measure": ledger.by_id[g[0]].get("measure"), "subject": ledger.by_id[g[0]].get("subject"),
              "as_of": ledger.by_id[g[0]].get("as_of")} for g in list(groups.values())[:6]]
    return None, cands, False


def _primary(alias_ids: list[str], ledger: Ledger, words: set[str]) -> str:
    """Which alias the reader is shown: the rank entry under a superlative, the
    tier under a tier word, the measure the sentence names, else the first."""
    recs = [ledger.by_id[f] for f in alias_ids]
    if words & SUPERLATIVES:
        for r in recs:
            if "rank" in (r.get("params") or {}):
                return r["id"]
    if words & TIER_WORDS:
        for r in recs:
            if _is_tier(r):
                return r["id"]
    for r in recs:
        if any(len(w) > 3 and w.lower() in words for w in _measure_words(r.get("measure"))):
            return r["id"]
    return alias_ids[0]


def _check_sentence(v: Verdict, i: int, sentence: str, offset: int, words: set[str], linked: list, tokens: list,
                    ledger: Ledger, subjects_on_ledger: set[str], two_word_measures: dict) -> None:
    """The sentence around its figures. `linked` is [(token, [alias records])]
    in reading order; a check that any alias satisfies is satisfied."""
    at = f"prose[{i}]"
    groups = [recs for _t, recs in linked if recs and recs[0].get("kind") == F.SCALAR]
    firsts = [recs[0] for recs in groups]
    low = sentence.lower()

    # a company named in the sentence is the figure's company (tickers only:
    # a sector or a check name is not something a reader mis-attributes)
    tickers = {s for s in subjects_on_ledger if s.isupper() and 1 <= len(s) <= 6}
    named = {w.upper() for w in words if w.upper() in tickers}
    if named:
        for t, recs in linked:
            short = _short_subject(recs[0].get("subject"))
            if short and short in tickers and short not in named:
                v.problems.append({"at": at, "reason": "subject_mismatch", "figure": t["token"], "id": recs[0]["id"],
                                   "figure_subject": recs[0].get("subject"), "sentence_names": sorted(named)[:6],
                                   "fix": f"this figure is {recs[0].get('subject')}'s ({recs[0].get('measure')}); the sentence names {', '.join(sorted(named)[:3])}"})

    # a measure the sentence names is the measure of a figure in it
    for phrase, measure in two_word_measures.items():
        if phrase and phrase in low and groups and not any(r.get("measure") == measure for recs in groups for r in recs):
            v.problems.append({"at": at, "reason": "measure_mismatch", "phrase": phrase, "linked": [r["id"] for r in firsts][:4],
                               "fix": f"the sentence says '{phrase}' but its figure(s) are {', '.join(sorted({str(r.get('measure')) for r in firsts})[:3])}; "
                                      f"the ledger holds {measure} as its own fact — write that value, or drop the phrase"})
            break

    # a superlative rests on a place in an ordering
    if words & SUPERLATIVES and groups:
        if not any(_ordered(r) for recs in groups for r in recs):
            v.problems.append({"at": at, "reason": "superlative_without_rank", "word": sorted(words & SUPERLATIVES)[0],
                               "linked": [r["id"] for r in firsts][:4],
                               "fix": "a largest/smallest/most/least rests on a rank node: request the ordering (compare: rank) and state its entry, or drop the word"})

    # a date word is followed by a date
    for dw in DATE_WORDS:
        for m in re.finditer(r"\b" + re.escape(dw) + r"\b", sentence, flags=re.IGNORECASE):
            nxt = next((t for t in tokens if t["start"] >= offset + m.end() and t["start"] < offset + len(sentence)), None)
            if nxt and nxt["kind"] == "num" and nxt["start"] - (offset + m.end()) <= 12:
                v.problems.append({"at": at, "reason": "date_expected", "word": dw, "figure": nxt["token"],
                                   "fix": f"'{dw}' introduces a date; this figure is not one — the date is on the facts' window (start/end) or as_of"})

    # tier words sit beside the tier they name
    tier_words = words & TIER_WORDS
    tiers = [r for recs in groups for r in recs if _is_tier(r)]
    readings = [recs[0] for recs in groups if not any(_is_tier(r) for r in recs)]
    if tier_words and tiers:
        kinds = {("warning" if t["measure"].endswith("warning_level") else "breach" if t["measure"].endswith("breach_level") else "limit") for t in tiers}
        if "warning" in words and "warning" not in kinds and kinds:
            v.problems.append({"at": at, "reason": "tier_mismatch", "id": tiers[0]["id"],
                               "fix": f"the sentence says warning; the tier figure here is the {sorted(kinds)[0]} tier"})
        if "breach" in words and "breach" not in kinds and kinds:
            v.problems.append({"at": at, "reason": "tier_mismatch", "id": tiers[0]["id"],
                               "fix": f"the sentence says breach; the tier figure here is the {sorted(kinds)[0]} tier"})
        for tier in tiers:
            for rd in readings:
                if "room" in (rd.get("measure") or "") or (rd.get("measure") or "").startswith("subtract("):
                    continue
                if not _same_check(tier.get("subject"), rd.get("subject")):
                    v.problems.append({"at": at, "reason": "tier_mismatch", "id": tier["id"], "reading": rd["id"],
                                       "fix": f"{tier.get('subject')}'s tier beside {rd.get('subject')}'s reading: a tier sits beside its own check's reading"})

    # a change or a comparison joins the right two figures, and points the way they moved
    up, down = words & UP_WORDS, words & DOWN_WORDS
    if words & CHANGE_WORDS and len(groups) >= 2:
        ga, gb = groups[0], groups[1]
        a, b = ga[0], gb[0]
        if a.get("unit") != b.get("unit"):
            v.problems.append({"at": at, "reason": "unit_conflict", "ids": [a["id"], b["id"]],
                               "fix": f"{a.get('unit')} beside {b.get('unit')}: a change or comparison joins two figures of one unit"})
            return
        same_group = _group_key(a) == _group_key(b)
        same_measure = a.get("measure") == b.get("measure") or same_group
        same_subject = (_short_subject(a.get("subject")) or a.get("subject")) == (_short_subject(b.get("subject")) or b.get("subject"))
        va, vb = float(a["value"]), float(b["value"])
        if same_group and abs(va - vb) < 1e-12:
            v.problems.append({"at": at, "reason": "change_conflict", "ids": [a["id"], b["id"]],
                               "fix": "the two figures are one reading written twice; a change is two dates, a comparison two subjects"})
        elif same_measure and same_subject:
            if a.get("as_of") and b.get("as_of") and a.get("as_of") != b.get("as_of"):
                earlier, later = sorted((a, b), key=lambda r: str(r.get("as_of")))
                moved_up = float(later["value"]) > float(earlier["value"])
            else:
                moved_up = vb > va            # "from A to B": the order written
            if (up and not moved_up) or (down and moved_up):
                v.problems.append({"at": at, "reason": "direction_conflict", "ids": [a["id"], b["id"]],
                                   "fix": f"the figure moved {'up' if moved_up else 'down'}; the sentence says the opposite"})
        elif same_measure and not same_subject:
            if up or down:
                first_higher = va > vb
                if (up and not first_higher) or (down and first_higher):
                    v.problems.append({"at": at, "reason": "direction_conflict", "ids": [a["id"], b["id"]],
                                       "fix": f"{a.get('subject')} is {'above' if first_higher else 'below'} {b.get('subject')} on {a.get('measure')}; the sentence says the opposite"})
        elif not same_measure and words & {"from", "to", "rose", "fell", "increased", "decreased", "grew", "declined", "change", "changed", "moved"}:
            if not any((r.get("params") or {}).get("op") in CHANGE_OPS for r in (a, b)):
                v.problems.append({"at": at, "reason": "change_conflict", "ids": [a["id"], b["id"]],
                                   "fix": f"{a.get('measure')} and {b.get('measure')} are two different quantities; a change is one measure of one subject at two dates"})
    elif (up or down) and len(groups) == 1:
        r = next((x for x in groups[0] if (x.get("params") or {}).get("op") in CHANGE_OPS), None)
        if r is not None:
            val = float(r["value"])
            if (up and val < 0) or (down and val > 0):
                v.problems.append({"at": at, "reason": "direction_conflict", "ids": [r["id"]],
                                   "fix": f"this change is {'negative' if val < 0 else 'positive'}; the sentence points the other way"})


# ── the render ───────────────────────────────────────────────────────────────

def accepted(text: str, verdict: Verdict, ledger: Ledger) -> dict:
    """The answer as stored and shown: paragraphs whose numbers carry their
    fact, the tables and charts the marks asked for, in the block shape
    services/answer.rendered already emits."""
    paras = [p for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    blocks: list[dict] = []
    for i, para in enumerate(paras):
        cuts: list[tuple[int, int, str, Any]] = []
        for m in MARK_FACT.finditer(para):
            cuts.append((m.start(), m.end(), "drop", None))
        for mk in verdict.marks:
            if mk["para"] == i:
                cuts.append((mk["start"], mk["end"], "block", mk))
        for (pi, start), link in verdict.links.items():
            if pi == i and link["to"] != "question":
                cuts.append((start, start + len(link["as_written"]), "link", link))
        cuts.sort(key=lambda c: c[0])
        runs: list = []
        pos = 0
        after: list[dict] = []
        for s, e, kind, payload in cuts:
            if s < pos:
                continue
            if s > pos:
                runs.append(para[pos:s])
            if kind == "link":
                if payload["to"] == "fact" and len(payload["ids"]) >= 1:
                    runs.append({"fact": A.fill(ledger.by_id[payload.get("primary") or payload["ids"][0]])})
                else:
                    runs.append({"link": {"to": payload["to"], "ids": payload["ids"], "as_written": para[s:e]}})
            elif kind == "block":
                after.append(_block_for(payload, ledger))
            pos = e
        if pos < len(para):
            runs.append(para[pos:])
        runs = [r for r in runs if r != ""]
        if runs:
            blocks.append({"type": "paragraph", "runs": runs})
        blocks += [b for b in after if b]
    facts_used = list(dict.fromkeys(verdict.refs))
    figures = [ledger.by_id[f] for f in facts_used if f in ledger.by_id and ledger.kind(f) in (F.SCALAR, F.SERIES)]
    passages = [f for f in facts_used if ledger.kind(f) == F.PASSAGE]
    return {"blocks": blocks, "text": A.prose_of(blocks), "citations": facts_used,
            "verified": {"figures": len(figures), "sources": len(passages),
                         "matches": [{"label": r.get("measure"), "value": r.get("value"), "unit_class": r.get("unit"),
                                      "source_id": r["id"], "subject": r.get("subject"), "as_of": r.get("as_of")} for r in figures]}}


def _block_for(mark: dict, ledger: Ledger) -> dict | None:
    recs = [ledger.by_id[fid] for fid in mark["ids"]]
    series = [r for r in recs if r.get("kind") == F.SERIES]
    if mark["kind"] == "chart" and series:
        return {"type": "chart", "kind": "line", "title": mark["node"], "fact": A.fill(series[0])}
    rows = [r for r in recs if r.get("kind") == F.SCALAR]
    if not rows and series:
        return {"type": "chart", "kind": "line", "title": mark["node"], "fact": A.fill(series[0])}
    if not rows:
        return None
    grid = [[A.fill(r)] for r in rows]
    return {"type": "table", "title": mark["node"], "rows": [[{"fact": f} for f in row] for row in grid], **A.derive_table(grid)}
