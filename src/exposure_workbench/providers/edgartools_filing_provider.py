"""EdgarTools implementation of FilingProvider.

edgartools objects are consumed here and never leak upward.

Fail-loud: EDGAR_IDENTITY is mandatory (the SEC requires a contact UA). A missing
identity raises at construction rather than failing deep inside a workflow step.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.providers.filing_provider import (
    CompanyDTO,
    FactDTO,
    FilingDoc,
    FilingMeta,
    SectionDTO,
)

logger = logging.getLogger(__name__)

_QUARTER_RE = re.compile(r"Q([1-4])", re.IGNORECASE)


def _quarter(fiscal_period: Any) -> int | None:
    """'Q2' -> 2. 'FY' (annual) -> None."""
    if not fiscal_period:
        return None
    m = _QUARTER_RE.search(str(fiscal_period))
    return int(m.group(1)) if m else None


def _section_title(text: str) -> str | None:
    """Item text starts with its own heading, e.g.
    'Item 1A. Risk Factors\\n\\n...' -> 'Risk Factors'."""
    first = (text.lstrip().split("\n", 1)[0] or "").strip()
    if not first:
        return None
    m = re.match(r"^\s*(?:part\s+[ivx]+[,\s]+)?item\s+[0-9]+[a-z]?\s*[.:\-–]?\s*(.+)$", first, re.IGNORECASE)
    title = (m.group(1) if m else first).strip()
    return title[:255] or None


def _as_date(v: Any) -> date | None:
    """edgartools returns period_of_report as a str but report_date as a date."""
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        logger.warning("unparseable date from EDGAR: %r", v)
        return None


class EdgarToolsFilingProvider:
    name = "edgartools"

    def __init__(self) -> None:
        identity = (get_settings().edgar_identity or "").strip()
        if not identity:
            raise RuntimeError(
                "EDGAR_IDENTITY is not set — the SEC requires a contact "
                "User-Agent (e.g. 'Name email@domain') for EDGAR access."
            )
        from edgar import set_identity

        set_identity(identity)

    # ── Company identity ──────────────────────────────────────────────────────

    def resolve_company(self, ticker: str) -> CompanyDTO:
        from edgar import Company

        c = Company(ticker)
        cik = getattr(c, "cik", None)
        if cik is None:
            raise RuntimeError(f"EDGAR could not resolve ticker {ticker!r}")
        sic = getattr(c, "sic", None)
        return CompanyDTO(
            ticker=ticker,
            cik=str(int(cik)),
            name=str(getattr(c, "name", "") or ""),
            industry=getattr(c, "industry", None),
            sic=str(sic) if sic is not None else None,
            exchange=None,   # not exposed reliably by edgartools; seeded separately
        )

    # ── Filing metadata ───────────────────────────────────────────────────────

    def latest_filings(self, cik: str, forms: list[str]) -> list[FilingMeta]:
        """Latest ORIGINAL filing per requested form (amendments are skipped for MVP)."""
        from edgar import Company

        c = Company(int(cik))
        out: list[FilingMeta] = []
        for form in forms:
            filings = c.get_filings(form=form)
            if filings is None or len(filings) == 0:
                logger.warning("no %s filings for CIK %s", form, cik)
                continue
            f = filings.latest(1)
            acc = str(f.accession_no)
            period = _as_date(getattr(f, "period_of_report", None)) or _as_date(getattr(f, "report_date", None))
            out.append(
                FilingMeta(
                    accession_number=acc,
                    form_type=str(f.form),
                    filing_date=_as_date(f.filing_date),
                    period_end=period,
                    accepted_at=getattr(f, "acceptance_datetime", None),
                    fiscal_year=period.year if period else None,
                    fiscal_quarter=None,
                    source_url=getattr(f, "filing_url", None),
                    is_amendment=str(f.form).endswith("/A"),
                )
            )
        return out

    # ── XBRL facts ────────────────────────────────────────────────────────────

    def fetch_company_facts(self, cik: str, since: date | None = None) -> list[FactDTO]:
        """All XBRL facts for the company, optionally limited to period_end >= since.

        Returns facts as-reported: no aggregation, no de-duplication across
        restatements (each fact keeps its originating accession).
        """
        from edgar import Company

        facts = Company(int(cik)).get_facts()
        if facts is None:
            return []

        out: list[FactDTO] = []
        for f in facts.get_all_facts():
            period_end = getattr(f, "period_end", None)
            if period_end is None:
                continue
            if since is not None and period_end < since:
                continue
            value = getattr(f, "numeric_value", None)
            if value is None:
                continue   # non-numeric facts carry no analytic value
            concept = str(getattr(f, "concept", "") or "")
            if not concept:
                continue
            dq = getattr(f, "data_quality", None)
            out.append(
                FactDTO(
                    raw_concept=concept,
                    value=float(value),
                    period_end=period_end,
                    period_start=getattr(f, "period_start", None),
                    fiscal_year=getattr(f, "fiscal_year", None),
                    fiscal_quarter=_quarter(getattr(f, "fiscal_period", None)),
                    unit=getattr(f, "unit", None),
                    statement_type=getattr(f, "statement_type", None),
                    form_type=getattr(f, "form_type", None),
                    source_accession=getattr(f, "accession", None),
                    dimensions=getattr(f, "dimensions", None) or {},
                    is_restated=bool(getattr(f, "is_restated", False)),
                    data_quality=str(dq.value) if hasattr(dq, "value") else (str(dq) if dq else None),
                )
            )
        return out

    # ── Text / sections ───────────────────────────────────────────────────────
    # Strategy fixed by the M2a spike (docs/spikes/M2_PARSE_EVAL.md): use the
    # edgartools typed filing object's Item map for BOTH 10-K and 10-Q. Raw-text
    # regex segmentation was measured and rejected (fragments MSFT 10-K into 144
    # marks; cannot separate 10-Q Part I Item 1 from Part II Item 1).

    def _find(self, accession_number: str):
        from edgar import find

        f = find(accession_number)
        if f is None:
            raise RuntimeError(f"EDGAR has no filing for accession {accession_number!r}")
        return f

    def fetch_filing_text(self, accession_number: str) -> FilingDoc:
        f = self._find(accession_number)
        text = f.text() or ""
        if not text.strip():
            raise RuntimeError(f"filing {accession_number} returned empty text")
        return FilingDoc(accession_number=accession_number, doc_type=str(f.form), raw_text=text)

    def fetch_sections(self, accession_number: str) -> list[SectionDTO]:
        """Item sections via the typed object. Raises if no sections are parseable —
        there is deliberately NO blind fixed-window fallback (rule A): a silent
        fallback would make bad parsing permanently invisible."""
        f = self._find(accession_number)
        obj = f.obj()
        codes = list(getattr(obj, "items", None) or [])
        if not codes:
            raise RuntimeError(
                f"filing {accession_number} ({f.form}) exposed no Item sections "
                f"via {type(obj).__name__}"
            )

        sections: list[SectionDTO] = []
        for order, code in enumerate(codes):
            try:
                text = obj[code]
            except Exception:
                text = None
            if not text:
                continue
            text = str(text)
            sections.append(
                SectionDTO(
                    item_code=str(code).strip(),
                    title=_section_title(text),
                    section_order=order,
                    text=text,
                )
            )
        if not sections:
            raise RuntimeError(
                f"filing {accession_number} advertised {len(codes)} items but none yielded text"
            )
        return sections
