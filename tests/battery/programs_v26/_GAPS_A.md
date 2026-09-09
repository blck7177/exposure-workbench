# Gaps found writing the ideal programs — slice A

Slice: W01-stop-sweep-across-book, W02-book-as-one-company, W03-vs-the-index, W05-paid-for-the-vol,
W06-weight-we-chose, L01–L06, F01, F02, F04, F06, W01-back-to-flat, W02-per-point-of-weight,
W03-did-the-hedge-hedge, W04-sectors-or-names. All programs run on exposure_gold with `refused: []`;
the only refusals left are entry-level data absences inside vectors (JPM bank refusal, LLY/XOM no
operating_income line, TLT/HYG no issuer accounts, TLT self_regression on its own benchmark).

Note: mid-task the executor gained `column(run=$explain, table="holdings", …)`, `pick` of payload
fields as literals for `params`, and dated episode/explain figures; gaps 1–3 below were closed by
that and are recorded only so the earlier partial designs are understood. Gaps 4–12 remain.

## Closed during the task (V30 executor update of 2026-09-09 03:31)
1. `book.explain_episode` per-holding returns unreachable → now `column(…, "holdings", "window_return")`.
2. `book.explain_episode` / `book.drawdown_episodes` figures undated (`undated_operand` on pick/arith) → now dated.
3. Episode dates unreachable → `pick(of=$ep, key="episodes[0].peak_date")` gives a literal that feeds `params`.

## Open

4. **Book minus market is refused (`mixed_worlds`), only the ratio is allowed.**
   Needs: W03-vs-the-index t2, W05 t2 (excess return = book return − SPY return over the same dates).
   Tried: `sub(pick($explain,"portfolio.window_return"), <SPY return built from prices/at>)` and
   `sub(book_ret_1y, method price.window_return SPY)`.
   Refusal: `mixed_worlds: … is a filed figure and the other operand is a figure of the book … cannot be
   summed or differenced. Multiply … or divide`. `div` of the same pair settles. An excess return over
   the market is a legitimate desk quantity; the calculator's world rule treats SPY's return as an
   issuer's account. Programs use `div` (ret_ratio_*) and the note says the excess is read off two figures.

5. **A literal picked from a payload feeds only method `params`, not `at`.**
   Needs: F06 t1/t2, W01-back-to-flat t3, W03-hedge t1/t2 — SPY's return over the book's episode dates.
   Tried: `{"fn":"at","of":"$spy_px","period":"$peak"}` with `peak = pick($episodes,"episodes[0].peak_date")`.
   Refusal: `unknown_point: $spy holds no point at Node(name='peak', …)` (the Node object is passed
   through instead of its literal). Programs hard-code the dates read from the episodes payload.

6. **Episode durations are literals, not figures.** `episodes[i].trough_days` / `recovery_days` come
   back as literal nodes and `column($ep, "episodes", col)` refuses (`$ep holds no column
   episodes.<label>.depth`, tables: portfolio, quality_flags). Needs: W01-back-to-flat t2 (sum of
   sessions under water = 55+24+18+13 = 110 of 253) — done in prose. A per-episode column
   (`episodes.<i>.{depth,trough_days,recovery_days}`) would make it a `sum` node.

7. **A share-of-sum vector cannot be ranked.** `rank(div($wv, sum($wv)))` →
   `indistinguishable_operands: each entry in an ordering must be one figure of one issuer … got ['?', …]`.
   Needs: F01 t1 (risk share ranked), W02-per-point t2/t3 (share of the fall). Programs rank the
   per-issuer numerator instead (same order) and show the share vector unranked.

8. **Cross-run algebra.** (a) prev-run column × latest-run figure →
   `different_books: … a share is a share of its own book`; (b) `sub(w, w_prev)` settles but is typed
   as a *flow*, and `sub(that, <latest-run balance>)` → `incompatible_bases: a stock and a flow may be
   divided, not added`; (c) `add(mv_prev, pnl)` → `different_books`.
   Needs: W06 t1/t2 — drift = w_prev × (1+r_i)/(1+r_book) − w_prev. Programs use the mirror form on the
   latest run only (w_implied_prev = w × (1+r_book)/(1+r_i); chosen = w_implied_prev − w_prev;
   drift = w − w_implied_prev; traded_dollars = (mv − pnl) − mv_prev), which the calculator accepts.

9. **Sum across issuers minus a sum sharing an issuer.** `sub(sum(hit_by_name), add(hit_TLT, hit_HYG))`
   → `mixed_basis_operand: … is a sum across several periods … and shares an issuer with …`.
   Needs: F02 t2 (equities' part of the hit). Program rebuilds the 8-name sum from an 8-subject beta vector.
   (The same shape settles for W03-hedge t1 where all figures share one window — inconsistent.)

10. **No label-subset primitive for a vector.** Coverage weights (Σw over the names a measure exists
    for) need `mul($w, div($x, $x))`; `div(mul($w,$nde), $nde)` refuses for MULTIPLE-unit measures
    (`ratio ÷ multiple has no row in units.QUOTIENTS`). Needs: W02 t1, L01 t3.

11. **No elementwise min/clip.** A cash ladder is Σ min(mv_i, H × cap_i); `min` is a set reduction only.
    Needs: L04 t1 — irrelevant on this book (every name exits in < 0.004 sessions) but a gap for any
    book where a name's capacity is below its market value.

12. **Vector form of `price.distance_from_52w_high` drops the date of the high** (only the
    single-subject scalar carries it in `basis`). Needs: W01-stop-sweep t1 (asks the date per name).
    Ten single-subject calls would carry it; the program stays the vector + rank.

## Minor / data
- `price.window_return` on a ticker with no prices (VUG, LQD, IEF, XLE) and on `port_001` refuses as
  `untyped_operand` (a null-value calc row) rather than `no_price_history`; book window returns go
  through `book.explain_episode` (arbitrary dates work).
- No book price series: `prices`, `price.volatility`, `price.drawdown`, `price.beta` on `port_001`
  refuse; book vol exists only as the run's 30d/60d figures, so no 1y book vol, no OLS book beta,
  no tracking error (W03-vs-the-index, W05 t1, F01 t2).
- No correlation/covariance method → no effective number of bets (F01 t2); the diversification ratio
  (book vol / Σ w·vol) is the nearest thing.
- `issuer_exposures.quantity` is not a run column (columns: contribution, daily_pnl, daily_return,
  market_value, weight); the traded-amount test uses mv − pnl − mv_prev instead.
- `factor_attributions.*` columns are all `not_alone` (collinear) except `sum_of_contributions`, so
  `column`/`figure` on them refuse; the netted market beta comes from `book.analysis`.
