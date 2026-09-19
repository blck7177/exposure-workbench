# V25 — the book across updates, the issuer page redrawn: reads only, no new measure

Status: **built** (2026-09-05). §12 records what the build did that this plan
did not say, and why. Phases A–D are green: 2,042 offline tests, 17 live tests,
66 web unit tests, `tsc`, `next build`, and both pages read against the local
stack. Nothing is committed and nothing is deployed. Written from the code at commit
`70912b9` (V24 phase F/G) and from the live database on this machine; every
count below was measured, not recalled. The two mockups the boss reviewed on
2026-09-05 are the visual spec: *Book Page, Tier One* and *Issuer Page, Second
Draft* (links in §11). The plan is a basis, not an authority — the code is.

## §0 The decision this plan records

The boss's framing, 2026-09-05, after reading the interaction review and the
two mockups:

> 金融指标的图要 line chart。然后 user 选择指标，展示对应的图。其他的没问题。

Decisions taken, in order:

1. **Financial measures are drawn as lines**, one at a time, chosen from a
   list of every measure the desk holds for the name. No small multiples, no
   bars.
2. **The issuer page reads in this order**: who this is and how old the data
   is → what it is in the reader's book, as one strip → price, first chart →
   the one financial chart → the desk's brief, in short. The rest of the
   second draft stands as drawn.
3. **The book page gains the seven tier-one items** of the first mockup: the
   book across updates, the sector panel, the holdings columns, linked
   highlight, span + brush + explain on the value chart, the dock's inline
   series, the reconcile line.
4. **Nothing in this batch computes a new financial measure.** Every figure
   drawn is a row a run stored, a calc row the recipe or a service already
   records, or a subtraction of two such figures written beside them
   (`room = tier − current`, `Δ = weight − weight of the previous dated
   update`). The withheld set (`analytics/withheld.py`) is untouched and
   nothing here reaches it.

What this batch is NOT: the scenario drawer over `book.sell`/`book.buy`, the
mandate editor, run-to-run diff, VaR release, historical stress replays,
holdings history. Those are tier two and three of the review and each is its
own batch (§9).

## §1 What is on the two pages today (measured)

| surface | what is drawn | interactions it has |
|---|---|---|
| Book `/` (`apps/web/app/page.tsx`, 364 lines) | chip strip, 5 tiles, value + drawdown, warnings, holdings table, day waterfall, mandate meters, factor betas + correlation heatmap, stress (withheld), briefing, run rail | crosshair tooltip, Table toggle, ⓘ method, click → evidence, Ask → dock, by-factor/by-holding toggle, audit switch |
| Issuer `/issuer/[ticker]` (708 lines) | price vs SPY with filing rules, margins line, coverage table; ladder + baseline measures + how assembled (Financials tab); filings reader; brief + provenance map + sources | metric dropdown on the ladder, tabs, click → evidence |
| Dock (`components/analyst/`, 1,411 lines) | answer blocks with fact chips; a `chart` block renders "open the series" | chip hover/click, suggestions by page |

Front end total: 7,531 lines of TS/TSX across 32 files; no front-end runner but
`vitest` for pure functions (`apps/web/tests/`, 5 files), `tsc`, `next build`,
and `scripts/smoke_ui.py` in a browser.

**Stored and never drawn** (the whole case for tier one):

| data | measured | on the page today |
|---|---|---|
| completed runs of `port_001` | 33 runs · 12 distinct `as_of_date` · 5 runs on 2026-09-03 alone | one run at a time; "vs previous run" chip only |
| `limit_checks` with levels, per run | 20 published rows per run (27 with withheld) | current run's meters only |
| `sector_exposures` per run | 7 rows per run, with `weight_change` vs the previous run | never charted |
| `issuer_exposures.contribution` | stored on every row | not in `IssuerExposureOut`, so not on the wire |
| `issuer_exposures.weight_change` | **always NULL** — `exposure_workflow.py:834` writes `None` | the holdings table has no Δ |
| `positions.cost_basis`, `quantity` | demo book complete, snapshot dated 2026-07-23 | not shown on either page |
| `/portfolios/{id}/history` spans | endpoint accepts `1y · 3y · 5y` (`portfolios.py:322`) | client hard-codes `3y` |
| `/issuers/{t}/price-index` params | `span` and `benchmark` (`issuers.py:201`) | client hard-codes `1y`, `SPY` |
| `/exposure-runs/{id}/reconcile` | exists, records once, reused after | typed in `lib/charts.ts`, never called |
| recipe rows per issuer (MSFT) | 16 rows, 10 of them series (`panel-series` `chartable`) | 3 margins drawn; the rest as a latest value in a table |
| measures per issuer (MSFT) | 37 in `coverage`, 21 flows | a table; no chart of any of them |
| `issuer_briefs` per company | MSFT 1 · LLY 2 · NVDA 3 | latest only |
| the brief's date vs the ledger | brief 2026-07-24 says −42.4% vs SPY over 1y; `return_1y_vs_SPY` computed 2026-08-20 says −21.0% | no date beside the brief's figures |
| `snapshot.portfolio_exposure` | reads the newest `issuer_exposures` row on **any** book (`issuers.py:126`) | shown as "in this book" |
| `chart` blocks in answers | the fact record holds every point | rendered as a link |

## §2 The rules every panel keeps (from the code, unchanged)

1. **A number appears only if a run or a ledger row holds it.** The client
   may sort, filter, highlight and subtract two figures it was sent; it may
   not compute a measure (`panels.tsx` header comment, V13-S6c).
2. **Every chart has a Table and a note.** The table is the audit twin; the
   note says what the picture is not (`charts/frame.tsx` `ChartCard`).
3. **Every figure opens the row it rests on** (`useEvidence().open(id)`).
4. **No read mints a ledger row** (`tests/test_v13_read_endpoints.py`,
   `tests/test_v13_issuer_panels_live.py`): a read that must be recorded
   goes through `calc_service.find_recorded` first, as `/history` and
   `/reconcile` do.
5. **No internal id reaches the reader's layer** (`scripts/smoke_ui.py`):
   ids live behind `AuditOnly`; the affordance is the click, not the id.
   The mockups show calc ids in captions for the reviewer's benefit — the
   build puts them behind `AuditOnly` and keeps the click.
6. **The view's own words come from the server** where the server has them
   (`limit-book.checks.label`, `methods`, `dn.metric`), never re-spelled from
   a key on the client.

## §3 The reads — every API change in this batch

All GET, all `dependencies=[Depends(optional_user)]`, all RLS-scoped through
`get_db`. Decimal → float through `_f`. None is None, never zero.

### A1 `GET /portfolios/{id}/run-series?span=1y` — the book across updates

New `services/run_series_service.py`; the route in `routes/portfolios.py`
beside `/history`. `span ∈ {1y, 3y, all}` (default `1y`), rejected with
`unknown_span` like `/history`.

```jsonc
{
  "portfolio_id": "port_001", "span": "1y",
  "updates": [                                   // one per as_of_date, oldest first
    {
      "as_of": "2026-09-03", "run_id": "run_aacdb498c66f",
      "runs_that_day": 5,                        // collapsed; the latest completed_at wins
      "metrics": {"market_value": 10986070.0, "daily_pnl": 126059.0, "daily_return": 0.01159507,
                  "vol_30d": 0.12156348, "vol_60d": 0.1228, "max_drawdown": 0.17667839, "alerts": 2},
      "issuers": [{"ticker": "MSFT", "weight": 0.16251671, "contribution": 0.00428631,
                   "daily_pnl": 46550.0, "weight_change_vs_prev": 0.00240192}],   // null on the first update
      "sectors": [{"sector": "Technology", "weight": 0.35348127, "weight_change_vs_prev": 0.0024}],
      "checks":  [{"key": "issuer_concentration:MSFT", "current": 0.16251671,
                   "warning": 0.15, "breach": 0.2, "status": "warning"}]          // published_checks only
    }
  ],
  "labels": {"checks": {"issuer_concentration:MSFT": "MSFT · issuer weight"},
             "sectors": {"Technology": "Technology"}},
  "detail": null                                  // or "N updates ran before this desk recorded check levels"
}
```

Rules, each pinned by a test:

- **Collapse by date.** `collapse_by_date(runs) -> list[ExposureRun]` is a
  pure function: for each `as_of_date`, the completed run with the greatest
  `completed_at`; `runs_that_day` is the count collapsed. Five runs on
  2026-09-03 become one point.
- **Δ is against the previous *dated* update**, not the previous row —
  `weight_change_vs_prev = weight − weight on the prior collapsed update`,
  None on the first, None when the name was not held then. This is the
  Holdings Δ column and the sector Δ; it is a subtraction of two stored
  figures written beside them (§0.4) and it is done here, once, not in the
  browser.
- **Checks are `wh.published_checks`** — the VaR, ES and stress rows never
  reach the wire, same filter as `/limit-book`.
- **Labels come from the same source `/limit-book` uses**
  (`dn.label("limit", …)`, `dn.label("sector", …)`), built once per response,
  not per update.
- **It reads and records nothing.** No `calc_service`, no `_record`.

### A2 `/exposure-runs/{id}/limit-book` — two fields per check

`room_warning = warning − current`, `room_breach = breach − current`, signed
(negative when over the tier), None when either side is None. Beside
`utilisation`, computed the same way it is, for the same reason: the Holdings
"room to limit" column and the strip need the figure, and a subtraction the
server writes once beats one the client repeats per row.

### A3 `IssuerExposureOut.contribution: float | None`

`routes/exposure_runs.py:58`. The column exists (`models.py:410`), the row is
written (`exposure_workflow.py:837`), `from_attributes` carries it. The label
on the page is "contribution to the book's day", never "contribution" alone
(§10, risk 4).

`weight_change` stays NULL for issuers in the workflow. Writing it there is a
run-time change to a step that has 33 runs of history behind it and belongs to
its own batch; A1 gives the page the Δ it needs from stored weights.

### A4 `spans` on `/history` and `/price-index`

Both responses gain `"spans": ["1y", "3y", "5y"]` (each file's own `_SPANS`,
sorted), so the span control lists what the endpoint accepts instead of a
copy of the list in TypeScript. `unknown_span` handling is unchanged.

### A5 `snapshot?portfolio=` — the book's own row, or none

`routes/issuers.py:119`. With `portfolio`, `portfolio_exposure` is read from
`exposure_run_service.get_latest_completed_run(db, portfolio_id)` →
`IssuerExposure` for that run and ticker, plus `run_id`, `as_of`,
`contribution`, `daily_pnl`. Without it, `portfolio_exposure` is **null**.
The query that took the newest `issuer_exposures` row on any book is deleted,
not kept as a fallback: it is the wrong book the moment two books hold the
name, and the demo book is public.

### A6 `GET /issuers/{ticker}/briefs` — the history

`[{id, research_run_id, created_at, citations: 32, sections: 6, is_current: true}]`,
newest first, RLS-scoped. No ordering hazard: the literal segment differs from
every sibling under `/issuers/{ticker}/`, and `test_route_reachability.py`
covers the new path the moment it is registered.

### A7 `GET /issuers/{ticker}/balance-series?metric=&last_n=12` — a balance, drawn

`fundamentals_service.get_balance_series` **records a calc row on every
call** (`fundamentals_service.py:335`, `cs._record`). The endpoint therefore
does what `/history` does for episodes: `calc_service.find_recorded(db,
OP_BALANCE_SERIES, identifying_params)` first, mint once when absent.
`identifying_params = {ticker, metric, last_n, latest_period_end}` — the
latest period end is in the key because a new filing makes it a different
calculation, and the lookup keys must be a subset of what the recorder writes
(`test_v13_read_endpoints.py::test_the_lookup_key_is_a_subset…` pattern).

```jsonc
{"ticker": "MSFT", "metric": "long_term_debt_total", "label": "Long-term debt, total",
 "unit_class": "MONEY", "calc_id": "calc_…",
 "points": [{"as_of": "2026-03-31", "value": 31423000000.0, "fact_ids": ["fact_…"]}],
 "basis": "long_term_debt_total as reported at each of 12 instants …; no value is carried across dates"}
```

### A8 `GET /issuers/{ticker}/measures` — the picker

The one response the Financials panel's list is built from. Three groups,
each row saying what it is, how far it goes, its latest figure, and which
views exist for it. **No minting**: flows go through
`ia.consecutive_windows(facts, months=3, last_n=1)` in process (the same call
`/windows` makes), balances read the newest fact, ratios read the recipe
manifest (`financials`) — all reads.

```jsonc
{
  "ticker": "MSFT", "as_of": "2026-08-20",                       // the recipe's own as-of, for the ratios
  "flows": [
    {"metric": "revenue", "label": "Revenue", "periods": 21, "through": "2026-03-31",
     "windows_filed": ["3-month", "12-month"],
     "latest": {"start": "2026-01-01", "end": "2026-03-31", "value": 82886000000.0,
                "derived": false, "fact_ids": ["fact_…"]},
     "latest_12m": {"start": "2024-07-01", "end": "2025-06-30", "value": 281724000000.0, "derived": false},
     "views": ["level", "yoy", "windows"],                      // yoy present because revenue_yoy is a recipe row
     "yoy_metric": "revenue_yoy", "share_metric": null}         // share_metric: "net_margin" on net_income
  ],
  "ratios": [
    {"metric": "net_margin", "label": "Net margin", "unit_class": "RATIO", "calc_id": "calc_2f9eba710a99",
     "points": 12, "latest": {"end": "2026-03-31", "value": 0.38339406}, "views": ["level"]}
  ],
  "balances": [
    {"metric": "long_term_debt_total", "label": "Long-term debt, total", "readings": 21,
     "through": "2026-03-31", "latest": {"as_of": "2026-03-31", "value": 31423000000.0, "fact_ids": ["fact_…"]},
     "views": ["level"], "superseded_by": null}
  ],
  "unavailable": [{"metric": "commercial_paper", "detail": "last reported 2025-06-30"}]
}
```

The `views` list is derived on the server from three facts it has: the
measure's kind, whether the recipe manifest holds `<metric>_yoy`, and the
recipe's `_MARGIN_NUMERATORS` table (`services/recipe.py:40`) for
`share_metric`. The client never decides what a measure can show.

### A9 (reads the client already has, unchanged)

`/windows?metric=` (the flow's 3- and 12-month series with derived flags and
fact ids — the Level view of a flow), `/panel-series?metrics=` (a ratio's or
y/y's points with its calc id), `/latest-brief`, `/evidence/{id}` (a fact
record's `points`, a calc's `result.points` — what the drawer and the dock
draw from), `/exposure-runs/{id}/reconcile`.

## §4 The build

Order of work, each phase green on its own: the offline suite, `vitest`,
`tsc`, `next build`, and the live reads test against the local stack. Phase A
adds nothing a page shows yet; B and C are independent of each other and
either may go first; D closes.

### Phase A — the reads (§3, A1–A8)

Files: `services/run_series_service.py` (new), `routes/portfolios.py`,
`routes/exposure_runs.py`, `routes/issuers.py`, `services/fundamentals_service.py`
(only to expose `OP_BALANCE_SERIES` and an `identifying_params` helper beside
it, as `drawdown_service` does), `services/measures_service.py` (new; A8's
assembly, so the route stays a dozen lines).

Done when: every A-row's tests in §5 pass; `GET /portfolios/port_001/run-series`
returns 12 updates with `runs_that_day` 5 on 2026-09-03 (the number in §1);
three reads of each new endpoint leave `calc_ledger` where it was.

### Phase B — the book page

Numbers are the mockup's badges.

| # | change | files | data |
|---|---|---|---|
| ① | `Composition` row under Holdings: **Sectors** (left) and **Weights across updates** (right); Mandate book gains a `Now / Across updates` control; across mode draws the six checks nearest their tiers as small multiples on calendar time, tier rules horizontal | new `components/book/composition.tsx`, `components/charts/multiples.tsx` (a `SmallMultiples` that takes `{key,label,points:[{date,value}],rules?:[{value,colour,label}],highlight?}`), `panels.tsx` (`MandateBook` mode), `lib/charts.ts` (`RunSeries` type + `getRunSeries`) | A1 |
| ② | Sectors as `TierBars` with **per-row** ticks — `TierBars` today draws one warning and one breach rule for the whole chart from the first bar (`bars.tsx:160`); it gains `tiersPerRow: true`, drawing each row's own ticks, default false so Stress is unchanged | `components/charts/bars.tsx` | `run.sector_exposures` + `limit-book` tiers |
| ③ | Holdings: columns `Δ vs <prev update>`, `Contribution to the day`, `Room to limit`; sortable headers with the current sort marked; default sort stays market value; the stored position (quantity, cost basis) in the Table view only | `components/book/sections.tsx` `Holdings`, `lib/types.ts` (`contribution`) | A1 (Δ), A3, A2 (room) |
| ④ | Linked highlight: `FocusProvider` in `page.tsx` holding `{kind:"ticker"\|"factor"\|"sector", key} \| null`; Holdings rows, the waterfall (both modes), Sectors, Factor betas and the heatmap read it; the source of a hover sets it, everyone else dims to 0.3 opacity — a view state, no data | new `components/book/Focus.tsx`; `sections.tsx`, `panels.tsx`, `bars.tsx` (`Waterfall`/`DivergingBars` take `focus`), `grids.tsx` (`Heatmap` takes `focus`) | none |
| ⑤ | Value and drawdown: span control from `history.spans`; a **brush** on the drawdown strip (`LineChart` gains `brush?: {from,to,onChange}`; the main plot draws the brushed index range — a view transform, nothing recomputed); episode chips become buttons: click brushes to the episode, `Explain` calls `ask("Explain the episode from … to …: what was it made of?")` | `panels.tsx` `ValueAndDrawdown`, `line.tsx`, `page.tsx` (span state) | A4; `book.explain_episode` answers the question, already registered |
| ⑦ | The reconcile line under the waterfall: both identities with ✓/✗, factor share, the calc id behind `AuditOnly`, a click opening the calc; a run the endpoint reports `run_not_reconcilable` for shows its `detail` sentence instead | `panels.tsx` `WhereTheDayWent`, `lib/charts.ts` (type `Reconcile` becomes the endpoint's shape) | `/reconcile` |
| ⑥ | Dock: a `chart` block whose fact is a series draws `LineChart` inline — points fetched lazily from `/evidence/{fact_id}` (`body.points`) when the block scrolls into view, cached per id; the chip and "open the series" stay | `components/analyst/AnswerBlocks.tsx` (`SeriesChart`), `lib/issuer.ts` | existing |

`Tiles` are unchanged. `Warnings` is unchanged. The chip strip's "vs previous
run" wording becomes "vs <date> update" from A1 when the previous run is the
same day (today it reads "unchanged" on a re-run, which is true and
uninformative).

Done when: the book page renders the composition row for `port_001` with 12
points per name; hovering MSFT in Holdings lights the MSFT bar in the
waterfall and the Technology bar in Sectors; the span control switches
`3y → 1y` without a reload; the reconcile line reads `✓ ✓` on
`run_aacdb498c66f`; `smoke_ui.py` finds no id in the reader's layer.

### Phase C — the issuer page

| # | change | files | data |
|---|---|---|---|
| ① | Header: identity line (`exchange · CIK behind AuditOnly · fiscal year ends <fiscal.fiscal_year_ends> · forms held`), then `IssuerFreshness`: filed to · figures computed · priced to · brief written — four dates already fetched (`snapshot.latest_filing`, `financials.as_of`, `price-index` last point, `latest-brief.created_at`) | new `components/issuer/IssuerFreshness.tsx`, `issuer/[ticker]/page.tsx` | existing |
| ② | `InBook` strip, one card row: market value (stored quantity · cost in the caption), weight + Δ vs prev update, day + contribution to the book's day, the issuer's own check as a meter with `room_*`, the weight sparkline across updates, `Open the alert` / `Back to the book`; rendered only when `?portfolio=` is present | new `components/issuer/InBook.tsx` | A5, A1 (the one name's series), A2 |
| ③ | `PriceVsBenchmark`: span control (`spans`), benchmark select (SPY, the factor ETFs from the correlation window, the book's other holdings), a second marker kind `brief` drawn dashed teal, the six `return_*` recipe rows as chips under the legend with "to <as_of>"; a filing rule click sets the Filings tab to that filing | `components/issuer/panels.tsx`, `line.tsx` (`markers[].kind?: "filing"\|"brief"`) | A4; `financials` rows |
| ④ | **`Financials`**: `MeasureList` (three groups from A8, latest value and reach per row, kind filter `All / Flows / Balances`) + `FinancialChart`: **a line** for the chosen measure; views per `views[]` — `level` (a flow: `/windows` 3- or 12-month slots as one line, derived windows drawn as hollow markers, unreachable slots as a gap; a ratio: `/panel-series`; a balance: `/balance-series`), `yoy` (`/panel-series?metrics=<yoy_metric>`), `share` (`/panel-series?metrics=<share_metric>`), `windows` (a link to the ladder in the Financials tab); a `3 months / 12 months` control on flows; every point opens its facts or its calc; Table lists the points with their ids behind `AuditOnly` | new `components/issuer/Financials.tsx`, `lib/charts.ts` (`Measures`, `BalanceSeries`, `getMeasures`, `getBalanceSeries`) | A7, A8, existing |
| ⑤ | `BriefShort` on the Overview: first paragraph of `financial_summary` through `AnswerText`, `figures as of <created_at>` tag, `Read the brief →` | `issuer/[ticker]/page.tsx` | existing |
| ⑥ | Evidence cards draw a series: `calc` with `result.points` and `fact_record` with `points` get a `LineChart` (last value labelled) above the fields; the point list moves under Technical details | `components/evidence/cards.tsx` | existing |
| — | Brief tab: `Briefs for <ticker>` strip from A6; `market_context` carries the `as of` tag; External sources split into *Cited by the brief* / *Retrieved, not cited* by `brief.citations ∩ src_ ids` | `issuer/[ticker]/page.tsx` `BriefTab` | A6 |
| — | Financials tab: the ladder receives `today` (the prop exists, `grids.tsx:117`, never passed); Coverage rows clickable → ladder metric; kind filter; **Baseline measures** table retired (its rows and calc ids are the picker's ratios group) — §7 D3 | `issuer/[ticker]/page.tsx` `FinancialsTab` | existing |

Removed from the Overview: the `Margins` card, the coverage table. Both live
on as views of ④ (`share` on the three P&L lines; the list itself).

Done when: `/issuer/MSFT?portfolio=port_001` shows the strip with weight
`16.25%` equal to `run_aacdb498c66f`'s row; choosing `Net income` then
`Share of revenue` draws the same line the retired Margins card drew for net
margin, from the same calc id; `/issuer/MSFT` without `?portfolio=` shows no
strip and no "in this book" figure anywhere; the brief's `market_context`
carries its date.

### Phase D — acceptance and documents

- `scripts/smoke_ui.py`: the id-absence sweep runs over `/`, `/issuer/MSFT`
  and `/issuer/MSFT?portfolio=<demo>` with the audit switch off, then on;
  three DOM assertions added — the composition row has as many `circle`
  marks per name as `updates.length`; the Financials chart is one `path`
  after a list click; the strip is absent without `?portfolio=`.
- `apps/web/README.md` layout block: the new components and the three new
  reads.
- `docs/ARCHITECTURE_AS_BUILT.md` §9 F4 (发行人页 tab 的说法) and §12 (one
  line for V25).
- `dev_note/topics/exposure-workbench.md` via the wrapup skill.

## §5 Tests, named before the code

| file | pins |
|---|---|
| `tests/test_v25_reads.py` (offline) | `collapse_by_date` picks the latest `completed_at` per date and counts the rest; `weight_change_vs_prev` is None on the first update and when the name was absent before; `room_*` sign convention (over the tier is negative); `measures.views` follows kind + manifest + `_MARGIN_NUMERATORS`; `snapshot` handler source contains no `IssuerExposure` query without a `run_id` bound; `spans` equals each file's `_SPANS`; the run-series and measures handlers reference no recording entry point (`_record`, `record_`, `cs.` — the `test_a_read_does_not_go_through_the_recording_entry_point` pattern); balance-series calls `find_recorded` before any mint and its lookup keys ⊆ the recorder's params |
| `tests/test_route_reachability.py` | unchanged; covers `/briefs`, `/measures`, `/balance-series`, `/run-series` on registration |
| `tests/test_v25_reads_live.py` (`pytest.mark.live`) | three reads of each new endpoint leave `calc_ledger` unchanged (the `test_v13_issuer_panels_live` shape); run-series' last update equals `GET /exposure-runs/{run_id}` metrics to 8 places; `measures.flows[revenue].latest.value` equals the last 3-month slot of `/windows?metric=revenue`; `snapshot?portfolio=port_001` weight equals the run's row; `/issuers/MSFT/briefs` length equals `count(*) from issuer_briefs` for MSFT |
| `apps/web/tests/runSeries.test.ts` | the Δ label rule ("vs Sep 2" when the prior update is a different day); the sort comparator over nullable columns (null last, stable); the focus reducer (setting a ticker clears a factor) |
| `apps/web/tests/financials.test.ts` | view list → control state (a measure with no `yoy` disables the button rather than hiding it); a flow's level series from `/windows` slots keeps unreachable slots as gaps, derived as hollow; unit formatting goes through `lib/display` for `MONEY`, `RATIO`, `MULTIPLE` |
| `tsc`, `next build`, `vitest run` | the wire shapes and the components agree |
| `scripts/smoke_ui.py` | §4 D |

## §6 Sizes and where the time goes

| piece | new lines (est.) | risk |
|---|---|---|
| A1 run-series (service + route + tests) | ~180 | dedupe and Δ rules; the only endpoint with logic |
| A8 measures (service + route + tests) | ~160 | `views` derivation; latest-quarter for a flow whose newest filed window is a 9-month YTD (§10) |
| A2–A7 | ~120 | A5 deletes a query; A7 is the reuse pattern copied |
| B ① + multiples + TierBars per-row | ~320 | calendar-time x-axis with gaps |
| B ③ ④ ⑤ ⑦ ⑥ | ~380 | brush is the largest single change to `LineChart` |
| C ④ Financials panel | ~360 | the only new panel with state (measure × view × window) |
| C ① ② ③ ⑤ ⑥ + tabs | ~340 | — |
| D | ~120 | — |

About 2,000 lines, ~700 of them tests; no migration, no new table, no
workflow change, no model prompt change.

## §7 Decisions for the boss

- **D1 · Δ column source.** As planned: from stored weights in A1. The
  alternative — writing `issuer_exposures.weight_change` in the workflow — is a
  run-time change and is not in this batch.
- **D2 · Ratios in the picker.** *Decided 2026-09-06: both doors stay, and they
  now point at each other.* The three margins appear both as rows under *Ratios*
  and as the `share` view of gross profit / operating income / net income, and
  both resolve to one ledger row (`calc_2f9eba710a99` for net margin on MSFT).
  Keeping only the Ratios row would cost the flow its follow-up question
  ("this $31.78B — how much of revenue is that?"); keeping only the share view
  would take `net_margin` out of the list that is meant to be the inventory of
  what this desk holds, while briefs go on citing it. What was actually wrong
  was never the second door: the share view was headed "Net income as a share of
  revenue", four words that never say "Net margin", so a reader arriving by each
  door could not tell one calculation from two. See §13.
- **D3 · Retire the Baseline measures table** from the Financials tab. Its
  16 rows are the picker's ratios and the returns strip, same calc ids.
  Planned: retire. The ladder and How assembled stay.
- **D4 · Brush is a view.** It narrows what is drawn; it computes nothing and
  minting a calc for a brushed window is out of scope. A reader who wants the
  window's figures asks (`Explain`), which is the recorded path.
- **D5 · Inline series in the dock fetch lazily** from `/evidence/{id}`
  rather than storing points in every `FactFill`. Old answers draw too; a
  17-series answer makes 17 small reads only when scrolled into view.
- **D6 · Benchmark list** on the price chart: SPY, the seven factor ETFs, and
  the book's holdings when `?portfolio=` is present. Anything the desk prices
  is accepted by the endpoint already; this is what the select offers.
- **D7 · Order of B and C.** Either first; the review's order was book then
  issuer.

## §8 Out of scope, on purpose

The scenario drawer over `book.sell` / `book.buy` (tier two, its own batch:
a write path through the wrapper, a `Scenarios` list for the book);
run-to-run diff; the mandate editor (a write path over `risk_limits`, append
only); VaR / ES release, historical-replay stress, rolling betas, risk
contribution (tier three, each a new method in `methods.py` with tests
first); dated position snapshots (the value path's honesty problem); writing
issuer `weight_change` in the workflow (D1).

## §9 What is measured before and after

| | before | after |
|---|---|---|
| runs a reader can see at once on the book page | 1 | 12 dated updates (all of `port_001`'s) |
| stored columns never on the wire | `issuer_exposures.contribution` | none |
| measures of an issuer with a chart | 3 (margins) | every flow, ratio and balance the desk holds (37 for MSFT) |
| endpoints typed and never called | 1 (`/reconcile`) | 0 |
| hard-coded windows on the client | 2 (`3y`, `1y`) | 0 |
| ledger rows added by a page view | 0 | 0 |
| ids in the reader's layer | 0 | 0 |

## §10 Risks named

1. **Run-series size.** A book updated daily for a year is ~250 updates ×
   (issuers + sectors + checks) rows. `span` bounds it; `all` is opt-in. If
   a single response passes ~400 KB, paginate by date range — not by row.
2. **A flow with no derivable latest quarter.** An issuer whose newest
   filing states a 9-month window and no third-quarter boundary has an
   unreachable latest 3-month slot. `measures.latest` is then the
   `unreachable` reason, the row says so, and Level draws the gap — the
   engine's finding, as `/windows` already shows it. Never the 9-month figure
   in the quarter's place.
3. **The strip wraps** when the evidence column is open at 1440 px. It wraps
   at the cell boundary by design; it does not truncate.
4. **`contribution` reads as two things.** On the wire it is yesterday's
   weight × the name's return (`pnl.py:154`); the page always labels it
   "of the book's day" and never alone.
5. **Brief history is RLS-scoped**: a signed-out reader sees public briefs
   only. The strip lists what the session can see and prints no total; a
   total would need an unscoped count, which nothing here may run.
6. **Snapshot without `?portfolio=`** loses the "in this book" line for
   readers who type a URL. That is the correct loss: the line was showing
   another book's row.

## §11 Sources

- Interaction review, 2026-09-05: <https://claude.ai/code/artifact/d8f71c0b-cfba-4ca8-8ac1-e1f9737523ea>
- Book Page, Tier One (mockup): <https://claude.ai/code/artifact/748db52a-b8b9-46eb-8eeb-be89482f51c4>
- Issuer Page, Second Draft (mockup): <https://claude.ai/code/artifact/9ff0e6be-99ae-44d7-abaa-db1b11e69d67>
  (the Financials panel there draws bars; §0.1 changes it to a line — the list, views and controls stand)
- Issuer Page, first draft, superseded: <https://claude.ai/code/artifact/466912dd-79a6-441f-b83a-708d25775873>

## §12 What the build found, and what it changed (2026-09-05)

Written after the fact, from the work rather than from the plan.

### Two defects this batch did not set out to fix, and had to

**D-1 · The ladder's slot key was never the wire's key.** `WindowSlot` was
typed `end: string`; `fundamentals_service._slot` has always written
`period_end` (`analytics/units.POINT_PERIOD_KEY`). So `s.end` was `undefined`
on every slot the API has ever returned: `WindowLadder` positioned its bars at
`NaN` and its year axis threw on `undefined.slice(0, 4)`. TypeScript cannot
catch this — JSON arrives as `any` — and the offline guards read the handler,
not the shape. The Financials panel's Level view hit it on its first render.

Fixed in the five readers (`lib/charts.ts`, `charts/grids.tsx`,
`issuer/panels.tsx`, `lib/measures.ts`, the test fixture), and pinned by
`test_v25_reads.py::test_the_ladders_slot_type_names_the_key_the_server_sends`,
which reads `units.POINT_PERIOD_KEY` and the `.ts` type together. `fmtMonth` is
now guarded like `fmtDate` beside it: a formatter that throws on a missing date
takes the page down, and the guard on `fmtDate` was earned the same way.

**D-2 · `find_recorded` was not scoped to an issuer.** It matched on operation
and params containment alone. A balance series records `{metric, last_n, ...}`
and puts the ticker in the row's own `company_id` column, so a lookup for
MSFT's long-term debt matched AAPL's row of the same metric — the same class of
miss as a proper subset, arriving from the other side. `company_ticker` is now
an optional argument; operations whose subject is not an issuer (reconcile, the
drawdown scan) pass nothing and are unaffected.

### Three things built that the plan did not name

- **`balance_points` split out of `get_balance_series`.** A7 could not "look
  the calculation up first" while the only entry point recorded — the shape
  `/reconcile` learned in V13-S5. The read is now a function that writes
  nothing (not a ledger row, not an absence row) and the recorder calls it.
  `get_balance_series` also records `through` now, so the lookup key can name
  which series it wants.
- **The rail on the issuer page reads the run, not the position rows.**
  `positions.market_value` is a snapshot column (the demo book's is dated Jul
  23) and the strip beside it reads the run's own issuer rows (Sep 3). One
  screen carried MSFT at $1.33M in the rail and $1.79M three inches right, both
  true of different days and neither saying which.
- **The book rail shows the time on a day that ran more than once.** Five rows
  reading "Sep 3, 2026" is five different runs that looks like one run listed
  five times — the same collapsing `run-series` performs, said the other way
  round, because on that rail a run IS the thing being picked.

### Where the plan was wrong about its own tests

`test_v13_issuer_panels.py` sliced a handler's source from its `async def` to
the section comment that followed. A7 and A8 were added between `panel_series`
and that comment, so the slice swallowed them and the guard failed on a minting
call in a different handler — one whose own test says it must be there. The
slice is now bounded by the next `@router.` decorator, which does not move when
a neighbour is added, and `measures` joined the parametrisation rather than
being excused from it.

### Decisions taken by default (§7 stands, unanswered)

D1, D2, D3, D5 and D6 were built as planned; D4 (the brush computes nothing)
and D7 (book before issuer) needed no decision in the end. **D2 in
particular — the three margins appearing both as ratios and as the `share` view
of their numerators — is live and still worth a second opinion.**

### Not done, and named

`scripts/smoke_ui.py` has the three new DOM assertions and has not been run
against a deploy — the local web container serves the page and the API on two
ports, and the script needs one origin. The `share` and `yoy` views are
exercised over HTTP for MSFT only
(`test_every_view_a_measure_offers_answers`); an issuer whose recipe lacks
them is covered by the offline derivation test and not by a browser.

## §13 D2 as built — the two doors name each other (2026-09-06)

`lib/measures.linkedRatio` is the whole rule, and it is a pure function so the
rule can be stated in a test rather than inferred from a render. Given the
selected measure, the current view and the issuer's ratio rows, it answers:
*which ledger row is this chart actually drawing?* Null on every view but
`share`, null on a flow with no margin, null when the recipe did not compute
that margin for this issuer, and null in the other direction — standing on Net
margin, knowing you could also have arrived from Net income does not help.

Where its answer goes, in three places:

| surface | before | after |
|---|---|---|
| chart title | `Net income as a share of revenue` | `Net margin` |
| beside it | — | `net income ÷ revenue` |
| under it | — | `The same row as Ratios → Net margin — one calculation, reached from either side.` |
| the list | nothing | the `Net margin` row lights (teal ring) and reads *the row the chart is drawing — you are looking at it from Flows*, and scrolls itself into view |

Five cases pinned in `apps/web/tests/financials.test.ts`. No API change; the
`share_metric` field the server has been sending since A8 is what carries it.

The discipline this settles, stated once so the next batch inherits it: **one
figure, one source — not one figure, one door.** `find_recorded` reusing a
calculation and the reconcile line asserting an identity are the same rule.
Two entrances do not break it. Two names that do not acknowledge each other do.

## §14 A defect the picker made visible (2026-09-06)

Not in this plan's scope, found by looking at the panel §13 had just changed,
and fixed on the boss's word.

**The reading.** `Current ratio 128.3%` and `Cash ÷ long-term debt 102.2%` in
the measure list. A current ratio is `1.28×`. Not a page problem:
`analytics/display_conventions.display` is the one rule the server and
`lib/display.ts` share, so an answer or a brief citing either figure printed a
percent too.

**Why.** money ÷ money is a `RATIO` to the unit algebra and can be nothing
else — net margin and current ratio are the same operation on the same units —
so which of the two dimensionless readings a named measure has must be
DECLARED. `analytics/formulas.py` has declared `current_ratio` a multiple since
V17. `services/recipe.ratio()` never asked.

**Why V17's migration did not already fix it.** It lists `current_ratio` among
its eight. It keyed on `params.result_type.quantity`, and the standard recipe
passes no `as_quantity`: 61 of this desk's 87 `calc.series.divide` rows carry a
null quantity. The rows that migration was written for were invisible to it,
and `test_v9_formulas.py`'s eight-measure guard went on passing, because the
registry was right the whole time. Nothing was going to surface this except a
reader looking at the number — which is what the picker made possible.

**The fix, in three parts.**

1. `recipe._reading_of(label)` takes the reading from the registry, and only
   when it is dimensionless: declaring `money` on a quotient is not a reading
   of it, `units.refine` would refuse, and a producer must not be able to turn
   a correct calculation into a refusal by consulting a table.
   `cash_to_long_term_debt_noncurrent` is stated at its call site, because it is
   not in the registry — it is a label this recipe composes and nothing
   evaluates by name, and adding it to `FORMULAS` would make it a formula the
   agent can ask for, a wider claim than "this quotient reads as a multiple".
2. `infra/migrations/v25_recipe_multiple.sql` — 23 rows (12 current_ratio
   across 8 issuers, 11 cash÷debt across 7), found through the recipe's own
   manifest, which is the only handle these anonymous rows have. Both places
   set, column and JSONB, for the reason `v15_calc_unit.sql` introduced the
   column. No value, operand, basis, input ref or period touched: an UPDATE on
   an append-only ledger that stays one. Applied locally; idempotent (a second
   run reported `UPDATE 0`). Named in `docs/PRODUCTION.md`, which its own guard
   required.
3. `test_v25_reads.py` gains the guard that would have caught it: every
   quotient the recipe computes whose registry family is liquidity, leverage,
   coverage or turnover must read as a multiple — checked against the family,
   not against a list of names, so a ninth such measure is covered on arrival.

**Left standing, and named so it is not rediscovered.** The recipe's series
rows record no `result_type.quantity`. It is why V17 missed them and why this
migration had to go through the manifest. Naming them changes how the model's
table refers to those rows, which is the agent path and not this batch.