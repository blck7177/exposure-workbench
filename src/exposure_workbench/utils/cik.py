"""One spelling for a CIK (V17).

A CIK is a number, and three sources write it three ways. SEC's company_tickers
feed gives an integer, which the security-master provider zero-pads to ten
because that is the form SEC's own URLs take (`CIK0000320193`). edgartools
hands back `str(int(cik))`, unpadded. The seed script wrote the unpadded form by
hand.

Nothing noticed while `companies` had one writer and its rows were typed in by a
person. The moment a row could be built FROM the security master, readiness
step 1 compared "0000320193" against "320193", found them different, and failed
every newly admitted issuer with a CIK mismatch — two spellings of one number,
reported as a disagreement about identity.

So the desk has one canonical form, and every comparison and every write goes
through this function. The padding is presentation and belongs where a URL is
built, not in a stored identity.
"""

from __future__ import annotations


def canonical(value: str | int | None) -> str | None:
    """The CIK as this desk stores and compares it: digits, no leading zeros.

    Returns None for anything that is not a CIK — empty, whitespace, or a
    string with a non-digit in it. None means "no CIK", never "some CIK I
    could not read": a caller that needs one refuses on None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    return str(int(text))


def same(a: str | int | None, b: str | int | None) -> bool:
    """Whether two CIKs are the same number. Two Nones are not the same CIK —
    an absent identity does not match an absent identity."""
    ca, cb = canonical(a), canonical(b)
    return ca is not None and ca == cb
