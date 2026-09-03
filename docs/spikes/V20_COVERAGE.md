# V20 coverage — what the desk computes and does not publish

Date: 2026-09-02. Plan: `docs/IMPLEMENTATION_PLAN_V20.md`. Module note: MODULE_NOTES §M22.
Wording: `docs/spikes/V19_WORDING_REVIEW.md` §12–15.

## §1 The audit (code read, tests listed, latest live run's numbers)

Criterion: keep = a named industry-standard method AND a value pinned by a
test AND inputs free of a known defect; otherwise withhold.

| measure (where) | method | value test | verdict |
|---|---|---|---|
| market value, weights, sector/issuer concentration | accounting identities, last close on or before the run date | yes | keep + ⓘ |
| day P&L, day return | adjusted return × previous-session MV (splits/dividends tested) | yes | keep + ⓘ |
| value path, drawdown, episodes | fixed quantities revalued daily; running-maximum drawdown | yes (episodes reproduce max drawdown) | keep + ⓘ |
| 30/60-day volatility | sample std ddof=1 × √252 | single-name yes; **portfolio: none until V20** | keep + ⓘ; test added |
| VaR 95% 1d, ES 95% | historical simulation, ~830 equal-weighted returns, k = ⌊0.05n⌋-th smallest | **none** | **withhold** |
| attribution: total, residual, by holding | one OLS on 8 ETF factors, 750 obs, intercept | yes (beta recovery, additivity) | keep + ⓘ |
| factor betas panel (individual β) | same | yes | **withhold when collinear** (live: VIF 17.9, `collinear=true`) |
| factor correlations | Pearson | yes | keep + ⓘ |
| stress: 5 scenarios | hand-written shocks × betas, linear, unshocked factors at 0 | direction only | **withhold** |
| mandate checks | threshold comparison | yes | keep daily_loss / gross_exposure / sector / issuer; **withhold** var_95 / ES / stress_loss checks |
| issuer page windows, formulas, margins | total-return windows; formula registry | yes | keep |
| single-name tools (vol, beta, momentum 12-1, 52w, ADV) | see price_analytics_service `basis` | yes (hand / constructed) | keep |

Latest live run before V20 (2026-09-01): VaR 1.39%, ES 1.99%, vol30 13.0%,
max drawdown 17.7%, R² 0.81, max VIF 17.9, collinear, 750 observations.

## §2 What was built

One declaration (`analytics/withheld.py`), nine readers derived from it; the
workflow unchanged (computes, stores). `^VIX` out of the factor set. Method
statements in `analytics/methods.py`, served as `methods`, rendered behind an
ⓘ. Betas nulled by the API under the collinearity flag.

## §3 Residuals

- The withheld measures are not deleted; the day they are validated the
  release is an edit to `withheld.py` (release conditions in its docstring).
- Removing `^VIX` changes the next run's regression (7 factors). Stored
  attributions from 8-factor runs stay as they were.
- `positions.quantity` is still not split-adjusted (V5 §5); the ⓘ on the
  value path says "fixed quantities" and does not say this.

## §4 Suite and deploy

Offline: 1973 → **1986** (`tests/test_v20_withheld.py`, 15 cases; four older
tests turned around, each saying which property it now pins).

Live, on the deployed stack (public API, demo book `run_690a3a2db838`):

- `GET /exposure-runs/{id}`: metric keys are the ten published ones (no
  `var_95_1d`, `expected_shortfall_95`, `stress_loss_*`); `withheld` sentence
  present; `methods` carries eight statements; every `beta` is `null` (the run
  is collinear); no stress-type alert.
- `GET /exposure-runs/{id}/stress`: `{"scenarios": [], "withheld": "…unsourced
  and propagate through individually collinear betas"}`.
- `GET /exposure-runs/{id}/limit-book`: 20 checks in three groups (Portfolio,
  Sector, Issuer); the Stress group is gone.
- `GET /portfolios/port_001/limits`: five types; `var_95`,
  `expected_shortfall_95`, `stress_loss` rows are not shown as in force.
- The page renders (200); no VaR tile, no "If the market broke", no factor
  betas panel; ⓘ on the value path, attribution and correlation cards.

The agent, asked "What is the book's 1-day 95% VaR, and how much would a 10%
market drop cost us?" — four turns, each after a rebuild:

| turn | answer | what changed |
|---|---|---|
| 1 | "VaR unavailable because this run does not hold a quantity by that name"; then **estimated the drop as a tenth of market value** | the withheld sentence was only on `get_risk_state`, which the turn never called |
| 2 | same | (rebuild had not picked up the edit) |
| 3 | VaR "withheld pending validation"; then quoted **7.40%** "as the published proxy" and a 6.00% stress limit | `snapshot_all` still served `stress_loss_market`, and alerts/checks raised by withheld checks on runs before V20 reached every reader |
| 4 | "VaR … withheld pending validation. For a ten percent market drop, the desk does not publish a cost estimate on this run" | `published_alerts` / `published_checks` filters on all eight alert/check readers; the sentence on the snapshot, the manifest and the capability statement |

A fifth turn, after the commit: "Which limits am I closest to breaching" ranked
`stress loss:market downside 92.5%` first — the table itself
(`quantities._from_run`) read every alert and check row of the run, so an
alert a withheld check raised on an older run was still citable. Twelfth
reader; filtered at the table now, and pinned.

The suggested questions in the chat dock were re-verified on the final stack
and replaced: the book gets the largest exposure, why the book moved, the
limits and their room, and a three-issuer net-income table; an issuer page
gets net debt, four-quarter revenue growth, and a web search for the week's
news. "Rank the positions" and "share count shrink" were tried and are not
suggested: the first fails when the rank tool is asked for run rows, the
second wrote `{ref}` into its text.

"Why did the book move on the last run?" — one of the new default questions —
answered with "75000.0% observations over a 75000.0%-day window": the two
counts had been declared RATIO since V8-P1 (a written COUNT was allowed to
meet a stored RATIO, so they verified; they just displayed as percentages).
Declared COUNT now, and the table reads COUNT columns as a third kind.

The lesson is the same as V19's: a decision made in one module is only as
complete as the list of readers, and the list was found by asking the model,
not by grepping — the grep found nine, the model found the tenth and the
eleventh.

Live suite: **262 passed** (1:50) against the final stack. Four live tests turned around: `test_quantities` repins the real run at 193 quantities (235 minus the withheld metrics, the stress table and the stress checks) and 161 shown; the faithfulness replay gained a `withheld` class — 17 of the 27 refusals that appeared were pre-V20 answers quoting VaR, a stress loss, or a count over alerts/checks that the withheld rows no longer contribute to, and the ceiling of 9 classified refusals holds.
