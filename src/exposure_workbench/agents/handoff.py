"""S2 evidence-first handoff. Identity and persistence belong to the runtime.

Only selected ledger rows and individually checked notes cross to the lead.
The accumulator preserves accepted items while another item is repaired. It
does not decide whether a task or a user's question has been answered.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from exposure_workbench.services import answer_check, fact_boundary
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.utils.ids import new_id

PROTOCOL = "evidence-v2"
SUBMIT_TOOL = {"type": "function", "function": {
    "name": "submit",
    "description": (
        "Return selected evidence rows and optional analysis notes to the lead. Evidence can stand alone; "
        "you need not rewrite the rows or account for every task line. A note has text and refs; figures must "
        "match those refs. Use narrower notes or explicit inline pointers when equal values are ambiguous. "
        "Keep qualifications in the same note. Valid items are kept when another fails. To repair a note, "
        "use its returned id; empty text withdraws that note. Submission returns the work, not a claim of completeness."),
    "parameters": {"type": "object", "properties": {
        "evidence": {"type": "array", "maxItems": 256, "items": {"type": "string"},
                     "description": "ids of existing ledger rows to hand to the lead"},
        "notes": {"type": "array", "maxItems": 32, "items": {
            "type": "object", "properties": {
                "id": {"type": "string", "description": "only for revising a note whose id submit returned"},
                "text": {"type": "string"},
                "refs": {"type": "array", "maxItems": 256, "items": {"type": "string"}}},
            "required": ["text", "refs"], "additionalProperties": False}}},
        "required": ["evidence"], "additionalProperties": False}}}


class BadSubmission(ValueError):
    pass


def parse(args: dict) -> dict:
    """Validate the envelope; malformed items are diagnosed individually."""
    if not isinstance(args, dict) or set(args) - {"evidence", "notes"}:
        raise BadSubmission("submit takes evidence and optional notes; the old lines/settled protocol is not used")
    if not isinstance(args.get("evidence"), list) or len(args["evidence"]) > 256:
        raise BadSubmission("evidence is a list of at most 256 row ids")
    if not isinstance(args.get("notes", []), list) or len(args.get("notes", [])) > 32:
        raise BadSubmission("notes is a list of at most 32 text/refs objects")
    return {"evidence": args["evidence"], "notes": args.get("notes", [])}


@dataclass
class Submission:
    evidence: list[str] = field(default_factory=list)
    notes: dict[str, dict] = field(default_factory=dict)
    known: set[str] = field(default_factory=set)
    identities: dict[str, str] = field(default_factory=dict)
    issues: dict[str, list[dict]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def apply(self, payload: dict, ledger: Ledger, question: str) -> dict:
        note_ids = []
        # Evidence is additive. An invalid id is a rejected item in this attempt,
        # not a permanent obligation to select that nonexistent row next time.
        self.issues = {k: v for k, v in self.issues.items()
                       if not k.startswith(("evidence[", "invalid_note["))}
        for index, fid in enumerate(payload["evidence"]):
            if not isinstance(fid, str) or not ledger.holds(fid):
                self.issues[f"evidence[{index}]"] = [{"reason": "not_on_ledger",
                    "way_out": "select an existing row id from the evidence"}]
            elif fid not in self.evidence:
                self.evidence.append(fid)
        for index, note in enumerate(payload["notes"]):
            identity = json.dumps(note, sort_keys=True, ensure_ascii=False)
            nid = note.get("id") if isinstance(note, dict) else None
            if nid is not None and (not isinstance(nid, str) or nid not in self.known):
                self.issues[f"invalid_note[{index}]"] = [{"reason": "unknown_note",
                    "way_out": "use an id returned by submit, or omit id for a new note"}]
                continue
            self.issues.pop(f"invalid_note[{index}]", None)
            if nid is None:
                nid = self.identities.setdefault(identity, new_id("nte_"))
                self.known.add(nid)
            note_ids.append({"index": index, "id": nid})
            if (not isinstance(note, dict) or set(note) - {"id", "text", "refs"}
                    or not isinstance(note.get("text"), str) or not isinstance(note.get("refs"), list)
                    or len(note["refs"]) > 256 or not all(isinstance(f, str) for f in note["refs"])):
                self.issues[nid] = [{"reason": "invalid_note", "way_out": "a note is text and a list of row refs"}]
                continue
            if not note["text"].strip():
                if note.get("id"):
                    self.notes.pop(nid, None)
                    self.issues.pop(nid, None)
                else:
                    self.issues[nid] = [{"reason": "empty_note", "way_out": "omit unused notes; empty text withdraws a known id"}]
                continue
            refs = list(dict.fromkeys(note["refs"]))
            canonical, verdict = fact_boundary.check_block("finding", note["text"], refs, ledger, question=question)
            if not verdict.ok:
                self.issues[nid] = verdict.problems or [{"reason": verdict.error}]
                continue
            self.issues.pop(nid, None)
            rendered = answer_check.accepted(canonical, verdict, ledger)
            self.notes[nid] = {"id": nid, "raw_text": note["text"], "text": canonical,
                               "refs": refs, "blocks": rendered["blocks"], "verified": rendered["verified"]}
        return {"accepted": self.ok, "evidence": list(self.evidence), "note_ids": note_ids,
                "kept_notes": list(self.notes),
                "problems": [{"item": item, **p} for item, errors in self.issues.items() for p in errors],
                "detail": "accepted items are kept; repair or withdraw the named notes, then submit again" if self.issues else "work returned"}

    def diagnostics(self) -> list[dict]:
        """Only codes cross to the lead. Rejected text remains in the audit."""
        return [{"item": item, "reasons": sorted({str(p.get("reason")) for p in problems})}
                for item, problems in self.issues.items()]
