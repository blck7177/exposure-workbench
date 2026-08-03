"""Provisioning a portfolio's risk limits — the write path that can now fail.

The bug being repaired: `_copy_risk_limits` gave a new portfolio port_001's
rows, and an empty source produced an empty copy with no exception. That window
is real — scripts/seed_demo_db.py DELETEs port_001's limits before reinserting
them — so a portfolio created inside it came out with no limits and nothing said
so. Now that a run stops when a required limit is missing, "silently gets zero
limits" becomes "every run of this book fails and nothing explains why".

These tests are offline. They run against a fake risk_limits table that enforces
the four rules the real one declares (the partial unique index on the
portfolio-wide default, warning > 0 AND breach > warning, unit = 'fraction',
and no retired default) and refuses to answer a query whose predicates are not
the ones it models — so a filter dropped from the production query fails here
rather than being quietly emulated. What a fake cannot prove is that Postgres
agrees with it; the live test at the bottom of this file is that check, and
tests/test_limit_completeness_live.py is the standing one over real data.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from exposure_workbench.analytics.limit_defaults import DEMO_OVERRIDES, SEED_DEFAULTS
from exposure_workbench.analytics.limits import LIMIT_SPECS, REQUIRED_LIMIT_TYPES
from exposure_workbench.db.models import Portfolio, Position, RiskLimit
from exposure_workbench.services import portfolio_service as svc

DEMO = svc.DEMO_PORTFOLIO_ID


# ── a fake risk_limits table ──────────────────────────────────────────────────

class _ConstraintViolated(Exception):
    """What Postgres would have raised. Named so a test failure says which rule."""


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _inserted_rows(stmt) -> list[dict]:
    """Recover the rows an INSERT carries, from the statement itself.

    Decoded from the compiled parameters (`limit_type_m3`, ...) rather than
    handed to the fake by the test, so the fake stores what the production code
    actually writes and not a second copy of it.
    """
    rows: dict[int, dict] = {}
    for key, value in stmt.compile(dialect=postgresql.dialect()).params.items():
        column, _, index = key.rpartition("_m")
        rows.setdefault(int(index) if index.isdigit() else 0, {})[column or key] = value
    return [rows[i] for i in sorted(rows)]


def _limit(portfolio_id: str, limit_type: str, entity_id=None, warning=0.1,
           breach=0.2, unit="fraction", is_active=True, entity_type=None) -> RiskLimit:
    return RiskLimit(
        id=f"rl_{portfolio_id}_{limit_type}_{entity_id or 'default'}",
        portfolio_id=portfolio_id, limit_type=limit_type,
        entity_type=entity_type or LIMIT_SPECS[limit_type].entity_type,
        entity_id=entity_id, warning_level=warning, breach_level=breach,
        unit=unit, is_active=is_active,
    )


class _FakeDB:
    """Enough of AsyncSession to run the provisioning path, and no more."""

    def __init__(self, rows: list[RiskLimit] | None = None, owned: int = 0,
                 positions: list[Position] | None = None):
        self.rows: list[RiskLimit] = list(rows or [])
        self.owned = owned
        self.positions = list(positions or [])
        self.added: list[object] = []
        self.inserts: list[Insert] = []

    # -- writes ---------------------------------------------------------------

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, RiskLimit):
            self._enforce(dict(
                portfolio_id=obj.portfolio_id, limit_type=obj.limit_type,
                entity_id=obj.entity_id, warning_level=float(obj.warning_level),
                breach_level=float(obj.breach_level), unit=obj.unit,
                is_active=obj.is_active,
            ))
            self.rows.append(obj)

    async def flush(self) -> None:
        pass

    def _enforce(self, row: dict) -> None:
        # Strict `>`, matching ck_risk_limits_levels exactly. A fake that is
        # looser than the constraint it stands in for certifies rows Postgres
        # will refuse — and equal tiers are as dead as inverted ones, because
        # _check_one tests breach first and the warning tier then never fires.
        if not row["warning_level"] > 0 or not row["breach_level"] > row["warning_level"]:
            raise _ConstraintViolated(f"ck_risk_limits_levels: {row}")
        if row["unit"] != "fraction":
            raise _ConstraintViolated(f"ck_risk_limits_unit: {row}")
        if row["entity_id"] is None and not row["is_active"]:
            raise _ConstraintViolated(f"ck_risk_limits_default_active: {row}")

    def _default(self, portfolio_id: str, limit_type: str) -> RiskLimit | None:
        return next((r for r in self.rows
                     if r.portfolio_id == portfolio_id and r.limit_type == limit_type
                     and r.entity_id is None), None)

    # -- execute --------------------------------------------------------------

    async def execute(self, stmt, *_a, **_k):
        if isinstance(stmt, Insert):
            return self._insert(stmt)
        return self._select(stmt)

    def _insert(self, stmt):
        self.inserts.append(stmt)
        sql = _sql(stmt)
        stands_down = ("ON CONFLICT (portfolio_id, limit_type) WHERE entity_id IS NULL "
                       "DO NOTHING") in sql
        for row in _inserted_rows(stmt):
            self._enforce(row)
            if row["entity_id"] is None and self._default(row["portfolio_id"], row["limit_type"]):
                if not stands_down:
                    raise _ConstraintViolated(
                        f"ux_risk_limits_default: second portfolio-wide "
                        f"{row['limit_type']} for {row['portfolio_id']}"
                    )
                continue
            self.rows.append(RiskLimit(**row))
        return _Result([])

    def _select(self, stmt):
        sql, target = _sql(stmt), stmt.column_descriptions[0]
        if "count(*)" in sql:
            return _Result([self.owned])
        if target["entity"] is RiskLimit:
            portfolio_id = next(v for k, v in stmt.compile(dialect=postgresql.dialect())
                                .params.items() if k.startswith("portfolio_id"))
            if target["name"] == "limit_type":
                # The fake answers the completeness question, so it insists the
                # query asked it: a readback that forgot `is_active` would call a
                # retired default present and the caller would never raise.
                assert "entity_id IS NULL" in sql and "is_active IS true" in sql, sql
                return _Result([r.limit_type for r in self.rows
                                if r.portfolio_id == portfolio_id
                                and r.entity_id is None and r.is_active])
            assert "entity_id IS NOT NULL" in sql and "is_active IS true" in sql, sql
            return _Result([r for r in self.rows
                            if r.portfolio_id == portfolio_id
                            and r.entity_id is not None and r.is_active])
        if target["entity"] is Position:
            return _Result([p for p in self.positions] if target["name"] != "as_of_date"
                           else [p.as_of_date for p in self.positions])
        raise AssertionError(f"the fake does not model this query: {sql}")


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _defaults_of(db: _FakeDB, portfolio_id: str) -> dict[str, tuple[float, float]]:
    return {r.limit_type: (float(r.warning_level), float(r.breach_level))
            for r in db.rows if r.portfolio_id == portfolio_id and r.entity_id is None}


def _overrides_of(db: _FakeDB, portfolio_id: str) -> dict[tuple[str, str], tuple[float, float]]:
    return {(r.limit_type, r.entity_id): (float(r.warning_level), float(r.breach_level))
            for r in db.rows if r.portfolio_id == portfolio_id and r.entity_id is not None}


def _entity_types_of(db: _FakeDB, portfolio_id: str) -> dict[tuple[str, str | None], str]:
    return {(r.limit_type, r.entity_id): r.entity_type
            for r in db.rows if r.portfolio_id == portfolio_id}


# ── the rows themselves ───────────────────────────────────────────────────────

def test_the_rows_cover_exactly_the_checks_a_run_evaluates():
    rows = svc._default_limit_rows("port_x")
    assert {r["limit_type"] for r in rows} == set(REQUIRED_LIMIT_TYPES)
    assert len(rows) == len(REQUIRED_LIMIT_TYPES), "one portfolio-wide row per check, no repeats"


def test_the_numbers_are_the_seed_constant_and_not_a_second_copy():
    rows = {r["limit_type"]: (r["warning_level"], r["breach_level"])
            for r in svc._default_limit_rows("port_x")}
    assert rows == dict(SEED_DEFAULTS)


def test_entity_type_comes_from_the_spec_where_the_two_disagree():
    """stress_loss is keyed per scenario and reported against the whole book. A
    hand-typed 'scenario' here would put a value on the row no alert can carry."""
    rows = {r["limit_type"]: r["entity_type"] for r in svc._default_limit_rows("port_x")}
    assert rows == {lt: spec.entity_type for lt, spec in LIMIT_SPECS.items()}
    assert rows["stress_loss"] == "portfolio"


def test_every_row_satisfies_the_four_rules_the_table_declares():
    for row in svc._default_limit_rows("port_x"):
        assert row["entity_id"] is None, "a default applies to the whole book"
        assert row["warning_level"] > 0 and row["breach_level"] >= row["warning_level"]
        assert row["unit"] == "fraction"
        assert row["is_active"] is True, "a retired default is a run that cannot start"


# ── ensure_default_limits ─────────────────────────────────────────────────────

async def test_it_writes_the_full_required_set_for_an_empty_portfolio():
    db = _FakeDB()
    await svc.ensure_default_limits(db, "port_new")
    assert set(_defaults_of(db, "port_new")) == set(REQUIRED_LIMIT_TYPES)
    assert _defaults_of(db, "port_new") == dict(SEED_DEFAULTS)


async def test_the_insert_stands_down_on_the_partial_index_rather_than_upserting():
    """The idempotence guarantee is in the SQL, not in the caller: DO NOTHING
    arbitrated on ux_risk_limits_default. DO UPDATE would walk every threshold a
    desk has tuned back to the seed value on the next call, and the table's plain
    UNIQUE is no arbiter here because entity_id is NULL on all eight rows."""
    db = _FakeDB()
    await svc.ensure_default_limits(db, "port_new")
    sql = _sql(db.inserts[0])
    assert "ON CONFLICT (portfolio_id, limit_type) WHERE entity_id IS NULL DO NOTHING" in sql
    assert "DO UPDATE" not in sql


async def test_running_it_again_changes_nothing():
    db = _FakeDB()
    await svc.ensure_default_limits(db, "port_new")
    await svc.ensure_default_limits(db, "port_new")
    assert len(db.rows) == len(REQUIRED_LIMIT_TYPES), "the second run must add no row"
    assert _defaults_of(db, "port_new") == dict(SEED_DEFAULTS)


async def test_a_threshold_the_desk_has_tuned_is_left_where_the_desk_put_it():
    db = _FakeDB([_limit("port_x", "var_95", warning=0.008, breach=0.010)])
    await svc.ensure_default_limits(db, "port_x")
    assert _defaults_of(db, "port_x")["var_95"] == (0.008, 0.010), (
        "provisioning must fill gaps, never restore a number to the seed value"
    )
    assert set(_defaults_of(db, "port_x")) == set(REQUIRED_LIMIT_TYPES)


async def test_it_only_touches_the_portfolio_it_was_given():
    db = _FakeDB([_limit(DEMO, lt) for lt in REQUIRED_LIMIT_TYPES])
    await svc.ensure_default_limits(db, "port_new")
    assert len(_defaults_of(db, DEMO)) == len(REQUIRED_LIMIT_TYPES)
    assert _defaults_of(db, DEMO)["var_95"] == (0.1, 0.2), "the demo's rows are untouched"


async def test_it_raises_when_a_required_default_is_still_missing_afterwards():
    """A retired default from before ck_risk_limits_default_active: the insert
    stands down on the index, the engine will not read an inactive row, so the
    book is incomplete and the creation must not be allowed to look successful."""
    db = _FakeDB()
    db.rows.append(_limit("port_x", "var_95", entity_id=None, is_active=False))
    with pytest.raises(svc.LimitProvisioningFailed) as e:
        await svc.ensure_default_limits(db, "port_x")
    assert "var_95" in str(e.value) and "port_x" in str(e.value)
    assert e.value.portfolio_id == "port_x"


async def test_the_failure_names_every_missing_check_not_just_the_first():
    db = _FakeDB()
    for lt in ("var_95", "stress_loss"):
        db.rows.append(_limit("port_x", lt, entity_id=None, is_active=False))
    with pytest.raises(svc.LimitProvisioningFailed) as e:
        await svc.ensure_default_limits(db, "port_x")
    assert "var_95" in str(e.value) and "stress_loss" in str(e.value)


# ── create_portfolio ──────────────────────────────────────────────────────────

@pytest.fixture
def no_charge(monkeypatch):
    """The quota charge is proven at its own charge point (test_charge_points_live);
    here it would only drag a second live dependency into an offline test."""
    charges = []

    async def _charge(_db, user_id, kind):
        charges.append((user_id, kind))

    monkeypatch.setattr(svc.usage_service, "charge", _charge)
    return charges


def _demo_book() -> list[RiskLimit]:
    """port_001 as the seed leaves it, derived from the constants the seed reads.

    Written out as literals this fixture stops being port_001 the moment
    DEMO_OVERRIDES gains an entry or retunes one — the seed would write the new
    set, the clone would copy it, and these tests would go on asserting the old
    one in green.
    """
    return (
        [_limit(DEMO, lt, warning=w, breach=b) for lt, (w, b) in SEED_DEFAULTS.items()]
        + [_limit(DEMO, lt, entity_id=eid, warning=w, breach=b)
           for (lt, eid), (w, b) in DEMO_OVERRIDES.items()]
    )


async def test_create_portfolio_gives_the_book_exactly_the_required_defaults(no_charge):
    db = _FakeDB(_demo_book())
    p = await svc.create_portfolio(db, owner_id="user_1", name="Mine")
    assert _defaults_of(db, p.id) == dict(SEED_DEFAULTS)
    assert no_charge == [("user_1", "portfolio_create")]


async def test_create_portfolio_inherits_no_override_from_the_demo_book(no_charge):
    """A COST/SBUX/TGT book has no business holding an LLY threshold: it is a row
    the user can read as policy and no holding of theirs can ever match."""
    db = _FakeDB(_demo_book())
    p = await svc.create_portfolio(db, owner_id="user_1", name="Mine")
    assert _overrides_of(db, p.id) == {}


async def test_create_portfolio_survives_the_demo_book_having_no_limits_at_all(no_charge):
    """The seed script's DELETE-then-INSERT window, which used to produce a
    portfolio with zero limits and no error."""
    db = _FakeDB()
    p = await svc.create_portfolio(db, owner_id="user_1", name="Mine")
    assert set(_defaults_of(db, p.id)) == set(REQUIRED_LIMIT_TYPES)


# ── clone_demo ────────────────────────────────────────────────────────────────

async def test_clone_demo_gets_the_defaults_plus_the_demo_overrides(no_charge):
    db = _FakeDB(_demo_book())
    p = await svc.clone_demo(db, owner_id="user_1")
    assert _defaults_of(db, p.id) == dict(SEED_DEFAULTS)
    assert _overrides_of(db, p.id) == dict(DEMO_OVERRIDES)
    assert (len([r for r in db.rows if r.portfolio_id == p.id])
            == len(SEED_DEFAULTS) + len(DEMO_OVERRIDES))


async def test_clone_demo_does_not_propagate_a_retired_override(no_charge):
    """is_active=false is how a user retires an override — app_rls holds no
    DELETE. Copying the flag would resurrect the tombstone on every later clone."""
    book = _demo_book()
    book.append(_limit(DEMO, "issuer_concentration", entity_id="NVDA", is_active=False))
    db = _FakeDB(book)
    p = await svc.clone_demo(db, owner_id="user_1")
    assert ("issuer_concentration", "NVDA") not in _overrides_of(db, p.id)
    assert all(r.is_active for r in db.rows if r.portfolio_id == p.id)


async def test_clone_demo_takes_its_defaults_from_the_constant_not_from_port_001(no_charge):
    """Mid-reseed the demo has no rows; the clone still comes out runnable."""
    db = _FakeDB()
    p = await svc.clone_demo(db, owner_id="user_1")
    assert _defaults_of(db, p.id) == dict(SEED_DEFAULTS)
    assert _overrides_of(db, p.id) == {}


async def test_clone_demo_refuses_an_override_no_check_can_read(no_charge):
    """`stress_loss_tech` sat in the seed for a year, shown as policy in force
    while nothing ever looked it up. Copying such a row onto every clone would
    multiply it, so the clone stops and names the row instead.

    Note the shape: this is a PER-ENTITY stress_loss_tech row. The one actually
    in the live seed is portfolio-wide (entity_id NULL), and that one never
    reaches the guard at all — `entity_id IS NOT NULL` drops it from the SELECT
    first. This test pins the guard, not the fate of that row."""
    book = _demo_book()
    book.append(RiskLimit(id="rl_ghost", portfolio_id=DEMO, limit_type="stress_loss_tech",
                          entity_type="sector", entity_id="Technology",
                          warning_level=0.1, breach_level=0.2, unit="fraction", is_active=True))
    db = _FakeDB(book)
    with pytest.raises(svc.LimitProvisioningFailed) as e:
        await svc.clone_demo(db, owner_id="user_1")
    assert "stress_loss_tech" in str(e.value)
    assert "no check of that name exists" in str(e.value), (
        "which of the two rules the row broke — the fix differs, so the message must"
    )


async def test_clone_demo_refuses_a_per_entity_row_for_a_portfolio_wide_check(no_charge):
    """The other half of the same rule, and the one membership alone misses.

    var_95 IS a check the engine runs, so `limit_type in LIMIT_SPECS` waves this
    row through — but check_limits looks var_95 up with no entity, so a var_95/LLY
    row on a clone is stored, served by GET /portfolios/{id}/limits as policy in
    force, and never once compared to anything. That is the stress_loss_tech
    shape exactly. limit_defaults asserts scope == 'entity' over DEMO_OVERRIDES;
    this path reads the table, not the constant, and SQL can write such a row."""
    book = _demo_book()
    book.append(_limit(DEMO, "var_95", entity_id="LLY", warning=0.12, breach=0.18))
    db = _FakeDB(book)
    with pytest.raises(svc.LimitProvisioningFailed) as e:
        await svc.clone_demo(db, owner_id="user_1")
    assert "var_95" in str(e.value) and "LLY" in str(e.value)
    assert "never per entity" in str(e.value)
    assert "no check of that name exists" not in str(e.value), (
        "var_95 is a real check; saying otherwise sends the reader after the wrong fix"
    )


async def test_clone_demo_takes_entity_type_from_the_spec_and_not_from_the_row(no_charge):
    """Nothing constrains the entity_type COLUMN — no FK, no CHECK — and the rows
    that reach this path were written by SQL (the seed, a migration, psql by
    hand). LIMIT_SPECS is authoritative for the same reason the alert reads it
    there: stress_loss is keyed per scenario yet reported against the whole book,
    so a row saying 'scenario' where the spec says 'portfolio' is the normal case
    and not a corruption.

    _demo_book() cannot prove this on its own — _limit() defaults entity_type FROM
    the spec, so in that fixture the two can never disagree, and copying the
    row's column instead passes every other test in this file. Hence rows here
    whose column deliberately contradicts the spec."""
    book = _demo_book()
    book.append(_limit(DEMO, "stress_loss", entity_id="rates_shock_2008",
                       entity_type="scenario", warning=0.06, breach=0.08))
    book.append(_limit(DEMO, "issuer_concentration", entity_id="MRK",
                       entity_type="ticker", warning=0.12, breach=0.18))
    db = _FakeDB(book)
    p = await svc.clone_demo(db, owner_id="user_1")

    copied = _entity_types_of(db, p.id)
    assert copied[("stress_loss", "rates_shock_2008")] == "portfolio", (
        "the spec's value; the row said 'scenario', which no alert can carry"
    )
    assert copied[("issuer_concentration", "MRK")] == "issuer", "the row said 'ticker'"
    assert all(copied[k] == LIMIT_SPECS[k[0]].entity_type for k in copied), (
        "every row on the clone, default and override alike, is typed by the spec"
    )
    # the source rows are read, never rewritten
    assert _entity_types_of(db, DEMO)[("stress_loss", "rates_shock_2008")] == "scenario"


# There is no sibling test for is_active, and that is not an omission. Unlike
# entity_type, the literal `is_active=True` and `lim.is_active` cannot disagree:
# the SELECT filters `is_active IS true`, so every source row is already active,
# and a fixture that disagreed would be a row the query could not have returned.
# What the pair actually rests on is that filter — and _select above refuses any
# RiskLimit query whose predicates it does not model, so dropping `is_active IS
# true` from the production query fails every clone test in this file.


# ── against a real database ───────────────────────────────────────────────────
#
# The fake above models the partial unique index; only Postgres can confirm that
# the ON CONFLICT clause actually names it and that all four constraints admit
# these rows. Runs as the owner role and cleans up after itself.

@pytest.mark.live
async def test_provisioning_against_postgres_is_idempotent_for_real():
    from dotenv import load_dotenv
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    load_dotenv(".env", override=True)
    url = os.getenv("DATABASE_URL_LOCAL",
                    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    portfolio_id = "port_provisioning_test"
    try:
        async with mk() as db, db.begin():
            # is_active=false so a failed teardown leaves nothing that
            # snapshot_all or the completeness live test would pick up as a real
            # book. Owner role, so no tenant context is needed to write it.
            await db.execute(
                text("INSERT INTO portfolios (id, name, currency, owner_id, is_active, is_public) "
                     "VALUES (:i, 'provisioning test', 'USD', 'user_provisioning_test', "
                     "false, false)"),
                {"i": portfolio_id},
            )
            await svc.ensure_default_limits(db, portfolio_id)

        async with mk() as db, db.begin():
            # a threshold the desk tuned after creation
            await db.execute(
                text("UPDATE risk_limits SET warning_level = 0.008, breach_level = 0.010 "
                     "WHERE portfolio_id = :i AND limit_type = 'var_95' AND entity_id IS NULL"),
                {"i": portfolio_id},
            )
            await svc.ensure_default_limits(db, portfolio_id)

        async with mk() as db:
            rows = dict((await db.execute(
                text("SELECT limit_type, warning_level FROM risk_limits "
                     "WHERE portfolio_id = :i AND entity_id IS NULL"),
                {"i": portfolio_id},
            )).all())
        assert set(rows) == set(REQUIRED_LIMIT_TYPES)
        assert float(rows["var_95"]) == 0.008, "the second run must not restore the seed value"
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM portfolios WHERE id = :i"), {"i": portfolio_id})
        await engine.dispose()
