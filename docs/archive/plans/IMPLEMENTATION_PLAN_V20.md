# V20 — what the desk computes and does not publish

Status: **as built** (2026-09-02). Ordered by the boss after the 9/2 quant audit:
"hide what is not robust or not tested; keep what is industry-standard, with an
ⓘ stating the method; the switch is not in the UI; the wording is English."

## The audit's verdicts (docs/spikes/V20_COVERAGE.md §1 has the table)

Kept, with an ⓘ: market value and concentration; day P&L; the value path and
its drawdown; 30/60-day volatility; the one-regression attribution (total,
residual, by holding) and the factor correlations; the mandate checks on
daily loss, gross exposure, sector and issuer concentration; the single-name
tools (vol, beta, momentum 12-1, 52-week distance, ADV).

Withheld: VaR 95% and expected shortfall (no value test, undocumented quantile
convention, no backtest); the stress scenarios and the four stress losses
(unsourced shock sizes, three of five scenarios lean on individually collinear
betas, unshocked factors held at zero); individual factor betas when the run
is collinear (VIF 17.9 on the live book). `^VIX` leaves the factor set (an
index level, not a return).

## The switch

`analytics/withheld.py` is the one declaration: `WITHHELD_METRICS`,
`WITHHELD_TABLES`, `WITHHELD_CHECKS`, `WITHHELD_GROUPS`, each with the reason
that is also the release condition. Derived from it:

- `resources.RUN_CHILDREN` / `RUN_GROUPS` (the table, the manifest, the gate)
  are `_DECLARED` minus withheld — so the model cannot name a withheld
  quantity and `describe_run` does not list it;
- `limits.check_limits` does not evaluate a withheld check (no alert, no
  record, no `evaluated` key); the limit rows stay;
- `run_reads_service.get_risk_state` / `list_risk_limits`,
  `integration_service.get_portfolio_analysis`, the daily-report input, the
  run evidence card, and the three API surfaces (`GET /exposure-runs/{id}`,
  `/stress`, `/portfolios/{id}` dashboard and `/limits`) read the same module;
- every payload that dropped a measure carries `withheld`, the sentence naming
  the state — a payload that simply lacked VaR would read as a book with no
  tail measure.

The workflow still computes and stores everything. Release = edit withheld.py.

## The ⓘ

`analytics/methods.py` holds one English statement per published measure,
quoting the code's own constants (ddof=1, √252, VIF 5); the run and history
endpoints serve it as `methods`, and the page renders it behind an ⓘ
(`MethodInfo` in charts/frame.tsx). No method string is written in a component
any more (test pins `basis="` out of sections.tsx).

## Factor betas

Server-side: `GET /exposure-runs/{id}` nulls every `beta` when
`metrics.collinear` — the same flag under which the table projects them off
the model's view (V11-F) — and the page draws the betas panel only when a beta
exists. Contributions, the sum, and the correlations stay.
