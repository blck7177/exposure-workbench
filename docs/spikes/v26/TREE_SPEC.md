# The catalogue tree — what each level tells the model

## The one-page version (2026-09-07, after the boss cut it back) — THIS is the plan — BUILT 2026-09-07 (MODULE_NOTES M27; local, uncommitted)

The tree is `ls`: each level lists what is under it, and every entry says in one line what it is
and how to open or call it. One concept, three levels, three changes.

**Three levels**
- `describe()` — the root: portfolios and issuers, each with one line and `open`.
- `describe(subject)` — one subject: everything under it, each entry with four fields: name, what
  it is, one line, how to use it. Four kinds of entry: a method (`compute`), a group of figures
  (`read_book`), a filed line (`read_fundamentals`), a domain (`describe(expand=…)`).
- `describe(subject, expand=<domain>)` — one domain: its knowledge card plus the methods and
  figures it uses, each with how to use it.

**Three changes**
1. Every listed entry in the catalogue goes from a bare name to {name, is, one line, call|open};
   a domain can be expanded on its own; the root takes no `expand`.
2. compute's `method` and read_fundamentals' `metric` are enums of the same name list the
   catalogue prints, so a name at the wrong door cannot be written.
3. The three tools' unknown-name refusals look the name up in that same list and say "this is X,
   used as Y".

Not part of the plan (kept below as reference only): `about=` search, strict mode, the
`capabilities` map, `Procedure.reads`, the invariant list, per-face construction.

---

## Reference: the long version (superseded where it goes beyond the page above)


Companion to `ROOT_CAUSES.md` (class 1, pattern A). Proposed 2026-09-07, for discussion; not built.

Criterion (boss): **the tree returns facts and addresses and never resolves intent on the model's
behalf.** Every payload answers three questions in its own fields: *where am I* (`level`), *how do
I open the next level* (`next`, as calls the model can copy), *how do I call what is listed here*
(`call` on every leaf). Skill stays tool-free: the catalogue computes `call` from a name's kind, and
one name table is the shared constant behind the schema enums, the refusals and the search.

Payloads below use today's live data (`port_001`, `run_72e6617afeb7`, `MSFT`). Sizes are tiktoken
`o200k_base`.

---

## L0 — resident: what the model knows before any call

**Tool schemas** (10 on the meta face, 8 on research). Changes:

| tool | change |
|---|---|
| `describe` | schema is two branches: `{subject: null, expand: null, about?}` or `{subject: string, expand: <data domain or a domain name of that subject kind>, about?}` — an `expand` at the root is unrepresentable. Description states the tree: *"Level 1, describe(): the desk — portfolios with ids, prepared issuers, the analyst's domains. Level 2, describe(subject): one portfolio, run, scenario or ticker — what is held, its methods with the call for each, its domains. Level 3, describe(subject, expand=<domain>): one node opened. describe(subject, about='…') searches names. Every payload carries `next`."* |
| `compute` | `method` is an enum of the face's registry names (46 meta / 40 research, 248 tokens); `op`-shape and `method`-shape are two `anyOf` branches, so filling both is unwritable. Description states the algebra once, macro: *"the one place a figure is computed. Two shapes: an op over fact ids, or a registry method over a subject. Every result is a fact, so results compose: a method over a list, then an op over its facts, is two calls."* |
| `read_book` | description states the capability, not cases: *"the desk's own work — a run's or scenario's figures and sections, a portfolio's sections, a ticker's brief and alerts — by the names describe lists for that subject."* The `is` field on every listed name and the `method` enum on compute do the disambiguation; no "not X" clause. |
| `read_fundamentals` | `metric` is an enum of `SUPPORTED_METRICS` (47); description states the capability: *"an issuer's filed figures, by line: a flow over a window, a series of windows, or a balance at an instant."* The enum makes a method name unwritable here; no signpost sentence. |
| `respond` | one example block in the description (`{fact: id}` in a slot, never inside a string). |

All schemas normalised for strict mode (every property listed in `required`, nullable types;
`oneOf` → `anyOf`). Whether gpt-5.4-mini's strict accepts every keyword in use is measured first.

**`_SYSTEM`**: unchanged discipline paragraph plus one sentence (~40 tokens): *"The desk is a
tree; start at describe(). Every payload lists `next` and every listed name carries `call` — copy
them; ids come from the tree."* The kind → tool mapping is NOT restated in the prompt: it is one
table (`KIND_TO_CALL`) in the catalogue, rendered once at the root as `capabilities` and used to
compute every `call` — a shared constant, not a second encoding.

Resident cost: read core 1,884 → ≈ 2,500 tokens (+ enums, + one line per tool); `_SYSTEM` ≈ +120.

---

## L1 — the root: `describe()`

**Purpose.** Pick a subject; see the map of domains; learn the two-step address. Nothing else.

**Fields.**

```json
{"level": "desk",
 "portfolios": [{"portfolio_id": "port_001", "name": "US Growth & Income Portfolio", "is_own": false,
                 "latest_completed_run": {"run_id": "run_72e6617afeb7", "as_of": "2026-09-04"},
                 "positions": 10, "alerts": 2, "open": "describe('port_001')"}],
 "issuers_prepared": ["AAPL", "AMZN", "GOOGL", "JPM", "KO", "LLY", "MSFT", "NVDA", "XOM"],
 "issuer_open": "describe('<ticker>')",
 "domains": [
   {"name": "book_liquidity", "subject": "portfolio",
    "question": "how fast the book can be sold down, and which names would hurt",
    "asked_as": ["if I had to get out in a hurry which positions hurt", "liquidity not price"],
    "methods": ["price.adv"], "reads": ["concentration"],
    "open": "describe('<port_…>', expand='book_liquidity')"},
   {"name": "issuer_earnings_quality", "subject": "issuer",
    "question": "are the profits real: is cash showing up behind earnings …",
    "methods": ["accruals_ratio", "cash_conversion", "days_sales_outstanding", "days_inventory", "days_payable"],
    "reads": ["net_income", "operating_cash_flow", "receivables", "inventory"],
    "open": "describe('<ticker>', expand='issuer_earnings_quality')"}
   ],
 "capabilities": {
   "fundamentals": {"holds": "filed figures per issuer, by line and period", "names": "filed lines (47)",
                    "read": "read_fundamentals('<ticker>', metric=<line>)", "computed": "issuer methods (33): compute(method=<name>, subject='<ticker>')"},
   "filings":      {"holds": "10-K / 10-Q text by item", "read": "read_filings('<ticker>', query=… | item=…)"},
   "prices":       {"holds": "daily closes per name", "read": "read_prices('<ticker>', window=…)",
                    "computed": "price methods (7): compute(method=<name>, subject='<ticker>')"},
   "book":         {"holds": "each portfolio's runs: figures by row name, sections, limits, positions",
                    "read": "read_book('<run_…>' | '<port_…>', names=[…])",
                    "computed": "run and portfolio methods (6): compute(method=<name>, subject='<run_…>' | '<port_…>')"},
   "web":          {"read": "search_web(query=…, days=…)"}},
 "desk_rules": [{"rule": "…", "authority": "…"}],
 "not_held": {"segment_revenue": {"why": "…", "instead": "read_filings('<ticker>', query='segment revenue')"}},
 "cannot":   {"per_name_factor_sensitivity": {"why": "…", "instead": "compute(method='price.beta', subject='<ticker>', params={'benchmark': 'TLT'})"}},
 "withheld": "…",
 "next": ["describe('port_001')", "describe('<ticker>')", "describe(<subject>, about='<what you need>')"]}
```

**Rules for this level.** Subjects in `open` are placeholders (`<port_…>`, `<ticker>`): the root
does not choose a subject. No run figure names (they are a run's). No bare method lists (a method
appears under its domain, with `open`). No values.

**Size.** 2,159 today → ≈ 2,400.

---

## L2 — a subject: `describe(subject)`

**Purpose.** What the desk holds about this one subject; its methods with the call for each (the
hot set); its domains and how to open one. Concrete ids here are facts.

Common to every kind: `level`, `subject`, `kind`, `identity`, `methods` (callable rows),
`domains` (name, question, methods, reads, open), `absences` (the kind's `not_held`/`cannot` with
`instead`), `desk_rules` (the kind's scope), `next`, `withheld`.

**The callable row** — one shape for every leaf kind:

```json
{"name": "book.drawdown_episodes", "is": "portfolio method",
 "does": "every peak-to-trough episode of the book at least 5% deep in a span, deepest first, with trough and recovery dates",
 "call": "compute(method='book.drawdown_episodes', subject='port_001', params={'span': '1y'})",
 "params": {"span": "3m | 6m | 1y | 3y (default 1y)"},
 "yields": ["portfolio.drawdown_episodes.deepest_depth", "portfolio.drawdown_episodes.episode_depths"]}
```
`is` ∈ {issuer method, price method, run method, portfolio method, run figure, portfolio section,
filed line, domain, op}; one `is` per name; `yields` omitted when it is the name itself. ≈ 51 tokens.

### Portfolio — `describe('port_001')`

```json
{"level": "portfolio", "subject": "port_001",
 "identity": {"name": "US Growth & Income Portfolio", "is_own": false},
 "sections": {
   "positions": {"count": 10, "call": "read_book('port_001', names=['positions'])"},
   "limits":    {"count": 13, "call": "read_book('port_001', names=['limits'])"},
   "alerts":    {"count": 2,  "call": "read_book('port_001', names=['alerts'])"},
   "freshness": {"latest_completed_run": "run_72e6617afeb7", "run_as_of": "2026-09-04", "sessions_behind": 0,
                 "call": "read_book('port_001', names=['freshness'])"}},
 "runs": [{"run_id": "run_72e6617afeb7", "as_of": "2026-09-04", "status": "completed", "open": "describe('run_72e6617afeb7')"}, "…"],
 "methods": [
   {"name": "book.drawdown_episodes", "is": "portfolio method", "does": "…", "call": "compute(method='book.drawdown_episodes', subject='port_001', params={'span': '1y'})", "params": {"span": "…"}, "yields": ["…"]},
   {"name": "book.explain_episode",   "is": "portfolio method", "does": "…", "call": "compute(method='book.explain_episode', subject='port_001', params={'peak': 'YYYY-MM-DD', 'trough': 'YYYY-MM-DD'})"},
   {"name": "book.analysis",  "is": "run method", "does": "…", "call": "compute(method='book.analysis', subject='run_72e6617afeb7')"},
   {"name": "book.reconcile", "is": "run method", "…": "…"},
   {"name": "book.sell", "is": "run method", "call": "compute(method='book.sell', subject='run_72e6617afeb7', params={'sales': [{'ticker': 'MSFT', 'fraction': 0.5}]})"},
   {"name": "book.buy",  "is": "run method", "…": "…"}],
 "domains": [
   {"name": "book_composition", "question": "…", "methods": [], "reads": ["concentration"], "open": "describe('port_001', expand='book_composition')"},
   {"name": "book_liquidity", "question": "…", "methods": ["price.adv"], "reads": ["concentration"], "open": "describe('port_001', expand='book_liquidity')"},
   "… 7 book domains"],
 "absences": {"cannot": {"per_name_factor_sensitivity": {"why": "…", "instead": "compute(method='price.beta', subject='<ticker>', params={'benchmark': 'TLT'})"}}},
 "desk_rules": ["… book scope"],
 "next": ["describe('run_72e6617afeb7')", "describe('port_001', expand='<domain>')", "read_book('port_001', names=['positions'])"]}
```
No run figure names here: the portfolio points at the run. ≈ 1,748 → 2,400 tokens.

### Run — `describe('run_72e6617afeb7')`

```json
{"level": "run", "subject": "run_72e6617afeb7", "portfolio_id": "port_001", "as_of": "2026-09-04", "status": "completed",
 "figures": {"count": 161,
   "groups": [
     {"group": "whole_book", "answers": "size, day P&L and net/gross exposure of the whole book",
      "names": ["exposure_metrics.portfolio_market_value", "exposure_metrics.daily_pnl", "…"],
      "call": "read_book('run_72e6617afeb7', names=['exposure_metrics.portfolio_market_value'])"},
     {"group": "concentration", "answers": "which issuers and sectors the book is concentrated in",
      "patterns": [{"patterns": ["issuer_exposures.<label>.weight", "issuer_exposures.<label>.market_value"], "labels": ["AAPL", "…"]}],
      "call": "read_book('run_72e6617afeb7', names=['issuer_exposures.MSFT.weight'])"},
     "… mandate, factor_exposure, attribution, risk, counts"],
   "units": {"exposure_metrics": {"portfolio_market_value": "MONEY", "…": "…"}}},
 "sections": {"alerts": {"call": "read_book('run_72e6617afeb7', names=['alerts'])"}, "attribution": {"…": "…"}, "risk_state": {"…": "…"}},
 "methods": ["… the four run methods as callable rows with subject='run_72e6617afeb7'"],
 "domains": ["… the 7 book domains, open on this run: describe('run_72e6617afeb7', expand='book_market_risk')"],
 "next": ["read_book('run_72e6617afeb7', names=[…])", "describe('run_72e6617afeb7', expand='book')  — every name, unfactored", "describe('port_001')"]}
```
A run that is not `completed` is refused here (`run_not_completed`, with `status` and the task to
read) — the same check `read_book` must make (class 2). The group formerly keyed `book` is renamed
so `book` is not a row-group, a method prefix, a domain prefix and an expand value at once.
≈ 2,886 → 3,400 tokens.

### Scenario — `describe('calc_…')`
As the run, with `from_run`, `trade`, the after-book's groups; `methods`: `book.sell` / `book.buy`
with subject = this row (a chain), nothing else.

### Issuer — `describe('MSFT')`

```json
{"level": "issuer", "subject": "MSFT",
 "identity": {"name": "Microsoft Corporation", "cik": "…", "sector": "Technology",
              "held": {"in": "port_001", "latest_run": "run_72e6617afeb7",
                       "call": "read_book('run_72e6617afeb7', names=['issuer_exposures.MSFT.weight', 'issuer_exposures.MSFT.market_value'])"}},
 "fundamentals": {"periods": {"first": "2021-06-30", "last": "2026-03-31", "count": 20},
   "filed_lines": ["revenue", "net_income", "operating_cash_flow", "capex", "…  (the 47 the desk maps; those MSFT filed)"],
   "call": "read_fundamentals('MSFT', metric='capex')",
   "detail": "describe('MSFT', expand='fundamentals')  — periods and coverage per line"},
 "filings": {"forms": {"10-K": 5, "10-Q": 15}, "latest": "…", "items": ["1", "1A", "7", "7A", "8"],
   "call": "read_filings('MSFT', query='<words>')  | read_filings('MSFT', item='1A')"},
 "prices": {"first": "…", "last": "2026-09-04", "count": 1256, "call": "read_prices('MSFT', window='1y')"},
 "methods": {
   "price":  ["… 7 rows, e.g. price.beta: compute(method='price.beta', subject='MSFT', params={'benchmark': 'TLT'})"],
   "issuer": ["… 33 rows, e.g. gross_margin: compute(method='gross_margin', subject='MSFT', params={'months': 12}) ; params.last_n=8 for its history"]},
 "domains": ["… the 7 issuer domains with methods, reads, open"],
 "absences": {"not_held": {"segment_revenue": {"why": "…", "instead": "read_filings('MSFT', query='segment')"}}, "not_filed": ["… lines MSFT has no facts for"]},
 "desk_rules": ["… issuer scope"],
 "next": ["describe('MSFT', expand='<domain>')", "read_fundamentals('MSFT', metric=…)", "read_filings('MSFT', item='1A')", "read_prices('MSFT', window='1y')"]}
```
Density option: all 33 issuer rows at L2 (≈ +1,150 tokens; MSFT ≈ 4,600) or names under domains
with rows behind `expand=<domain>` (≈ +300; MSFT ≈ 3,700). Both drafted; the boss chooses.

---

## L3 — one node: `describe(subject, expand=X)`

`X` is a domain name of the subject's kind, or a data domain: `fundamentals` (periods and
coverage per filed line), `filings` (sections and counts — the payload shape that crashed the
adapter, declared as structure not figures), `book` (every row name, unfactored), `readings`,
`methods` (every full card; kept, not advertised).

**A domain node** — `describe('port_001', expand='book_liquidity')`:

```json
{"level": "domain", "subject": "port_001", "domain": "book_liquidity",
 "question": "how fast the book can be sold down, and which names would hurt",
 "asked_as": ["… all five"],
 "evidence": ["each position's market value on the run", "each name's dollars a day traded over the window", "…"],
 "this_desk": ["liquidity is read as days to liquidate: market value over dollars a day traded, at a participation rate the reading states; the desk fixes none — the user's, or none, and the answer says which", "…"],
 "compare": ["…"], "close": ["…"], "absent": "…", "authority": "SEC Rule 22e-4; …",
 "methods": [
   {"name": "price.adv", "is": "price method",
    "does": "average dollars a day traded over the window",
    "procedure": "mean of close × volume over the last window_days sessions", "fails_when": "fewer sessions than window_days",
    "params": {"window_days": "20 | 30 | 60 (default 20)"},
    "call": "compute(method='price.adv', subject=['AAPL', 'MSFT', 'LLY', '…'], params={'window_days': 20})",
    "yields": ["{ticker}.adv"]}],
 "reads": [
   {"group": "concentration", "is": "run figure", "call": "read_book('run_72e6617afeb7', names=['issuer_exposures.MSFT.market_value', '…'])"}],
 "next": ["describe('port_001')", "…the calls above"]}
```
The domain's `methods` and `reads` are declared on the `Procedure` by name and checked at
construction (the name exists, its kind fits the domain's subject kind). The domain's closing
arithmetic stays in `close` as knowledge; it is NOT rendered as a call chain — that is the script
V25 removed, and the unit algebra (MONEY ÷ MONEY_PER_DAY = COUNT) already carries it.
≈ 1,000–1,500 tokens for one domain, instead of 3,853 / 5,068 for all.

---

## Search — `describe(subject, about='…')`

BM25 over the name table (name, `does`, params, yields, domain `asked_as`/`evidence`), restricted
to the subject's kind when a subject is given. Returns rows, never runs anything:

```json
{"level": "search", "subject": "port_001", "about": "days to liquidate each name",
 "matches": [
   {"name": "price.adv", "is": "price method", "domain": "book_liquidity", "does": "…", "call": "compute(method='price.adv', subject=[…], params={'window_days': 20})"},
   {"name": "book_liquidity", "is": "domain", "open": "describe('port_001', expand='book_liquidity')"},
   {"name": "concentration", "is": "run figure", "call": "read_book('run_72e6617afeb7', names=['issuer_exposures.<label>.market_value'])"}]}
```
≈ 400 tokens.

---

## Refusals — every door, one shape

```json
{"error": "unknown_name", "name": "book.drawdown_episodes",
 "route": {"is": "portfolio method", "call": "compute(method='book.drawdown_episodes', subject='port_001', params={'span': '1y'})"},
 "detail": "not a row this run holds; it is a method — the call above"}
```
When the name is in no vocabulary: `nearest` across all vocabularies, each with `is` and `call`.
`route` returns the call and never performs it.

---

## Invariants (each a test)

1. One `is` per name across the table; the table is a view over skill / resources / concept_mapping / OPS, not a copy.
2. Every `call`, `open` and `next` string in any payload parses and validates against the named tool's schema on the face it was served (placeholders `<…>` come from a declared set).
3. The root carries no concrete subject in `open`, no run figure names, no values.
4. At the subject level every row's subject is the subject itself or a fact listed in the same payload.
5. `EXPANDS(kind)` = data domains ∪ the kind's `PROCEDURES`; `Procedure.methods ⊆ METHODS` with matching kind; `Procedure.reads ⊆ RUN_GROUPS keys ∪ SUPPORTED_METRICS`.
6. A payload never names a tool outside the face it was served on (describe is built per face, like compute).
7. Size ceilings pinned per level by the live test (to measure: L1 ≈ 2.4k, L2 ≤ 4.6k, L3 ≤ 1.5k tokens).
8. The V24 fact invariants (I1–I3) unchanged: every value in a payload is a Fact with an id; no digits in `note`.

---

## Self-audit (2026-09-07, boss's question: rule-based? fallbacks? case-by-case descriptions?)

Removed from the first draft, and why:

| removed | why it was wrong | what carries it instead |
|---|---|---|
| "a method is not a name" in read_book's description; "a computed measure is compute(…)" in read_fundamentals' | "not X" clauses aimed at one observed failure each — rule patches | the `method`/`metric` enums (unwritable) and the `is` field on every listed name |
| the kind → tool legend in `_SYSTEM` | a second encoding of the same table as the root payload | one `KIND_TO_CALL` table, rendered once, used to compute every `call` |
| `name_kinds` as a flat kind → call list | correct but not macro: it did not say what each data domain holds | `capabilities` by data domain: holds / names / read / computed, derived from the same table |
| `then` on a domain node | a call chain per domain — the V25 script reborn | `close` as knowledge; the unit algebra; compute's one macro sentence on composition |
| `subject_note`, the "months \| last_n \| at" string, the "not prepared" sentence | per-case prose duplicating schema and refusals | the tool schemas' parameter descriptions; the existing `not_prepared` refusal |
| op + method as a defined "pipeline" (ROOT_CAUSES C5b) | two enumerated argument combinations — a case rule | `anyOf` branches make the combination unwritable; results are facts, so composition is two calls, stated once |
| loop-side retrieval injection (ROOT_CAUSES B2) | a second delivery channel beside the tree, decided by a heuristic each turn | not built; measure whether `next`/`open` are followed first |
| new DESK_RULES per observed confusion (participation rate; "P&L is not a drawdown driver") | a rule per instance does not generalise (X18 showed it) | rules stay definitions; X18 is a class-3 (identity in the sentence) matter, not a rule |

Kept, and why they are structural rather than rule-based: two schema branches for describe;
enums + strict; one name table behind enums, refusals and search; the callable row with `is`;
`next`/`open`; `Procedure.methods`/`reads` as declared, constructor-checked relations; one
`route()` for every door, text generated from the table; describe built per face; the invariants.
