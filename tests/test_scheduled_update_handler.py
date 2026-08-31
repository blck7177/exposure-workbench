"""V13 §9-④A — the scheduled door: sync first, resolve the date second, mint
third (offline: no DB, no network).

The ORDER is the entire reason this handler exists. The run's as_of_date is
stamped at mint time and honoured exactly downstream, and the workflow's own
sync_prices step only refreshes the RUN's window [as_of - lookback, as_of] — it
can never move as_of forward. A handler that resolved the date before syncing
would pin every 06:30 report to whatever session the store last saw, and the
fresh bars fetched minutes later could not unpin it.

The second thing pinned here is V13-S1 at this door: `scheduled` is a fact about
which door the run came through, minted where it is true. The enqueue payload
carries a copy for the audit trail, but the handler must neither read it nor be
able to say anything else.
"""

from __future__ import annotations

import inspect
import re
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from apps.worker import worker
from apps.worker.handlers import market_data_sync, scheduled_update
from exposure_workbench.db.models import Task
from exposure_workbench.services import (
    exposure_run_service,
    market_data_service,
    portfolio_service,
    task_service,
)
from exposure_workbench.services.market_data_ingestion_service import MarketDataUnavailable

SESSION = date(2026, 8, 28)


class FakeDb:
    """Answers the one statement the handler issues itself: the portfolio's
    distinct held tickers."""

    def __init__(self, tickers):
        self._tickers = tickers

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "FROM positions" in sql, f"unexpected statement: {sql}"
        return SimpleNamespace(all=lambda: [(t,) for t in self._tickers])


class Recorder:
    """One call log shared by every stubbed collaborator, so ordering is a fact
    of the log rather than five separate booleans."""

    def __init__(self):
        self.calls: list[tuple] = []
        # A real (detached) Task instance: the handler mirrors the API door and
        # calls flag_modified on it, which needs an instrumented object.
        self.task = Task(id="task_child", type="exposure_update",
                         status="pending", payload={})
        self.run = SimpleNamespace(id="run_child")

    def install(self, monkeypatch):
        async def ingest_market(db, tickers, start, end, provider, commit=True):
            self.calls.append(("ingest_market", tuple(tickers)))
            return {t: 1 for t in tickers}

        async def ingest_factor(db, tickers, start, end, provider):
            self.calls.append(("ingest_factor", tuple(tickers)))
            return {t: 1 for t in tickers}

        async def latest_session_date(db):
            self.calls.append(("latest_session_date",))
            return SESSION

        async def get_portfolio(db, portfolio_id):
            self.calls.append(("get_portfolio", portfolio_id))
            return SimpleNamespace(id=portfolio_id, owner_id="user_owner")

        async def create_task(db, task_type, payload=None, owner_user_id=None):
            self.calls.append(("create_task", task_type, dict(payload), owner_user_id))
            self.task.payload = dict(payload)
            return self.task

        async def create_run(db, portfolio_id, as_of_date, task_id=None,
                             triggered_by="unset"):
            self.calls.append(("create_run", portfolio_id, as_of_date,
                               task_id, triggered_by))
            return self.run

        monkeypatch.setattr(scheduled_update, "ingest_market_prices", ingest_market)
        monkeypatch.setattr(scheduled_update, "ingest_factor_prices", ingest_factor)
        monkeypatch.setattr(market_data_service, "latest_session_date", latest_session_date)
        monkeypatch.setattr(portfolio_service, "get_portfolio", get_portfolio)
        monkeypatch.setattr(task_service, "create_task", create_task)
        monkeypatch.setattr(exposure_run_service, "create_run", create_run)
        return self

    def named(self, name):
        return [c for c in self.calls if c[0] == name]

    def index(self, name):
        return next(i for i, c in enumerate(self.calls) if c[0] == name)


def task_row(payload=None):
    base = {"schedule_id": "sched_1", "portfolio_id": "port_1",
            "owner_user_id": "user_owner", "triggered_by": "scheduled"}
    return SimpleNamespace(id="task_parent", payload={**base, **(payload or {})})


async def run_handler(monkeypatch, tickers=("AAPL", "MSFT"), payload=None,
                      factor_panel=("MTUM", "VLUE")):
    rec = Recorder().install(monkeypatch)
    # Offline the real configs path does not exist and the panel reads empty, so
    # every test pins the panel it hands in; the identity assertion in
    # test_sync_covers... is what ties the callable to the real source of truth.
    monkeypatch.setattr(scheduled_update, "_factor_tickers",
                        lambda: list(factor_panel))
    await scheduled_update.handle(FakeDb(list(tickers)), task_row(payload))
    return rec


# ── the sequencing that is the point ──────────────────────────────────────────

async def test_sync_happens_before_the_date_which_happens_before_the_mint(monkeypatch):
    rec = await run_handler(monkeypatch)
    assert rec.index("ingest_market") < rec.index("latest_session_date")
    assert rec.index("ingest_factor") < rec.index("latest_session_date")
    assert rec.index("latest_session_date") < rec.index("create_task")
    assert rec.index("create_task") < rec.index("create_run")


async def test_the_minted_date_is_the_post_sync_session(monkeypatch):
    rec = await run_handler(monkeypatch)
    (_, _, payload, _) = rec.named("create_task")[0]
    assert payload["as_of_date"] == SESSION.isoformat()
    (_, _, as_of, _, _) = rec.named("create_run")[0]
    assert as_of == SESSION


async def test_sync_covers_holdings_benchmark_and_the_factor_panel(monkeypatch):
    # The factor set must be THE SAME callable market_data_sync reads from
    # configs/factor_config.yaml — identity, not a copied list, so the two doors
    # cannot drift. (Offline the real config path does not exist, so the panel
    # itself is stubbed below to prove it is passed through verbatim.)
    assert scheduled_update._factor_tickers is market_data_sync._factor_tickers
    rec = await run_handler(monkeypatch, tickers=("AAPL", "MSFT"))
    (_, market) = rec.named("ingest_market")[0]
    assert set(market) == {"AAPL", "MSFT", market_data_sync._BENCHMARK}
    (_, factors) = rec.named("ingest_factor")[0]
    assert list(factors) == ["MTUM", "VLUE"]


async def test_an_empty_factor_panel_skips_the_factor_sync(monkeypatch):
    rec = await run_handler(monkeypatch, factor_panel=())
    assert rec.named("ingest_factor") == []
    assert rec.named("create_run")  # the run is still minted


# ── V13-S1 at this door ───────────────────────────────────────────────────────

async def test_triggered_by_is_minted_here_not_read_from_the_payload(monkeypatch):
    rec = await run_handler(monkeypatch, payload={"triggered_by": "v99_acceptance"})
    (_, _, payload, _) = rec.named("create_task")[0]
    assert payload["triggered_by"] == "scheduled"
    (_, _, _, _, triggered_by) = rec.named("create_run")[0]
    assert triggered_by == "scheduled"


async def test_owner_is_read_from_the_portfolio_not_the_payload(monkeypatch):
    rec = await run_handler(monkeypatch, payload={"owner_user_id": "user_impostor"})
    (_, _, _, owner_user_id) = rec.named("create_task")[0]
    assert owner_user_id == "user_owner"


def test_the_handler_cannot_say_anything_but_scheduled():
    """Source-level guard, same shape as the reap-SQL pins: the door's label is
    a constant, so the word for the OTHER door must not appear at all and the
    payload copy must be unreadable from here."""
    src = inspect.getsource(scheduled_update)
    assert "manual" not in src
    assert not re.search(r"""payload(?:\.get\(|\[)\s*["']triggered_by""", src)


# ── wiring and honesty ────────────────────────────────────────────────────────

async def test_run_id_is_written_back_into_the_child_task_payload(monkeypatch):
    rec = await run_handler(monkeypatch)
    assert rec.task.payload["run_id"] == "run_child"


async def test_sync_failure_fails_the_task_before_anything_is_minted(monkeypatch):
    rec = Recorder().install(monkeypatch)

    async def unavailable(db, tickers, start, end, provider, commit=True):
        raise MarketDataUnavailable(tickers[0])

    monkeypatch.setattr(scheduled_update, "ingest_market_prices", unavailable)
    with pytest.raises(MarketDataUnavailable):
        await scheduled_update.handle(FakeDb(["AAPL"]), task_row())
    assert rec.named("create_task") == [] and rec.named("create_run") == []


async def test_no_session_at_all_is_a_loud_failure_not_a_quiet_skip(monkeypatch):
    rec = Recorder().install(monkeypatch)

    async def none_at_all(db):
        return None

    monkeypatch.setattr(market_data_service, "latest_session_date", none_at_all)
    with pytest.raises(ValueError):
        await scheduled_update.handle(FakeDb(["AAPL"]), task_row())
    assert rec.named("create_task") == []


def test_worker_dispatch_resolves_scheduled_update_to_this_handler():
    assert worker._get_handler("scheduled_update") is scheduled_update.handle
