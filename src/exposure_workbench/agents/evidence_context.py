"""Session-ledger evidence projections shared by lead and specialist readers.

References are resolved by the caller's session ledger. A page never substitutes
model-authored task text for a record; omitted points/text have explicit cursors.
"""
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger


def fact_page(ledger: Ledger, fid: str, offset: int = 0, *, preview: bool = False) -> dict:
    rec = ledger.by_id.get(fid)
    if rec is None:
        return {"error": "not_on_the_record", "detail": "no such row in this conversation"}
    offset = max(0, offset)
    identity = {key: rec.get(key) for key in
                ("id", "kind", "subject", "measure", "unit", "as_of", "window", "sources", "params", "standalone")}
    if rec.get("kind") == F.SCALAR:
        return {"row": F.line(rec), "identity": {**identity, "value": rec.get("value")}}
    field = "points" if rec.get("kind") == F.SERIES else "text" if rec.get("kind") == F.PASSAGE else None
    if field is None:
        return {"row": F.line(rec), "identity": identity}
    items = rec.get(field) or ([] if field == "points" else "")
    size = (12 if preview else F.SERIES_POINTS_INLINE) if field == "points" else (1024 if preview else F.PASSAGE_CHARS)
    if offset and offset >= len(items):
        return {"error": "past_the_end", "total": len(items)}
    page = items[offset:offset + size]
    end = offset + len(page)
    # The row is a labelled excerpt; text/points below are the exact page.
    # Avoid duplicating a twelve-thousand-character passage in one result.
    rendered = page[:256] if field == "text" else page
    return {"id": fid, "row": F.line({**rec, field: rendered}), "identity": identity,
            field: page, "total": len(items), "shown": [offset, end],
            "next_offset": end if end < len(items) else None}
