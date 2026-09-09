# Does a runtime refusal do the work V29's schema enum did? (2026-09-09)

**Question.** V29 closed a class by construction: `compute`'s `method` was a schema enum, so a wrong
method name became unrepresentable. `unknown_method` went from 32 occurrences on 2026-09-07 (names free
strings, every name printed in the catalogue the model read) to 0 in both 09-08 replicates. V30 moved
method names back inside the program JSON, where nothing binds them — `run`'s schema types `let` items
only as array-or-object — and C3 has seen zero `unknown_method` in ~120 turns.

Zero occurrences is *unverified*, not *safe*. That reading has cost this project before. So the names
the 09-07 battery actually got wrong were replayed through V30's node:
`scripts/v30_replay_method_names.py`, output `METHOD_NAME_REPLAY.json`.

**What the replay found.** The mistake is not misspelling. Of 25 distinct wrong names (76 sends):

| what the name really is | distinct | sends | examples |
|---|---|---|---|
| a filed line item | 18 | 57 | `capex`, `revenue`, `operating_cash_flow`, `net_income`, `depreciation`, `interest_expense`, `inventory` |
| a primitive of the program language | 4 | 13 | `yoy`, `latest`, `rank`, `divide` |
| a domain | 1 | 2 | `issuer_capital_allocation` |
| a figure of a run | 2 | 3 | `issuer_exposures.weight`, `attribution.attribution_portfolio_return` |

None of them is a method under any spelling, so an enum would have made them unrepresentable without
telling the model where the figure lives. And the refusal that existed was worse than silence: `nearest`
answered with a real method that is the wrong figure — `revenue` → `roe`, `depreciation` →
`current_ratio`, `inventory` → `days_inventory`.

**The fix, and the measurement.** `_p_method` now routes a name it recognises to its own door rather
than guessing a neighbour: a filed line to `{"fn": "fundamentals", "ticker": …, "metric": …}`, a
primitive to its own `fn` shape, a domain to `describe(subject, expand=…)`, a `table.col` name to
`pick` / `column`. The code is `wrong_door`, classed with the call errors in
`claims.SPELLING_REFUSALS` — the call is re-made, and the reader is told nothing.

| | before | after |
|---|---|---|
| refused by `run`'s json_schema | 0/25 | 0/25 |
| refused at node level | 25/25 | 25/25 |
| refusal names a real method to try | 23/25, mostly the wrong figure | 2/25 |
| refusal routes the name to its own door | 0/25 | **23/25 (74/76 sends)** |

The two that still fall through to `nearest` are `share_count` (not a metric this desk normalises) and
`attribution.attribution_portfolio_return` (a run figure whose table prefix is not in the run-table
list). Pinned by `test_a_name_at_the_wrong_door_is_sent_to_its_own_door`.

**What this does and does not settle.** It settles that the runtime refusal now carries more than the
enum could: the enum refuses the call, this names the door. It does not settle that V30 needs no schema
constraint — a genuinely misspelled method (`grosss_margin`) is still a runtime refusal, and the
provider-side guarantee would need the program schema to enumerate method names inside the `method`
node. That is on the plan's decision list, not fixed here.
