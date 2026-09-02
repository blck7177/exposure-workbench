"""Portfolio service — portfolios, positions, and the portfolio-level snapshot.

The issuer tools are all ticker-scoped; a question like "what fundamental risk is
my portfolio most exposed to" has no ticker to start from. `snapshot_all` is the
missing orthogonal read: it surfaces the desk's portfolio(s), their latest
exposure metrics, largest sector/issuer weights and active alerts — the entry
point the agent discovers holdings from, so it never asks the user for an
internal id. Every portfolio number is produced by an exposure run, so the
snapshot carries that run_id; run_ resolves through the evidence resolver and
passes the citation gate, so a portfolio-level claim is cited like an issuer one.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics.limit_defaults import SEED_DEFAULTS
from exposure_workbench.analytics.limits import LIMIT_SPECS, REQUIRED_LIMIT_TYPES
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import IssuerExposure, MarketPrice, Portfolio, Position, RiskLimit
from exposure_workbench.services import exposure_run_service, security_master_service, usage_service
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

_TOP_SECTORS = 8
_TOP_ISSUERS = 10
# The full-book read is bounded too — see positions_with_weights. 50 rows is
# comfortably inside the 6000-character summariser and above every real book on
# this system; the CSV importer's own ceiling is 200.
_POSITION_ROW_LIMIT = 50

DEMO_PORTFOLIO_ID = "port_001"
# tickers that are funds even when no position metadata names them (U1 covered set)
_ETF_HINT = {"SPY", "TLT", "HYG", "QQQ", "IWM", "AGG", "LQD", "VOO", "IVV"}


async def get_portfolio(db: AsyncSession, portfolio_id: str) -> Portfolio | None:
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id)
    )
    return result.scalar_one_or_none()


async def list_portfolios(db: AsyncSession, active_only: bool = True) -> list[Portfolio]:
    q = select(Portfolio).order_by(Portfolio.name)
    if active_only:
        q = q.where(Portfolio.is_active == True)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_positions(
    db: AsyncSession,
    portfolio_id: str,
    as_of_date: date | None = None,
) -> list[Position]:
    q = (
        select(Position)
        .where(Position.portfolio_id == portfolio_id)
        .order_by(Position.market_value.desc())
    )
    if as_of_date:
        q = q.where(Position.as_of_date == as_of_date)
    else:
        # Latest available date
        latest_q = (
            select(Position.as_of_date)
            .where(Position.portfolio_id == portfolio_id)
            .order_by(Position.as_of_date.desc())
            .limit(1)
        )
        latest_result = await db.execute(latest_q)
        latest_date = latest_result.scalar_one_or_none()
        if latest_date:
            q = q.where(Position.as_of_date == latest_date)

    result = await db.execute(q)
    return list(result.scalars().all())


async def get_positions_latest(
    db: AsyncSession,
    portfolio_id: str,
) -> list[Position]:
    """Get positions for the most recent available date."""
    return await get_positions(db, portfolio_id, as_of_date=None)


async def positions_for_run(db: AsyncSession, portfolio_id: str, as_of_date: date) -> list[Position]:
    """The holdings a run reports on, resolved the one way everything agrees on.

    get_positions filters as_of_date by EXACT equality, while uploads date a
    snapshot by max(price_date) and a run's as_of defaults to today — so the
    two normally differ and the latest snapshot is the branch that actually
    fires. One definition (V19, moved out of the exposure workflow): the run
    computes over these rows, and the evidence card for the run lists these
    rows, so a copy that skipped the second branch would show a reader no
    holdings for a run that valued ten.
    """
    positions = await get_positions(db, portfolio_id, as_of_date)
    if not positions:
        positions = await get_positions_latest(db, portfolio_id)
    return positions


async def get_risk_limits(
    db: AsyncSession,
    portfolio_id: str,
    active_only: bool = True,
) -> list[RiskLimit]:
    q = select(RiskLimit).where(RiskLimit.portfolio_id == portfolio_id)
    if active_only:
        q = q.where(RiskLimit.is_active == True)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── portfolio snapshot (agent entry point) ────────────────────────────────────

def _f(v) -> float | None:
    return float(v) if v is not None else None


def _metrics(m) -> dict | None:
    if m is None:
        return None
    return {
        "market_value": _f(m.portfolio_market_value),
        "daily_pnl": _f(m.daily_pnl),
        "daily_return": _f(m.daily_return),
        "gross_exposure_pct": _f(m.gross_exposure_pct),
        "net_exposure_pct": _f(m.net_exposure_pct),
        "rolling_vol_30d": _f(m.rolling_vol_30d),
        "var_95_1d": _f(m.var_95_1d),
        "max_drawdown": _f(m.max_drawdown),
    }


async def _snapshot_one(db: AsyncSession, p: Portfolio) -> dict:
    base = {
        "portfolio_id": p.id, "name": p.name, "benchmark": p.benchmark,
        "currency": p.currency, "manager": p.manager,
        # semantic, not security: is_own only lets the agent prefer the user's own
        # book over the shared public demo. Visibility itself is decided by RLS.
        "is_own": p.owner_id is not None and p.owner_id == current_user_id(),
    }
    latest = await exposure_run_service.get_latest_completed_run(db, p.id)
    if latest is None:
        # No completed run yet — honest empty, not fabricated zeros.
        return {**base, "run_id": None, "as_of_date": None,
                "metrics": None, "top_sectors": [], "top_issuers": [], "alerts": []}

    run = await exposure_run_service.get_run(db, latest.id)  # eager-loaded relations
    top_sectors = sorted(run.sector_exposures, key=lambda s: (s.weight or 0), reverse=True)[:_TOP_SECTORS]
    top_issuers = sorted(run.issuer_exposures, key=lambda i: (i.weight or 0), reverse=True)[:_TOP_ISSUERS]
    return {
        **base,
        "run_id": run.id,
        "as_of_date": run.as_of_date.isoformat(),
        "metrics": _metrics(run.metrics),
        "top_sectors": [
            {"sector": s.sector, "weight": _f(s.weight), "market_value": _f(s.market_value)}
            for s in top_sectors
        ],
        "top_issuers": [
            {"ticker": i.ticker, "sector": i.sector, "weight": _f(i.weight),
             "market_value": _f(i.market_value), "daily_return": _f(i.daily_return)}
            for i in top_issuers
        ],
        # alert_type (not "type") so the evidence walker harvests a clean alert ref
        # off the id, not one typed by the alert category.
        "alerts": [
            {"id": a.id, "alert_type": a.alert_type, "severity": a.severity,
             "entity_id": a.entity_id, "message": a.message, "utilization": _f(a.utilization)}
            for a in run.risk_alerts
        ],
    }


async def snapshot_all(db: AsyncSession) -> list[dict]:
    """Every active portfolio the desk manages, latest exposure state first.

    Returns a list (data-driven: one portfolio today, many later, same shape) —
    no "default portfolio" rule.
    """
    portfolios = await list_portfolios(db, active_only=True)
    return [await _snapshot_one(db, p) for p in portfolios]


# ── user portfolios: create / upload / clone (V2-B) ───────────────────────────

class UploadError(Exception):
    """Atomic-upload rejection. Carries per-row problems; nothing is written."""
    def __init__(self, problems: list[dict]):
        super().__init__(f"{len(problems)} problem(s)")
        self.problems = problems


async def list_visible(db: AsyncSession, owner_id: str | None) -> list[Portfolio]:
    """Portfolios a caller may see: public (demo) plus their own.

    semantic, not security: Postgres RLS is what isolates tenants. This filter
    only shapes what 'my portfolios' means for the list view."""
    q = select(Portfolio).where(Portfolio.is_active.is_(True))
    if owner_id:
        q = q.where((Portfolio.owner_id == owner_id) | (Portfolio.is_public.is_(True)))
    else:
        q = q.where(Portfolio.is_public.is_(True))
    return list((await db.execute(q.order_by(Portfolio.created_at))).scalars().all())


async def _covered_tickers(db: AsyncSession) -> set[str]:
    return set((await db.execute(select(MarketPrice.ticker).distinct())).scalars().all())


async def _snapshot_date(db: AsyncSession) -> date | None:
    return (await db.execute(select(func.max(MarketPrice.price_date)))).scalar_one_or_none()


async def _common_snapshot_date(db: AsyncSession, tickers: list[str]) -> date | None:
    """The latest date on which EVERY uploaded ticker has a price. Using a global
    max instead would date a whole upload to the freshest ticker's day and price
    the others at a stale close — this pins one real, coherent snapshot (matches
    the seed's own HAVING count(distinct)=N logic)."""
    n = len(set(tickers))
    return (await db.execute(
        select(MarketPrice.price_date)
        .where(MarketPrice.ticker.in_(tickers))
        .group_by(MarketPrice.price_date)
        .having(func.count(func.distinct(MarketPrice.ticker)) == n)
        .order_by(MarketPrice.price_date.desc())
        .limit(1)
    )).scalar_one_or_none()


async def _latest_prices(db: AsyncSession, tickers: list[str], as_of: date) -> dict[str, float]:
    rows = (await db.execute(
        select(MarketPrice.ticker, MarketPrice.close)
        .where(MarketPrice.ticker.in_(tickers), MarketPrice.price_date <= as_of)
        .order_by(MarketPrice.ticker, MarketPrice.price_date.desc())
        .distinct(MarketPrice.ticker)
    )).all()
    return {t: float(c) for t, c in rows}


async def _ticker_metadata(db: AsyncSession, tickers: list[str]) -> dict[str, dict]:
    """sector / asset_class / region from the most recent existing position for
    each ticker (companies.sector is unreliable). U1's covered set are all demo
    holdings, so this is populated; U2 will enrich unknowns from the provider."""
    rows = (await db.execute(
        select(Position.ticker, Position.sector, Position.asset_class, Position.region)
        .where(Position.ticker.in_(tickers))
        .order_by(Position.ticker, Position.as_of_date.desc())
        .distinct(Position.ticker)
    )).all()
    return {t: {"sector": s, "asset_class": ac, "region": r} for t, s, ac, r in rows}


async def _backfill_prices(db: AsyncSession, tickers: list[str]) -> None:
    """Pull ~1y of daily prices for new tickers into THIS transaction (atomic with
    the upload). Unpriceable tickers are left absent -> caught as no_price_data."""
    from datetime import timedelta

    from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
    from exposure_workbench.services import market_data_ingestion_service as mdi

    provider = YFinanceMarketDataProvider()
    end = date.today()
    start = end - timedelta(days=365)
    for t in tickers:
        try:
            await mdi.ingest_market_prices(db, [t], start, end, provider, commit=False)
        except mdi.MarketDataUnavailable:
            pass  # no data -> step 4 rejects it as no_price_data (upload stays atomic)
        except Exception as e:  # noqa: BLE001 — a provider/network hiccup (rate limit,
            # timeout) must not 500 the upload; leave the ticker unpriced so step 4
            # reports a clean no_price_data. A genuine DB error still surfaces later.
            logger.warning("price backfill failed for %s: %s", t, e)


async def _enrich_new_meta(db: AsyncSession, tickers: list[str], meta: dict) -> None:
    """Fill asset_class/sector for tickers with no existing-position metadata, from
    security_master (is_etf) + best-effort yfinance sector (None -> Unclassified)."""
    provider = None
    for t in tickers:
        m = meta.get(t) or {}
        if m.get("asset_class"):
            continue  # already described by an existing position (sector incl. None for ETFs)
        sm_row = await security_master_service.get(db, t)
        is_etf = bool(sm_row and sm_row.is_etf)
        if is_etf:
            meta[t] = {"asset_class": "etf", "sector": None, "region": "US"}
            continue
        from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
        provider = provider or YFinanceMarketDataProvider()
        # yfinance .info is a blocking network call — offload so it can't stall the loop
        try:
            sector = await asyncio.to_thread(provider.fetch_sector, t)
        except Exception:  # noqa: BLE001 — sector is best-effort
            sector = None
        meta[t] = {"asset_class": "equity", "sector": sector or "Unclassified", "region": "US"}


# ── risk limits a new portfolio starts with ───────────────────────────────────

class LimitProvisioningFailed(Exception):
    """A portfolio does not carry the limit rows every run of it will need.

    Raised inside the caller's transaction so the portfolio row goes back with
    it: a book that cannot be valued is never handed to a user in the first
    place. Nothing catches this. Its whole purpose is that provisioning stops
    being able to half-succeed quietly.

    `portfolio_id` is the book whose ROWS AN OPERATOR HAS TO GO FIX, which is
    not always the book being created. A clone that trips over a bad override in
    port_001 names port_001 here, because that is the row that will trip the
    next clone too; the transient clone id is about to be rolled back and would
    be a different value on every attempt, so anything grouping on this field
    would see a stream of one-off ids instead of one recurring broken book. The
    message carries both.
    """

    def __init__(self, portfolio_id: str, problem: str):
        super().__init__(f"{portfolio_id}: {problem}")
        self.portfolio_id = portfolio_id


def _default_limit_rows(portfolio_id: str) -> list[dict]:
    """One portfolio-wide row per check a run evaluates — eight of them today.

    The numbers come from the SEED_DEFAULTS constant, not from port_001. A copy
    is only ever as present as its source, and this source disappears on
    purpose: scripts/seed_demo_db.py DELETEs port_001's limits before
    reinserting them, so a portfolio created inside that window was handed an
    empty set and told nobody. They come from a Python module rather than
    configs/risk_limits.yaml because the API container has no /app/configs at
    all — that missing file is what left check_limits reading its own literals.

    entity_type is taken from LIMIT_SPECS and never typed here: stress_loss is
    keyed per scenario yet reported against the whole book, and that
    disagreement is settled in exactly one place.
    """
    return [
        {"id": new_id("rl_"), "portfolio_id": portfolio_id, "limit_type": limit_type,
         "entity_type": LIMIT_SPECS[limit_type].entity_type, "entity_id": None,
         "warning_level": warning, "breach_level": breach,
         "unit": "fraction", "is_active": True}
        for limit_type, (warning, breach) in SEED_DEFAULTS.items()
    ]


async def _active_default_limit_types(db: AsyncSession, portfolio_id: str) -> set[str]:
    """Which checks this book currently has a live portfolio-wide row for.

    The same definition the run uses: entity_id IS NULL and is_active. A retired
    default cannot legally exist (ck_risk_limits_default_active), but filtering
    on the flag anyway means a row left over from before that constraint is
    reported as missing — which, to the engine, is exactly what it is — instead
    of counting as present and then never being read.
    """
    return set((await db.execute(
        select(RiskLimit.limit_type).where(
            RiskLimit.portfolio_id == portfolio_id,
            RiskLimit.entity_id.is_(None),
            RiskLimit.is_active.is_(True),
        )
    )).scalars().all())


async def ensure_default_limits(db: AsyncSession, portfolio_id: str) -> None:
    """Give this portfolio every portfolio-wide limit a run of it will look up.

    Idempotent, and idempotent in the direction that matters: ON CONFLICT DO
    NOTHING, so a threshold the desk has already tuned stays where the desk put
    it. An upsert here would walk every edited number back to the seed value on
    the next call, which is a policy change nobody asked for and nobody would
    see.

    It reads the table back and raises, because writing is the step that can
    fail invisibly. The copy-from-port_001 this replaces could not fail at all:
    an empty source produced an empty copy and returned successfully. Once the
    engine is switched over to these rows — check_limits still reads every
    threshold from its own cfg() closure today and still ignores the db_limits
    it is handed — that same silence surfaces days later as "every run of this
    book fails", with nothing pointing back at the creation that caused it.
    Raising at creation time is what keeps that book from existing.
    """
    await db.execute(
        pg_insert(RiskLimit)
        .values(_default_limit_rows(portfolio_id))
        # Arbitrated on the partial index, not on the table's UNIQUE: entity_id
        # is NULL on every row here, and under NULLS DISTINCT that UNIQUE would
        # wave the insert through and leave the book holding two contradictory
        # defaults for one check.
        .on_conflict_do_nothing(
            index_elements=["portfolio_id", "limit_type"],
            index_where=text("entity_id IS NULL"),
        )
    )
    await db.flush()

    missing = REQUIRED_LIMIT_TYPES - await _active_default_limit_types(db, portfolio_id)
    if missing:
        raise LimitProvisioningFailed(
            portfolio_id,
            "no active portfolio-wide limit for " + ", ".join(sorted(missing))
            + " after provisioning — a run of this portfolio would have no "
              "threshold to check those against",
        )


async def _copy_demo_overrides(db: AsyncSession, dst_id: str) -> None:
    """Give a clone of the demo book the demo book's per-entity thresholds.

    A clone, and only a clone: it holds the demo's positions, so "Financials
    0.20/0.30" and "LLY 0.12/0.18" are about names it actually owns. This is why
    create_portfolio copies nothing — an uploaded COST/SBUX/TGT book has no
    business inheriting an LLY threshold, and three of the live user books share
    not one entity with the rows they were given, because yfinance calls a
    sector "Consumer Cyclical" where the seed said "Consumer_Discretionary".
    Those rows could never match the thing they were meant to constrain.

    entity_id IS NOT NULL keeps this away from the eight defaults, which
    ensure_default_limits has already written from the constant. It also means
    the legacy portfolio-wide `stress_loss_tech` row never reaches the guard
    below: entity_id is NULL on it, so the WHERE clause drops it one step
    earlier and silently. The guard is about per-entity rows only.

    is_active is a filter and not a copied column: with no DELETE grant,
    is_active=false is the only way a user retires an override, and propagating
    that tombstone would hand every later clone a row whose only purpose is to
    be ignored.
    """
    overrides = (await db.execute(select(RiskLimit).where(
        RiskLimit.portfolio_id == DEMO_PORTFOLIO_ID,
        RiskLimit.entity_id.isnot(None),
        RiskLimit.is_active.is_(True),
    ))).scalars().all()

    for lim in overrides:
        spec = LIMIT_SPECS.get(lim.limit_type)
        if spec is None or spec.scope != "entity":
            # Two ways a per-entity row is policy nothing will ever read, and the
            # message says which because the two need different fixes.
            #
            # No such check: `stress_loss_tech`, shown to users as in force for a
            # year while nothing looked it up. The row has to go or be renamed.
            #
            # A real check, but a portfolio-scoped one: check_limits looks var_95
            # up with no entity, so var_95/LLY is stored, served by GET
            # /portfolios/{id}/limits as policy in force, and never compared to
            # anything. Same shape, different repair — the threshold belongs on
            # the portfolio-wide row.
            #
            # limit_defaults asserts both rules over DEMO_OVERRIDES, but that
            # constant is not what this reads: the rows come from the table, and
            # nothing stops SQL putting one there. So the copy path checks both
            # rather than inheriting the constant's guarantee.
            raise LimitProvisioningFailed(
                DEMO_PORTFOLIO_ID,
                f"clone into {dst_id} stopped: this book has a "
                f"{lim.limit_type!r} override for "
                f"{lim.entity_id!r} and "
                + ("no check of that name exists to read it" if spec is None else
                   f"{lim.limit_type} is checked for the whole book, never per "
                   "entity, so no run would ever look that row up"),
            )
        db.add(RiskLimit(
            id=new_id("rl_"), portfolio_id=dst_id, limit_type=lim.limit_type,
            # From the spec, not from the source row, for the same reason the
            # alert takes it from there: the two can disagree.
            entity_type=spec.entity_type, entity_id=lim.entity_id,
            warning_level=lim.warning_level, breach_level=lim.breach_level,
            # The source's own unit rather than a literal 'fraction'. Under
            # ck_risk_limits_unit the two cannot differ, so this is defence in
            # depth for a volume older than that constraint: on such a database
            # a 'percent' row copied as 'fraction' would become a hundredfold
            # looser limit that reads as deliberate, where copying the unit
            # keeps the row refusable by the constraint once it lands.
            unit=lim.unit, is_active=True,
        ))
    await db.flush()


class TooManyPortfolios(Exception):
    def __init__(self, limit: int):
        super().__init__(f"a user may own at most {limit} portfolios")
        self.limit = limit


# A ceiling, and since V2-H also a daily pool. The two are orthogonal and both
# stay: the ceiling bounds how many rows one account can ever hold, the pool
# bounds how fast it can get there. Nobody should earn ten more portfolios every
# morning, and nobody should be able to spend their whole allowance in one
# scripted loop either. Each creation also writes one portfolio-wide risk-limit
# row per check — eight, the length of SEED_DEFAULTS — and a clone copies the
# demo's positions and its per-entity overrides on top.
#
# A demo clone is 12 rows (8 SEED_DEFAULTS + 4 DEMO_OVERRIDES) — and that is a
# statement about a database whose port_001 has already been reseeded from
# limit_defaults, not about one that has not. Until scripts/seed_demo_db.py has
# rerun, port_001 holds what the retired data/demo/risk_limits_seed.csv put
# there: 13 rows, 8 of them per-entity and active (four — Technology, NVDA,
# AAPL, MSFT — only restating the default, which is why the constant drops
# them), so a clone taken against that book writes 16, not 12.
MAX_PORTFOLIOS_PER_USER = 20


async def create_portfolio(db: AsyncSession, owner_id: str, name: str) -> Portfolio:
    """New empty portfolio owned by the user, carrying the eight portfolio-wide
    limits every run looks up — and nothing else.

    It inherits no per-entity threshold from the demo book. Those name the demo's
    sectors and issuers, and a book with none of those holdings gets rows that
    can never match; see _copy_demo_overrides for who does get them and why."""
    # semantic, not security: RLS already scopes this count to the caller; the
    # explicit owner filter is what makes it mean "mine" rather than "visible".
    owned = (await db.execute(
        select(func.count()).select_from(Portfolio).where(Portfolio.owner_id == owner_id)
    )).scalar_one()
    if owned >= MAX_PORTFOLIOS_PER_USER:
        raise TooManyPortfolios(MAX_PORTFOLIOS_PER_USER)

    # Charged here rather than in the routes so that both surfaces — POST
    # /portfolios and POST /portfolios/clone-demo — are covered by one call.
    # clone_demo goes through this function exactly once and produces exactly
    # one Portfolio row, so there is no double charge. Shares the caller's
    # transaction: the work is a handful of local INSERTs, so a later failure
    # rolling the charge back with them is the correct outcome.
    await usage_service.charge(db, owner_id, "portfolio_create")

    p = Portfolio(
        id=new_id("port_"), name=(name or "").strip() or "My Portfolio",
        currency="USD", benchmark="SPY", owner_id=owner_id, is_active=True, is_public=False,
    )
    db.add(p)
    await db.flush()
    await ensure_default_limits(db, p.id)
    return p


async def upload_positions(
    db: AsyncSession, portfolio_id: str, rows, as_of: date | None = None,
) -> dict:
    """Atomic holdings upload. Validates every ticker is in the covered set and
    priceable BEFORE any write; any failure raises UploadError (zero writes).
    Priced at the snapshot close; re-upload on the same snapshot date upserts."""
    tickers = [r.ticker for r in rows]
    if not tickers:
        raise UploadError([{"row": 0, "ticker": "", "reason": "no rows"}])

    # 1) universe membership (U2): every ticker must be in the active universe
    problems = [{"ticker": t, "reason": "ticker_not_in_universe"}
                for t in tickers if not await security_master_service.is_in_universe(db, t)]
    if problems:
        raise UploadError(problems)

    # 2) backfill prices for tickers we don't already have (yfinance, this txn)
    have = await _covered_tickers(db)
    to_backfill = [t for t in tickers if t not in have]
    if to_backfill:
        await _backfill_prices(db, to_backfill)

    # 3) snapshot date = latest date on which ALL uploaded tickers are priced
    #    (a coherent common date, not a global max that would stale-price others)
    as_of = as_of or await _common_snapshot_date(db, tickers)
    if as_of is None:
        # no date where every ticker has a price -> at least one is unpriceable
        priced_any = await _covered_tickers(db)
        raise UploadError([{"ticker": t, "reason": "no_price_data"}
                           for t in tickers if t not in priced_any] or
                          [{"ticker": "*", "reason": "no_common_price_date"}])

    # 4) price every ticker; any still unpriced -> reject the whole upload (atomic)
    prices = await _latest_prices(db, tickers, as_of)
    missing = [t for t in tickers if t not in prices]
    if missing:
        raise UploadError([{"ticker": t, "reason": "no_price_data"} for t in missing])

    # 5) metadata: existing positions first, then universe + yfinance for new tickers
    meta = await _ticker_metadata(db, tickers)
    await _enrich_new_meta(db, tickers, meta)

    for r in rows:
        m = meta.get(r.ticker, {})
        close = prices[r.ticker]
        asset_class = m.get("asset_class") or "equity"
        stmt = pg_insert(Position).values(
            id=new_id("pos_"), portfolio_id=portfolio_id, as_of_date=as_of, ticker=r.ticker,
            asset_class=asset_class, sector=m.get("sector"), region=m.get("region") or "US",
            currency="USD", quantity=r.quantity, cost_basis=r.cost_basis, price=close,
            market_value=round(r.quantity * close, 2),
        ).on_conflict_do_update(
            index_elements=["portfolio_id", "as_of_date", "ticker"],
            set_={"quantity": r.quantity, "cost_basis": r.cost_basis, "price": close,
                  "market_value": round(r.quantity * close, 2), "asset_class": asset_class,
                  "sector": m.get("sector")},
        )
        await db.execute(stmt)
    await db.flush()
    return {"portfolio_id": portfolio_id, "as_of_date": as_of.isoformat(), "positions": len(rows)}


async def clone_demo(db: AsyncSession, owner_id: str, name: str = "My Portfolio (demo copy)") -> Portfolio:
    """Create a user portfolio pre-filled with the demo's latest holdings — the
    one-click way to get something runnable without uploading a CSV.

    The demo's per-entity limits come with the holdings, because here they are
    about the same names. The eight portfolio-wide defaults arrive from
    create_portfolio, not from port_001, so a clone taken while the demo is
    mid-reseed still gets a complete set."""
    p = await create_portfolio(db, owner_id, name)
    await _copy_demo_overrides(db, p.id)
    demo_positions = await get_positions_latest(db, DEMO_PORTFOLIO_ID)
    for pos in demo_positions:
        db.add(Position(
            id=new_id("pos_"), portfolio_id=p.id, as_of_date=pos.as_of_date, ticker=pos.ticker,
            asset_class=pos.asset_class, sector=pos.sector, region=pos.region, currency=pos.currency,
            quantity=pos.quantity, cost_basis=pos.cost_basis, price=pos.price, market_value=pos.market_value,
        ))
    await db.flush()
    return p


# ── full holdings (V3-C3) ─────────────────────────────────────────────────────

async def positions_with_weights(db: AsyncSession, portfolio_id: str) -> dict | None:
    """Every holding, with the run whose numbers these are.

    A SIBLING of the snapshot rather than a widening of it: the snapshot is a
    framing device capped at the largest few names, and making it unbounded would
    change what every portfolio question costs.

    Market values and weights come from the latest completed run's
    issuer_exposures, NEVER from a position row. That is not a preference — a
    number the agent quotes has to have a citable id behind it, and only the run
    has one. Reading a price off the position would hand the model figures that
    A1's numeric check must then refuse, turning a memory feature into a
    generator of false rejections.

    The two dates are reported separately because they really are different: on
    the live demo book the newest position snapshot is 2026-07-23 while the
    newest completed run is 2026-07-27. Collapsing them into one "as of" would be
    a small lie that gets repeated in every answer built on this.

    With no completed run the quantities are still real and are returned as
    themselves, with market_value and weight ABSENT rather than zero — a holding
    worth nothing and a holding not yet valued are different facts, and this
    codebase has been bitten by conflating them before.
    """
    p = await get_portfolio(db, portfolio_id)
    if p is None:
        return None

    # The established convention for "which snapshot is the book": newest.
    positions = await get_positions_latest(db, portfolio_id)

    latest = await exposure_run_service.get_latest_completed_run(db, portfolio_id)
    priced: dict[str, IssuerExposure] = {}
    if latest is not None:
        rows = (await db.execute(
            select(IssuerExposure).where(IssuerExposure.run_id == latest.id)
        )).scalars().all()
        priced = {r.ticker: r for r in rows}

    # A hard row cap, and the truncation is REPORTED. The CSV importer accepts
    # 200 rows and a tool result is summarised at 6000 characters, so a large
    # book would be cut mid-JSON by the summariser — the model would read a
    # broken object, or worse, a plausible one that stops at "AAP". A count the
    # model can see is a fact it can act on ("showing 50 of 137"); a silent cut
    # is a wrong answer it cannot know is wrong.
    total = len(positions)
    positions = positions[:_POSITION_ROW_LIMIT]

    holdings = []
    for pos in positions:
        # pos_id is what makes the quantity answerable: it is the only number on
        # this row that comes from the position itself, and without an id beside
        # it the model can read the holding and cannot support it.
        row = {"pos_id": pos.id, "ticker": pos.ticker, "quantity": _f(pos.quantity),
               "sector": pos.sector, "asset_class": pos.asset_class}
        exposure = priced.get(pos.ticker)
        if exposure is not None:
            row["market_value"] = _f(exposure.market_value)
            row["weight"] = _f(exposure.weight)
        holdings.append(row)

    unpriced = [h["ticker"] for h in holdings if "market_value" not in h]
    return {
        "portfolio_id": p.id, "name": p.name,
        "run_id": latest.id if latest is not None else None,
        "valued_as_of": latest.as_of_date if latest is not None else None,
        "positions_as_of": positions[0].as_of_date if positions else None,
        "holdings": holdings,
        "count": len(holdings),
        "total_holdings": total,
        **({"truncated": True} if total > len(holdings) else {}),
        **({"unpriced": unpriced} if unpriced else {}),
        **({} if latest is not None else
           {"note": "no completed run: quantities are real, market values and weights are "
                    "not available and are omitted rather than reported as zero"}),
    }
