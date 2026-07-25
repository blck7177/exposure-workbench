"""Security-master universe provider (V2-D).

Fetches the investable US-equity/ETF universe from official free sources and
returns plain SecurityRowDTOs — the httpx/parse details never leak upward.

Sources (IMPLEMENTATION_PLAN_V2 §0.5):
  - NASDAQ Trader nasdaqlisted.txt + otherlisted.txt  (tickers, names, ETF flag)
  - SEC company_tickers.json                           (ticker -> CIK enrichment)

Fail loud: any source unreachable or unparseable raises — the caller writes
nothing on a partial fetch (no half-populated universe).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from exposure_workbench.app_state.settings import get_settings

logger = logging.getLogger(__name__)

_NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# CQS exchange codes used by otherlisted.txt
_EXCHANGE = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


class UniverseFetchError(Exception):
    pass


@dataclass(frozen=True)
class SecurityRowDTO:
    ticker: str          # exchange-listing form (dot preserved, e.g. BRK.A)
    name: str
    exchange: str
    is_etf: bool
    cik: str | None


def _get(client: httpx.Client, url: str, headers: dict | None = None) -> str:
    try:
        r = client.get(url, headers=headers or {}, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001 — any failure means "can't build the universe"
        raise UniverseFetchError(f"fetch failed for {url}: {e}") from e


def _parse_pipe(text: str, ticker_col: str) -> list[dict]:
    """Parse a NASDAQ Trader pipe file by header, dropping the 'File Creation
    Time' trailer and Test-Issue rows."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise UniverseFetchError("empty listing file")
    header = lines[0].split("|")
    idx = {name: i for i, name in enumerate(header)}
    for req in (ticker_col, "Security Name", "Test Issue", "ETF"):
        if req not in idx:
            raise UniverseFetchError(f"missing column {req!r} in {header}")
    out: list[dict] = []
    for ln in lines[1:]:
        if ln.startswith("File Creation Time"):
            continue
        parts = ln.split("|")
        if len(parts) < len(header):
            continue
        if parts[idx["Test Issue"]].strip() == "Y":
            continue
        ticker = parts[idx[ticker_col]].strip()
        if not ticker:
            continue
        out.append({
            "ticker": ticker,
            "name": parts[idx["Security Name"]].strip(),
            "is_etf": parts[idx["ETF"]].strip() == "Y",
            "exchange_code": parts[idx["Exchange"]].strip() if "Exchange" in idx else None,
        })
    if not out:
        raise UniverseFetchError("no usable rows parsed from listing file")
    return out


def _cik_map(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise UniverseFetchError(f"SEC tickers JSON parse failed: {e}") from e
    if not isinstance(data, dict):
        raise UniverseFetchError(f"SEC tickers JSON has unexpected shape: {type(data).__name__}")
    out: dict[str, str] = {}
    for v in data.values():
        if not isinstance(v, dict):
            continue
        tk = str(v.get("ticker", "")).upper()
        cik = v.get("cik_str")
        if tk and cik is not None:
            out[tk] = str(cik).zfill(10)
    return out


def fetch_universe() -> list[SecurityRowDTO]:
    """The full listed US universe, deduped by ticker, enriched with CIK. Raises
    UniverseFetchError on any source failure (all-or-nothing)."""
    settings = get_settings()
    ua = settings.edgar_identity or "exposure-workbench research"
    with httpx.Client() as client:
        nasdaq_txt = _get(client, _NASDAQ_LISTED)
        other_txt = _get(client, _OTHER_LISTED)
        sec_txt = _get(client, _SEC_TICKERS, headers={"User-Agent": ua})

    rows = _parse_pipe(nasdaq_txt, "Symbol")
    rows += _parse_pipe(other_txt, "ACT Symbol")
    ciks = _cik_map(sec_txt)

    by_ticker: dict[str, SecurityRowDTO] = {}
    for r in rows:
        tk = r["ticker"]
        exch = "NASDAQ" if r["exchange_code"] is None else _EXCHANGE.get(r["exchange_code"], "Other")
        if tk in by_ticker:
            # first occurrence wins (nasdaqlisted parsed first); OR the ETF flag in
            if r["is_etf"] and not by_ticker[tk].is_etf:
                prev = by_ticker[tk]
                by_ticker[tk] = SecurityRowDTO(tk, prev.name, prev.exchange, True, prev.cik)
            continue
        # SEC uses the dash form (BRK-A) where listings use the dot form (BRK.A);
        # try both so dual-class tickers still get a CIK.
        cik = ciks.get(tk.upper()) or ciks.get(tk.replace(".", "-").upper())
        by_ticker[tk] = SecurityRowDTO(
            ticker=tk, name=r["name"], exchange=exch, is_etf=r["is_etf"], cik=cik,
        )
    logger.info("universe: %d securities (%d with CIK)", len(by_ticker),
                sum(1 for s in by_ticker.values() if s.cik))
    return list(by_ticker.values())
