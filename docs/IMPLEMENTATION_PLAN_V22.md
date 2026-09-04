# V22 — the book's figures enter the algebra; the panel is the algebra; a sale is a primitive

Status: **as built** (2026-09-04). The batch answers the conversation
battery's central finding (docs/spikes/V21_CONVERSATIONS.md §2, §5): the desk
had two worlds of values and one algebra. An issuer's figures (fact_, calc_)
had operators, methods as data, and a refusal that reached the trace when a
method was missing; the book's figures (a run's weights, market values, limit
levels, net betas) had none of the three — readable, citable, terminal. The
boss's decision, after the analysis of 2026-09-04: no bare calculator; extend
the typed algebra to the book's quantities; make `get_portfolio_analysis` a
panel OVER the algebra and pin it with parity; add one scenario primitive.

Nothing here is a prompt rule, a fallback, or a function per question. Each
item is a module that makes a class of answer reachable, or a class of error
unwritable, and every one was measured against the live database before the
rebuild (docs/spikes/V22_COVERAGE.md).

## S1 — a named figure on a row is a typed operand

**Feature.** `calculate`, `rank`, `scale` (`services/typed_calculator.py`).

**Gap.** `_resolve` accepted `fact_` and `calc_` ids only. C01#t1 handed
`rank` ten `run_…:issuer_exposures.<T>.weight` refs and was refused
`unknown_operand`; C12#t2 could state a weight and a limit and not the
dollars between them.

**Built.** An operand may be `ref:name` — the first colon is the boundary,
because names hold dots and labels hold colons (`limit_checks.
issuer_concentration:MSFT.current_value`). The VALUE and UNIT come from the
one namer every reader uses (`quantities.of_ref`), so the figure the
calculator combines is the figure the table shows and the gate resolves. What
`_resolve_named` adds is the AS-OF (the run's date) and one new axis on
`Typed`: the **base** — the book the figure is a figure of (a run id, or a
scenario row's id; an analysis row's base is the run it analysed). The row
label is the entity (`issuers`), so `rank` labels the holdings and the
double-count rules tell two rows of one run apart. A collinear coefficient
(`not_alone`) is refused as an operand, the projection the table already
applies.

The rules the base adds, in `_book_rule`, first in `_check`:

| combination | verdict |
|---|---|
| two books' figures summed or multiplied | `different_books` |
| a book's figure summed or differenced with a filed figure | `mixed_worlds` |
| a share of the book × money that is not the book's | `mixed_worlds` |
| two books' figures differenced | allowed — the change between them, a figure of neither |
| two books' figures divided | allowed — a ratio that says which two |
| a share of the book × an issuer's ratio | allowed — the weighted margin, still of the book |
| neither operand has a base | untouched: every pre-V22 combination is as it was |

Results carry the base (`result_type.base`) and read it back; `scale` and
`rank` carry it too. A named figure on a calculator row that holds ONE figure
resolves as the bare row (live turn 2 wrote `calc_…:<its quantity>`, as the
table had shown it), and a calculator row of the book dates and bases itself
from its own `result_type` when it has no run behind it. A row whose result_type names a base is grouped
`book_derived` on the legend (a new key in `resources.GROUP_QUESTIONS`) —
`dollars_to_sell` is not a filed figure and not a formula's measure.

**Effect.** (current − warning) × market value is two calls over four figures
the run holds; MSFT's weight after NVDA leaves is one subtraction and one
division; the holdings rank by weight with a place per name.

## S2 — the panel is the algebra, pinned

**Feature.** `get_portfolio_analysis` (`services/integration_service.py`).

**Gap.** Its derived quantities (net betas, room to each tier) were recorded
as labelled lists on one row with no `value` and no `result_type`, so the
calculator refused them as `untyped_operand` — with a sentence saying the row
predated typed quantities, which was false of a row written that day.

**Built.** The row states its own type: `params.result_type = {unit_class:
ratio, base: run_id, basis: {instant: as_of}}` and `params.as_of`, beside the
unchanged two-key identifying set `find_recorded` matches on. Each named
figure on it is now an operand (`calc_…:portfolio.integration.room_to_breach.
<check>`), typed from the row and not from a rule about the operation's name
(`LEGACY_RATIO_OPS` still lists the op for rows written before). The panel
keeps computing through the same pure functions (`analytics/integration.py`)
and stays one row per call — it exists to save calls — and PARITY is what
makes it a panel over the algebra rather than a second arithmetic:
`test_v22_book_algebra` proves headroom equals `calculate(subtract)` on the
same four figures and net beta equals `scale` (the sense, data) then `add`
over the same legs; the live database agrees on all twenty checks of the
latest run (§V22_COVERAGE).

**Effect.** A distance on the panel times the book's market value is the
dollars of room; nothing on the panel is terminal any more.

## S3 — one scenario primitive

**Feature.** `hypothetical_book(run_id, sales)` — `analytics/scenario.py`
(pure), `services/scenario_service.py`, on the meta face only.

**Gap.** "Say I sell the one you landed on: where does that leave
concentration?" is nine renormalisations and a limit pass over a book that
does not exist. The evidence stores what IS; stress, the one scenario
machinery, is withheld (V20). C01#t3 died eight refusals deep.

**Built.** One parametric entry, not a derivation per question: sell all or a
fraction of any names; the proceeds leave the book (no cash line is
invented); every remaining weight is its market value over the remaining
book's; sector weights follow; the portfolio's own thresholds are re-applied
through the same engine the workflow uses (`check_limits`, with the risk,
stress and P&L inputs absent — so the concentration and exposure checks run
and `checks_not_run` names the two that cannot). Factor exposures are stated
unmeasured, never carried: a beta is a regression over a history the new book
does not have. Refused: a name not held, a fraction outside (0, 1], a name
sold twice, a sale that empties the book, an unpriced holding.

The result is ONE ledger row (`book.scenario`) whose result mirrors a run's
tables, and `quantities._from_scenario` publishes it under a RUN's names with
a run's units, read from the one declaration (`resources.RUN_CHILDREN` — the
scenario writer may only write columns the declaration names; pinned).
So a slot that works on a run works on the book-after-the-sale unchanged;
`read_quantities` reads it like a run; the calculator resolves
`calc_…:issuer_exposures.MSFT.weight` on it with the row itself as the base;
scenario weight − run weight is the change the sale makes and their sum is
`different_books`. Because the names are the run's, the row carries a SUBJECT
(`after_sale_of_NVDA`) that the renderer prefixes into derived table labels,
so a before/after table's columns say which book each is (live turn 1 had
shown two columns both headed `issuer exposures weight`).

**Effect.** C01#t3 is one call and a table; "would trimming Y clear the
warning" is one call with a fraction.

## What the model is told

`calculate`, `rank`, `get_portfolio_analysis` and `describe_run.how_to_read`
say the `ref:name` grammar where the model reads it; `_FACE_CAPABILITIES.can`
gains two lines (the book's own arithmetic; the book after a sale);
`hypothetical_book` carries its own description. `_SYSTEM` is unchanged: its
"a superlative is a rank call FIRST" is true of the book now, where before
`rank` could not serve it (V21_CONVERSATIONS §5). Wording of the new tool
descriptions is for the boss's review, as every batch's is.

## Not done, on purpose

- No bare calculator: an operand without a type is refused, as before.
- No per-quantity ledger rows from the panel (fifty rows per
  `describe_run`); one row, self-typed, with parity pinned instead.
- No cash line in a scenario, no re-fit of betas, no split of a sale across
  dates: the scenario is the book at the run's date with less in it.
- `_SYSTEM` untouched; `so_what` (V21_CONVERSATIONS §6) remains the boss's
  product decision.
- The ten-name budget question (V21_COVERAGE §3) is untouched; a scenario is
  one call, which is the largest single saving this batch makes on it.
