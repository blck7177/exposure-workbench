"""One threshold, one place — asserted structurally (offline).

The bug this whole change repairs was not an arithmetic mistake. It was three
copies of the same eight numbers (a YAML, a seed CSV, and 16 literals inside
check_limits' cfg() closure) with no mechanism keeping them equal, plus a
fourth set — the user's own risk_limits rows — that the engine never read.

These tests do not check that the numbers are right. They check that there is
only one of each, and that the copies which have to remain cannot drift apart.

Tense, because it matters in this commit: the engine has NOT been switched over
yet. analytics/limits.py still reads every threshold out of the cfg() closure it
is handed and still ignores db_limits, so the number in force today comes from
configs/risk_limits.yaml — or, in the API container, which has no /app/configs,
from the 16 literals inside cfg(). What this commit builds is the schema, the
seed and the constraints that the switch will land on, and what is asserted below
is what has to be true before it: the engine cannot import the seed numbers, the
three DDL mirrors agree AND enforce the rules they were written for, and the seed
builds its rows out of the module rather than out of a file.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from sqlalchemy import CheckConstraint

from exposure_workbench.analytics import limits
from exposure_workbench.analytics.limit_defaults import DEMO_OVERRIDES, SEED_DEFAULTS
from exposure_workbench.analytics.limits import LIMIT_SPECS, REQUIRED_LIMIT_TYPES
from exposure_workbench.db.models import RiskLimit

ROOT = Path(__file__).resolve().parents[1]
INIT_SQL = ROOT / "infra" / "init.sql"
V2_SQL = ROOT / "infra" / "migrations" / "v2_multiuser.sql"
SEED_SCRIPT = ROOT / "scripts" / "seed_demo_db.py"


@lru_cache(maxsize=1)
def _seed_module():
    """scripts/seed_demo_db.py imported as a module, so a test can call into it.

    It is a script, not a package member, hence the path load. Its import runs
    `load_dotenv(ROOT/".env")`, which would otherwise push the developer's real
    DATABASE_URL and API keys into os.environ for every test that runs after
    this one — so the environment is put back exactly as it was. Nothing at its
    import time opens a socket or a database.
    """
    spec = importlib.util.spec_from_file_location("seed_demo_db_under_test", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    before = dict(os.environ)
    try:
        spec.loader.exec_module(module)
    finally:
        os.environ.clear()
        os.environ.update(before)
    return module


def test_the_seed_covers_exactly_the_checks_that_exist():
    # Both directions. A check with no seeded row fails every run of a new
    # portfolio; a seeded row for a check that does not exist is how
    # `stress_loss_tech` was served to users as policy in force while nothing
    # ever looked it up.
    assert set(SEED_DEFAULTS) == set(REQUIRED_LIMIT_TYPES)


def test_the_engine_cannot_import_the_seed_numbers():
    """The import direction IS the guarantee — there is nothing else.

    If analytics/limits.py could reach SEED_DEFAULTS, a plausible-looking edit
    would restore exactly the fallback this change deletes, and every test here
    would stay green because the numbers agree.

    Read as an import graph, not as text: the module's own docstring names
    limit_defaults in order to forbid it, and a substring check would call that
    sentence a violation while missing `importlib.import_module` entirely.
    """
    tree = ast.parse(Path(limits.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Call):
            # importlib.import_module("...") / __import__("...")
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in {"import_module", "__import__"}:
                imported.update(a.value for a in node.args
                                if isinstance(a, ast.Constant) and isinstance(a.value, str))

    offenders = sorted(m for m in imported if "limit_defaults" in m)
    assert not offenders, f"the engine must not be able to read a seed number: {offenders}"


def test_every_override_names_a_check_that_is_looked_up_per_entity():
    for limit_type, entity_id in DEMO_OVERRIDES:
        assert limit_type in LIMIT_SPECS, limit_type
        assert LIMIT_SPECS[limit_type].scope == "entity", limit_type
        assert entity_id, f"an override needs an entity: {limit_type}"


def test_a_portfolio_scoped_label_takes_no_entity_and_an_entity_one_requires_it():
    # The alert text is built by formatting the label, so a placeholder in the
    # wrong spec would either print a stray "{entity}" or drop the name.
    for limit_type, spec in LIMIT_SPECS.items():
        has_placeholder = "{entity}" in spec.label
        assert has_placeholder == (spec.scope == "entity"), limit_type


# ─── The schema and the migration agree with SEED_DEFAULTS ────────────────────

def _values_block(alias: str) -> str:
    """The body of the CROSS JOIN (VALUES …) list closed by `alias`.

    Anchored on the alias because the V2-H4 section holds two such lists — the
    backfill and statement (7)'s completeness guard — and matching the wrong one
    would compare the eight names against themselves and pass no matter what the
    backfill said.

    `(?!CROSS JOIN)` is what makes the anchor actually select: a plain `.*?`
    starting at the first list runs straight through it to the second list's
    alias and returns both bodies concatenated, which is how this helper first
    reported twenty-four names in an eight-name list.
    """
    match = re.search(
        r"CROSS JOIN \(VALUES((?:(?!CROSS JOIN).)*?)\)\s*AS " + alias,
        V2_SQL.read_text(), re.S,
    )
    assert match, f"the V2-H4 VALUES list aliased `{alias}` is gone or was reshaped"
    return match.group(1)


def _migration_defaults() -> list[tuple[str, str, float, float]]:
    """The backfill's VALUES block, read out of the SQL rather than restated."""
    rows = re.findall(
        r"\(\s*'([\w]+)'\s*,\s*'([\w]+)'\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
        _values_block(r"d\(limit_type, entity_type, warning, breach\)"),
    )
    return [(lt, et, float(w), float(b)) for lt, et, w, b in rows]


def test_the_migration_backfills_exactly_the_seed_numbers():
    """The VALUES block is a frozen snapshot of SEED_DEFAULTS, and a snapshot
    nothing compares is just a fourth copy of the numbers — which is the failure
    this whole change exists to end. Asserted both directions: a name only in the
    SQL seeds a limit type the engine cannot evaluate, and a name only in
    SEED_DEFAULTS leaves every existing portfolio short a required default, which
    surfaces as a run that will not start.

    If a threshold genuinely changes, this test is supposed to fail. The fix is a
    NEW dated section in the migration file, never an edit to this one — existing
    databases already ran it, so editing it in place changes nothing for them
    while quietly rewriting the record of what they were given.
    """
    rows = _migration_defaults()

    # The count is asserted separately from the mapping because a dict cannot see
    # a duplicate limit_type: two var_95 rows collapse to one key and compare
    # equal. That is not a hypothetical tidiness point — the INSERT is ON CONFLICT
    # DO NOTHING, which keeps the FIRST of the two, so a duplicate pair whose
    # first entry is wrong gives every portfolio in production a threshold nobody
    # chose, with the intended row silently discarded.
    assert len(rows) == len(SEED_DEFAULTS), (
        "the backfill's VALUES block names a limit_type twice — ON CONFLICT DO "
        f"NOTHING would keep whichever came first: {[lt for lt, *_ in rows]}"
    )

    from_sql = {lt: (w, b) for lt, _et, w, b in rows}
    assert from_sql == dict(SEED_DEFAULTS)


def test_the_migration_uses_the_entity_type_the_engine_reports():
    """entity_type lands on the alert, and LIMIT_SPECS is authoritative over it
    precisely because the two can disagree — stress_loss is keyed per scenario
    and reported against the whole book. A hand-typed 'scenario' here would put a
    value on the row that no code path can produce."""
    for limit_type, entity_type, _w, _b in _migration_defaults():
        assert limit_type in LIMIT_SPECS, limit_type
        assert entity_type == LIMIT_SPECS[limit_type].entity_type, limit_type


def _guard_limit_types(which: str) -> list[str]:
    """The limit_type names listed by one of statement (7)'s two guards."""
    if which == "completeness":
        block = _values_block(r"t\(limit_type\)")
    else:
        match = re.search(r"WHERE limit_type NOT IN \((.*?)\)", V2_SQL.read_text(), re.S)
        assert match, "the unknown-limit_type guard's IN list is gone or was reshaped"
        block = match.group(1)
    return re.findall(r"'([\w]+)'", block)


def test_the_migrations_own_verification_guards_list_every_required_check():
    """Statement (7) decides whether the deploy proceeds, off two hand-typed name
    lists. A name missing from the first means a portfolio short that default
    passes the migration and then fails every run; a name missing from the second
    means a row like `stress_loss_tech` — served to users as policy in force,
    looked up by nothing — is waved through by the check written to catch it.

    Names only. The guards carry no thresholds, deliberately: they ask whether a
    row exists, never whether its number is right.
    """
    for which in ("completeness", "unknown"):
        names = _guard_limit_types(which)
        assert len(names) == len(set(names)), f"duplicate name in the {which} guard: {names}"
        assert set(names) == set(SEED_DEFAULTS) == set(REQUIRED_LIMIT_TYPES), which


def _v2h4_section() -> str:
    """Everything from the V2-H4 header down, so a search cannot wander into an
    earlier section's statements — v2_multiuser.sql already holds two other
    DO blocks and several other INSERTs."""
    text = V2_SQL.read_text()
    start = text.find("V2-H4 (2026-08-02)")
    assert start != -1, "the V2-H4 section header is gone or was reworded"
    return text[start:]


def test_each_verification_guard_is_a_block_that_can_actually_fail_the_deploy():
    """The name-list test above reads the two guards' contents and nothing around
    them, which leaves the MECHANISM unpinned — and the mechanism is the whole
    point of statement (7). Both of these keep their name lists intact and stop
    working:

      * the DO block replaced by the bare SELECT it used to be. psql exits 0
        whether a SELECT returns eight rows or none, so ON_ERROR_STOP cannot see
        it and docs/PRODUCTION.md proceeds to the next file regardless. The
        operator's only warning is a table in scrollback.
      * `IF missing_defaults IS NOT NULL THEN` given one more conjunct. The guard
        still reads correctly, still names every check, and never fires.

    So the shape is asserted: a DO block that collects offenders into a variable
    and RAISEs when that variable came back non-NULL. Whitespace is collapsed
    first — the assertions are about structure, not formatting.
    """
    blocks = re.findall(r"DO \$\$(.*?)END \$\$;", _v2h4_section(), re.S)
    for which, marker in (("completeness", "AS t(limit_type)"),
                          ("unknown", "limit_type NOT IN (")):
        found = [b for b in blocks if marker in b]
        assert len(found) == 1, (
            f"the {which} guard is not inside exactly one DO $$ … END $$; block "
            f"(found {len(found)}). A bare SELECT cannot fail a deploy: psql exits "
            "0 either way, so ON_ERROR_STOP never sees it and the operator has to "
            "notice a table scrolling past. RAISE EXCEPTION is what makes it stop."
        )
        body = " ".join(found[0].split())

        target = re.search(r"\bINTO (\w+)\b", body)
        assert target, f"the {which} guard does not collect its offenders INTO a variable: {body}"
        fires = f"IF {target.group(1)} IS NOT NULL THEN RAISE EXCEPTION"
        assert fires in body, (
            f"the {which} guard no longer raises on exactly `{target.group(1)} IS "
            f"NOT NULL`. Expected `{fires}`, which is the only condition that means "
            "'offenders were found'. An extra conjunct — or a statement wedged in "
            "front of the RAISE — is how a guard keeps its name list, keeps its "
            f"RAISE, and stops firing: {body}"
        )


def test_the_backfill_can_only_add_a_missing_default_never_move_one():
    """Statement (6) promises in its own comment that it can never move a number
    already in the table. ON CONFLICT … DO NOTHING is that promise's entire
    mechanism, and nothing else in this file re-states it.

    Turned into DO UPDATE it becomes a statement that overwrites a threshold an
    operator deliberately set — and since docs/PRODUCTION.md re-runs this file on
    every deploy, it would do so on every deploy, quietly resetting the desk's
    policy to a snapshot frozen on 2026-08-02. The conflict target is pinned too:
    it has to be the partial index statement (2) creates, because
    (portfolio_id, limit_type, entity_id) is NULLS DISTINCT and would let the
    backfill insert a second portfolio-wide default instead of standing down.
    """
    section = _v2h4_section()
    assert section.count("INSERT INTO risk_limits") == 1, (
        "V2-H4 writes risk_limits in more than one place; each write needs its own "
        "conflict action argued, and this test only checks the backfill"
    )
    start = section.find("INSERT INTO risk_limits")
    end = section.find(";", start)
    assert end != -1, "the backfill INSERT is not terminated"
    statement = " ".join(section[start:end + 1].split())

    assert "DO UPDATE" not in statement.upper(), (
        "the backfill would overwrite thresholds that already exist, on every "
        f"deploy: {statement}"
    )
    assert statement.endswith(
        "ON CONFLICT (portfolio_id, limit_type) WHERE entity_id IS NULL DO NOTHING;"
    ), statement


# ─── init.sql, the migration and the ORM declare the SAME guards ──────────────

_CK_IN_INIT = r"CONSTRAINT\s+(ck_risk_limits_\w+)\s+CHECK\s*\("

# `ADD` is the load-bearing word here. Each constraint's name appears twice in the
# migration — once on its `DROP CONSTRAINT IF EXISTS` line, once on its ADD — so
# searching for the bare name is satisfied by the DROP alone. Deleting the ADD
# would then still read as "declared", and because docs/PRODUCTION.md re-runs this
# file on every deploy, the next deploy would REMOVE that guard from an
# already-migrated live database with the suite green.
_CK_ADDED_IN_MIGRATION = (
    r"ALTER TABLE risk_limits\s+ADD\s+CONSTRAINT\s+(ck_risk_limits_\w+)\s+CHECK\s*\("
)

_EXPECTED_CHECKS = {
    "ck_risk_limits_levels",
    "ck_risk_limits_unit",
    "ck_risk_limits_default_active",
}


def _predicate_from(sql: str, open_paren: int) -> str:
    """The CHECK body that starts at `open_paren`, whitespace collapsed.

    Parenthesis counting rather than a lazy regex: no predicate here nests
    parens today, and a regex that assumes that keeps passing right up until
    someone writes CHECK ((a OR b) AND c), at which point it compares half a
    predicate against half a predicate and calls them equal.
    """
    depth = 0
    for i in range(open_paren, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return " ".join(sql[open_paren + 1:i].split())
    raise AssertionError(f"unbalanced parentheses in a CHECK at offset {open_paren}")


def _check_predicates(sql: str, pattern: str) -> dict[str, str]:
    return {m.group(1): _predicate_from(sql, m.end() - 1)
            for m in re.finditer(pattern, sql, re.I)}


def _orm_check_predicates() -> dict[str, str]:
    return {
        c.name: " ".join(str(c.sqltext).split())
        for c in RiskLimit.__table__.constraints
        if isinstance(c, CheckConstraint) and (c.name or "").startswith("ck_risk_limits_")
    }


def _the_three_mirrors() -> dict[str, dict[str, str]]:
    """Every place the constraint predicates are written down, by file."""
    return {
        "infra/init.sql": _check_predicates(INIT_SQL.read_text(), _CK_IN_INIT),
        "infra/migrations/v2_multiuser.sql":
            _check_predicates(V2_SQL.read_text(), _CK_ADDED_IN_MIGRATION),
        "src/exposure_workbench/db/models.py": _orm_check_predicates(),
    }


def _default_index_definition(sql: str) -> str:
    m = re.search(
        r"CREATE UNIQUE INDEX (?:IF NOT EXISTS )?ux_risk_limits_default(.*?);",
        sql, re.S | re.I,
    )
    assert m, "ux_risk_limits_default is not created in this file"
    definition = " ".join(m.group(1).split())
    # Cheap floor so the equality below cannot be satisfied by two empty strings
    # or by the name appearing in a commented-out statement.
    assert "ON risk_limits" in definition, definition
    return definition


def test_a_fresh_database_gets_the_same_four_guards_as_a_migrated_one():
    """init.sql builds new volumes and the migration repairs existing ones. A
    constraint on only one of them is a rule that holds on the deployed database
    and not on the next developer's, or the reverse — and either way it is found
    by a row that should not exist.

    Predicates, not names, and equal to each other rather than merely both
    present: two databases carrying a constraint with one name and two different
    bodies is exactly the drift this pairing exists to prevent, and the name is
    then actively misleading — `\\d risk_limits` shows the guard on both.
    """
    from_init = _check_predicates(INIT_SQL.read_text(), _CK_IN_INIT)
    from_migration = _check_predicates(V2_SQL.read_text(), _CK_ADDED_IN_MIGRATION)

    assert set(from_init) == _EXPECTED_CHECKS, f"infra/init.sql declares {set(from_init)}"
    assert from_migration == from_init, (
        "a fresh database and a migrated one would not carry the same rules: "
        f"init.sql has {from_init}, the migration ADDs {from_migration}"
    )
    assert (_default_index_definition(V2_SQL.read_text())
            == _default_index_definition(INIT_SQL.read_text()))


def test_the_orm_declares_the_same_guards_as_the_sql():
    """models.py is the third mirror, and the one a reader consults before
    writing an INSERT. If it disagrees with the DDL it teaches a row shape the
    database will reject — or, worse, describes a rule the database does not
    have.

    Predicate text is compared literally, so the three copies have to be written
    the same way as well as mean the same thing. That is a real constraint on
    whoever edits them, and it is the price of being able to check them at all
    offline: nothing here can evaluate SQL.
    """
    assert _orm_check_predicates() == _check_predicates(INIT_SQL.read_text(), _CK_IN_INIT)

    index = next((i for i in RiskLimit.__table__.indexes
                  if i.name == "ux_risk_limits_default"), None)
    assert index is not None, "models.py does not declare ux_risk_limits_default"
    assert index.unique
    assert [c.name for c in index.columns] == ["portfolio_id", "limit_type"]
    assert str(index.dialect_options["postgresql"]["where"]) == "entity_id IS NULL"


# ─── …and the guards still forbid what they were written to forbid ───────────

# A row that satisfies every constraint, so each case below can vary one thing.
_LEGAL_ROW = dict(warning_level=0.10, breach_level=0.20, unit="fraction",
                  is_active=1, entity_id=None)

# Per constraint: (the fields this row varies, must it be ADMITTED, why).
# The `why` lands in the failure message — whoever trips one of these should
# come away with the argument, not with a line to delete.
_GUARD_CASES: dict[str, list[tuple[dict, bool, str]]] = {
    "ck_risk_limits_levels": [
        (dict(warning_level=0.20, breach_level=0.20), False,
         "breach == warning kills the warning tier outright. _check_one tests "
         "breach FIRST, so every reading that should have warned is reported as a "
         "breach and no reading can ever produce a warning. Equality does this "
         "exactly as thoroughly as inversion does, which is the whole reason the "
         "comparison is strict — relaxing `>` to `>=` here reads like tidying and "
         "deletes a tier"),
        (dict(warning_level=0.30, breach_level=0.20), False,
         "inverted levels: same failure, more obvious"),
        (dict(warning_level=0.0, breach_level=0.20), False,
         "warning_level <= 0 makes every positive reading an alert — _check_one's "
         "only floor is its `current_value <= 0` early return"),
        (dict(warning_level=-0.10, breach_level=0.20), False,
         "a negative warning level is the same failure as zero"),
        (dict(warning_level=0.10, breach_level=0.20), True,
         "the ordinary seeded shape has to keep working"),
        (dict(warning_level=1.10, breach_level=1.20), True,
         "gross_exposure legitimately sits above 1.0, and higher on a levered "
         "book — this guard judges ordering, never plausibility"),
    ],
    "ck_risk_limits_unit": [
        (dict(unit=None), False,
         "an explicit unit=NULL row. `unit` is nullable and a CHECK whose "
         "predicate evaluates to NULL is SATISFIED, so `unit = 'fraction'` on its "
         "own admits this row — the constraint would read as coverage while "
         "providing none. The IS NOT NULL half is what rejects it, and it is not "
         "redundant"),
        (dict(unit="percent"), False,
         "nothing reads this column and _check_one compares raw floats, so "
         "unit='percent', warning=15, breach=20 is a limit that can never fire"),
        (dict(unit="fraction"), True, "the only scale the engine can act on"),
    ],
    "ck_risk_limits_default_active": [
        (dict(is_active=0, entity_id=None), False,
         "app_rls has no DELETE, so is_active=false is a user's only way to retire "
         "a limit. Aimed at a required portfolio-wide default it arms a run failure "
         "for later — 'deactivate' and 'fail every future run' must not be the "
         "same button"),
        (dict(is_active=0, entity_id="AAPL"), True,
         "a per-entity override stays deactivatable; that is the supported way to "
         "retire one"),
        (dict(is_active=1, entity_id=None), True, "an active default is the norm"),
    ],
}


def _admits(predicate: str, row: dict) -> bool:
    """Would a CHECK with this predicate let `row` into the table?

    sqlite is used here as nothing but a three-valued-logic evaluator — no schema
    is loaded and no Postgres behaviour is being simulated beyond `AND`/`OR`,
    comparison and NULL, which the two agree on. It is here because the rule under
    test IS a NULL rule: a CHECK rejects a row only when its predicate evaluates
    to FALSE, and NULL passes. Modelling that by hand would mean re-deciding it in
    Python, which is the assumption the unit guard exists to disprove.

    A predicate sqlite cannot parse fails loudly rather than being waved through.
    """
    full = {**_LEGAL_ROW, **row}
    columns = ", ".join(full)
    db = sqlite3.connect(":memory:")
    try:
        db.execute(f"CREATE TABLE r ({columns})")
        db.execute(f"INSERT INTO r ({columns}) VALUES ({', '.join('?' * len(full))})",
                   tuple(full.values()))
        try:
            verdict = db.execute(f"SELECT ({predicate}) FROM r").fetchone()[0]
        except sqlite3.Error as exc:
            raise AssertionError(
                f"this predicate cannot be evaluated offline, so nothing here can "
                f"tell you what it admits: {predicate!r} ({exc})"
            ) from exc
    finally:
        db.close()
    # FALSE rejects; TRUE and NULL both admit. That asymmetry is the point.
    return verdict != 0


def test_each_guard_forbids_what_it_was_written_to_forbid_not_merely_the_same_text():
    """The two tests above pin the three mirrors TO EACH OTHER and to nothing
    else. That catches drift between the files and no other thing: relax
    `unit IS NOT NULL AND unit = 'fraction'` to `unit = 'fraction'` in all three
    and every pairing still holds — and because the parity tests force an editor
    to touch all three anyway, "simplify it everywhere" is the NATURAL shape of
    the edit that puts the defect back. Same for `>` relaxed to `>=`. Both
    reintroduce a live-database defect with the suite green.

    So the rule itself is restated here, as rows each predicate must reject.

    Yes, that duplicates the rule, and the rest of this file exists to delete
    duplicates. The distinction is what gets duplicated. A threshold NUMBER must
    live in exactly one place, because two copies can disagree about the desk's
    policy and nothing can say which one is in force. A RULE is precisely the
    thing a test is supposed to restate: it has no second opinion to be wrong
    about, and a rule nothing restates is a rule the next tidying edit relaxes
    with the suite green.
    """
    assert set(_GUARD_CASES) == _EXPECTED_CHECKS, (
        "a constraint was added or renamed without saying what it forbids: "
        f"{set(_GUARD_CASES) ^ _EXPECTED_CHECKS}"
    )
    for source, predicates in _the_three_mirrors().items():
        assert set(predicates) == _EXPECTED_CHECKS, f"{source} declares {set(predicates)}"
        for name, cases in _GUARD_CASES.items():
            for row, admitted, why in cases:
                assert _admits(predicates[name], row) is admitted, (
                    f"{source}: {name} must {'admit' if admitted else 'REJECT'} "
                    f"{row} — {why}.\nAs written: {predicates[name]}"
                )


# ─── The seed CSV is gone, not merely unused ──────────────────────────────────

def test_the_seed_csv_is_deleted():
    """Leaving the file in the tree keeps a fourth set of thresholds one
    `open()` away, and this one was already wrong: it carried a stress_loss_tech
    row nothing looks up and no gross_exposure row at all."""
    assert not (ROOT / "data" / "demo" / "risk_limits_seed.csv").exists()


def test_the_demo_seed_builds_every_limit_row_out_of_the_module():
    """Run the builder and check the rows, field by field.

    seed_demo_db.py DELETEs port_001's limits and reinserts them, and
    create_portfolio copies port_001 — so a wrong row here does not just break
    the demo book, it propagates to every portfolio created afterwards.

    Reading the source for `LIMIT_SPECS[` instead of running it is what this
    replaced, and it was not merely weak: the name appears in the overrides
    branch too, so the defaults branch could hand entity_type the literal
    'portfolio' with the assertion still satisfied — which seeds
    sector_concentration as entity_type='portfolio', and that is what GET
    /portfolios/{id}/limits then shows the user.
    """
    rows = _seed_module().build_demo_limit_rows()
    assert len(rows) == len(SEED_DEFAULTS) + len(DEMO_OVERRIDES)

    for row in rows:
        limit_type = row["limit_type"]
        assert row["portfolio_id"] == "port_001"
        assert limit_type in LIMIT_SPECS, limit_type
        # Authoritative over anything a row could carry: stress_loss is keyed per
        # scenario and reported against the whole book.
        assert row["entity_type"] == LIMIT_SPECS[limit_type].entity_type, limit_type
        # _check_one compares raw floats, so a row on another scale cannot fire;
        # ck_risk_limits_unit rejects anything else outright.
        assert row["unit"] == "fraction", limit_type
        assert row["is_active"] is True, limit_type
        # Both constraint halves, before Postgres is anywhere near this: a
        # non-positive warning alerts on every positive reading, and breach at or
        # below warning deletes the warning tier because breach is tested first.
        assert 0 < row["warning_level"] < row["breach_level"], limit_type

    ids = [row["id"] for row in rows]
    assert len(set(ids)) == len(ids), "two limit rows share an id"
    assert all(i.startswith("rl_") for i in ids), ids

    defaults = {r["limit_type"]: (r["warning_level"], r["breach_level"])
                for r in rows if r["entity_id"] is None}
    assert defaults == dict(SEED_DEFAULTS)

    overrides = {(r["limit_type"], r["entity_id"]): (r["warning_level"], r["breach_level"])
                 for r in rows if r["entity_id"] is not None}
    assert overrides == dict(DEMO_OVERRIDES)


class _RecordingCursor:
    """Enough of a psycopg2 cursor to run seed_risk_limits, and no more."""

    def __init__(self, log: list):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("execute", " ".join(sql.split()), params))


class _RecordingConn:
    def __init__(self):
        self.log: list = []
        self.commits = 0

    def cursor(self):
        return _RecordingCursor(self.log)

    def commit(self):
        self.commits += 1


def test_the_writer_attempts_exactly_the_rows_the_builder_built(monkeypatch):
    """build_demo_limit_rows() is tested above by running it. seed_risk_limits —
    the function that actually DELETEs port_001's limits and INSERTs new ones — was
    only read as an AST for three substrings, which pins nothing about what it
    writes: replace its body with one hardcoded row and the suite stays green while
    the demo book ships seven of its eight required defaults short. Under the
    contract this change is building toward, that is a portfolio that cannot
    complete a run, and create_portfolio copies port_001, so it propagates.

    So the writer is driven against a recording connection and the rows it hands
    to the driver are compared to the builder's, field by field.

    The comparison goes through the INSERT's own declared column list rather than
    through RISK_LIMIT_COLUMNS: the rows arrive as positional tuples, and reading
    the names off the statement that will consume them is what makes a tuple built
    in one order and a column list written in another — warning_level landing in
    breach_level — visible here instead of in the database.
    """
    module = _seed_module()
    conn = _RecordingConn()
    sent: list = []

    def _recording_execute_values(cur, sql, rows, *_a, **_k):
        sent.append((" ".join(sql.split()), [tuple(row) for row in rows]))

    monkeypatch.setattr(module, "execute_values", _recording_execute_values)
    module.seed_risk_limits(conn)

    assert [entry[0] for entry in conn.log] == ["execute"], (
        "seed_risk_limits ran a statement this test cannot see; every write it "
        f"makes has to be checked here: {conn.log}"
    )
    _kind, delete_sql, delete_params = conn.log[0]
    assert delete_sql.startswith("DELETE FROM risk_limits WHERE portfolio_id ="), delete_sql
    assert delete_params == (module.DEMO_PORTFOLIO_ID,), (
        "the DELETE has to be scoped to the demo book — this script must not reset "
        f"another portfolio's limits: {delete_params}"
    )
    assert len(sent) == 1, f"expected exactly one bulk INSERT, got {len(sent)}"
    assert conn.commits == 1

    insert_sql, written = sent[0]
    columns = re.match(r"INSERT INTO risk_limits \((.*?)\) VALUES %s$", insert_sql)
    assert columns, f"the INSERT no longer declares its columns: {insert_sql}"
    names = [c.strip() for c in columns.group(1).split(",")]

    expected = module.build_demo_limit_rows()
    assert len(written) == len(expected), (
        f"the writer sends {len(written)} rows; the builder builds {len(expected)}"
    )
    assert set(names) == set(expected[0]), (
        f"the INSERT's columns and the builder's fields differ: {set(names) ^ set(expected[0])}"
    )
    got = [dict(zip(names, row, strict=True)) for row in written]

    # `id` is random per call, so it is checked for shape rather than compared.
    ids = [row["id"] for row in got]
    assert all(isinstance(i, str) and i.startswith("rl_") for i in ids), ids
    assert len(set(ids)) == len(ids), "two rows would be written with the same id"

    def comparable(rows):
        return sorted(({k: v for k, v in row.items() if k != "id"} for row in rows),
                      key=lambda row: (row["limit_type"], row["entity_id"] or ""))

    assert comparable(got) == comparable(expected)


_FILE_READING_CALLS = frozenset({
    "open", "read", "readlines", "read_text", "read_bytes",
    "load", "loads", "safe_load", "full_load", "read_csv", "read_json",
})

# Reaching a path at all is the tell, whatever is done with it afterwards.
# DATA_DIR and ROOT are this script's own module-level paths.
_PATH_NAMES = frozenset({"Path", "os", "path", "DATA_DIR", "ROOT"})


def test_the_demo_seed_reads_no_file_for_its_numbers():
    """The behavioural test above cannot see WHERE a number came from — a row
    built by parsing a file that happens to agree with SEED_DEFAULTS today passes
    it. This is the structural half: neither the builder nor the writer may read
    anything.

    Checked by call name and by any path being touched, not by three substrings.
    The narrow version named `csv`, `open(` and `risk_limits_seed`, and
    `yaml.safe_load((ROOT / 'configs' / 'risk_limits.yaml').read_text())` satisfies
    all three — which is not a hypothetical, because configs/risk_limits.yaml is
    still in the tree as this lands and still holds all eight thresholds at exactly
    the SEED_DEFAULTS numbers. It is due to be deleted later in this change; this
    test does not depend on that happening, because what it guards is the shape —
    a number arriving from outside the module — and not one filename.

    Read as code with docstrings removed, not as text. Both functions' docstrings
    name the retired CSV in order to say it is gone, and a substring check over the
    raw source would call those sentences a violation — punishing the explanation
    while a `csv` in a comment-free one-liner slipped past.
    """
    tree = ast.parse(SEED_SCRIPT.read_text())
    for name in ("build_demo_limit_rows", "seed_risk_limits"):
        fn = next((n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == name), None)
        assert fn is not None, f"scripts/seed_demo_db.py has no {name}"
        body = fn.body[1:] if ast.get_docstring(fn) else fn.body
        code = "\n".join(ast.unparse(stmt) for stmt in body)

        assert "risk_limits_seed" not in code, name
        assert "csv" not in code, f"{name} must not read a file for its numbers"

        called: set[str] = set()
        mentioned: set[str] = set()
        for statement in body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    fn_node = node.func
                    called.add(getattr(fn_node, "attr", None) or getattr(fn_node, "id", ""))
                if isinstance(node, ast.Name):
                    mentioned.add(node.id)
                elif isinstance(node, ast.Attribute):
                    mentioned.add(node.attr)

        assert not called & _FILE_READING_CALLS, (
            f"{name} reads a file for its numbers via {sorted(called & _FILE_READING_CALLS)}; "
            "the thresholds come from analytics/limit_defaults and nowhere else"
        )
        assert not mentioned & _PATH_NAMES, (
            f"{name} reaches for a path ({sorted(mentioned & _PATH_NAMES)}); there is "
            "no file it is allowed to consult for a threshold"
        )
