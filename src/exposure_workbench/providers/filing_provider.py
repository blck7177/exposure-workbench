"""FilingProvider boundary — SEC company identity, filing metadata, XBRL facts, text.

DTOs only: edgartools objects are consumed inside the implementation and never
leak upward. Only filing_ingestion_service may import a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class CompanyDTO:
    ticker: str
    cik: str
    name: str
    industry: str | None = None
    sic: str | None = None
    exchange: str | None = None


@dataclass(frozen=True)
class FilingMeta:
    accession_number: str
    form_type: str
    filing_date: date
    period_end: date | None = None
    accepted_at: datetime | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    source_url: str | None = None
    is_amendment: bool = False


@dataclass(frozen=True)
class FilingDoc:
    accession_number: str
    doc_type: str
    raw_text: str


@dataclass(frozen=True)
class SectionDTO:
    """One SEC Item section of a filing (e.g. 'Item 1A' Risk Factors)."""

    item_code: str | None
    title: str | None
    section_order: int
    text: str


@dataclass(frozen=True)
class FactDTO:
    """One XBRL fact, as reported by a specific filing."""

    raw_concept: str            # e.g. 'us-gaap:Revenues'
    value: float
    period_end: date
    period_start: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    unit: str | None = None
    statement_type: str | None = None
    form_type: str | None = None
    source_accession: str | None = None
    dimensions: dict[str, Any] = field(default_factory=dict)
    is_restated: bool = False
    data_quality: str | None = None


class FilingProvider(Protocol):
    name: str

    def resolve_company(self, ticker: str) -> CompanyDTO: ...

    def latest_filings(self, cik: str, forms: list[str]) -> list[FilingMeta]: ...

    def fetch_company_facts(self, cik: str, since: date | None = None) -> list[FactDTO]: ...

    def fetch_filing_text(self, accession_number: str) -> FilingDoc: ...

    def fetch_sections(self, accession_number: str) -> list[SectionDTO]: ...
