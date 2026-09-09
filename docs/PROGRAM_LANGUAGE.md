# The program language (V30)

What the model writes when a question needs figures. One program per
quantitative intent; the desk executes it, every node becomes a ledger row
and a Fact, and the answer points at nodes. The reference below is the
whole language; the same text (abridged) is the `run` tool's description.

## Shape

```json
{"let": [["name", <expr>], ...], "return": ["name", ...]}
```

- `let` is an ordered list of bindings. A binding is `[name, expression]`.
  Names are letters, digits and `_`, not starting with `_`; each bound once.
- An expression is one of: `{"fn": "<primitive>", ...args}`; `"$name"` (an
  earlier binding); a literal (number, string, list, object).
- A nested `{"fn": …}` inside an argument is allowed; it becomes its own node.
- `return` names the bindings the answer will point at (default: all).
- Bindings evaluate in order. A node that refuses becomes an ABSENCE; every
  node depending on it refuses with the ROOT cause named. The result table
  holds every node, settled or refused — nothing partial.
- Forgiving spellings: `{"name": …, "expr": …}` for a binding; a bare binding
  name in an operand position (`"b": "adv"`) means `$adv`; `direction`
  accepts `desc`/`asc`; positional `"args": [...]` maps onto the declared order.

## Values

| kind | what it is | comes from |
|---|---|---|
| scalar | one typed figure (unit, subject, as_of or window) | a filed line, a method, arithmetic, a statistic |
| series | one figure over the issuer's own periods | `fundamentals` with `last_n`, `prices`, a method with `last_n`, a series op |
| vector | one figure per label (ticker, sector, check) | a run column, a method over a list of subjects, arithmetic over a vector, `top` |
| ranking | an ordering of a vector | `rank` |
| table | a payload holding several named figures | a balance sheet, a scenario, a multi-figure method (beta/alpha/r2, adv shares/dollars) |
| run | a handle on a completed run or a scenario | `run`, `sell`, `buy` |
| absence | a refusal, with its reason | any node |

A table is not an arithmetic operand: `pick` one figure of it, or read a
`column` of it (scenarios read like runs).

## Primitives

**Reads**

| fn | args | yields |
|---|---|---|
| `fundamentals` | `ticker`, `metric?`, `months?` (3/6/9/12), `start?`,`end?`, `at?`, `last_n?` | a flow over a window (scalar); with `last_n` a series; a balance at `at` (scalar); with no `metric` the whole balance sheet (table) |
| `prices` | `ticker`, `window?` (1m/3m/6m/1y/3y) | series of adjusted closes |
| `window_return` | `ticker`, `start`, `end`, `benchmark?` | total return between two dates (a picked episode date may be named as `"$peak"`) |
| `price` | `ticker`, `as_of?` | table: close, adj_close |
| `run` | `portfolio`, `which?` (`latest` default, `prev`, or a `run_` id) | run |
| `column` | `run`, `table`, `col` | vector: `issuer_exposures.weight`, `issuer_exposures.market_value`, `sector_exposures.weight`, `limit_checks.current_value` / `warning_level` / `breach_level`, `factor_attributions.contribution`, …; also over a scenario (`$after`) and over a table's row list (`column(run="$explain", table="holdings", col="window_return")`) |
| `pick` | `of` (run, table, vector), `key` | scalar: one named figure (`exposure_metrics.portfolio_market_value` on a run; `beta` of a beta table; `dollars` or `adv_dollars` of an adv table); a non-figure field of a table's payload (`episodes[0].peak_date`) comes back as a LITERAL a later `params` may name as `"$peak"`; a computed scalar may likewise be named inside `params` or a `sales`/`buys` list (`{"ticker": "MSFT", "fraction": "$frac"}`) |
| `method` | `name`, `subject` (ticker / run / port_ / or a list), `params?`, `key?` | scalar (or vector over a list); `key` picks one figure of a multi-figure method; issuer methods with `params.last_n` yield a series |

**Arithmetic** — `add`, `sub`, `mul`, `div` (`a`, `b`): scalar∘scalar; vector∘scalar
broadcasts; vector∘vector aligns by label. `scale` (`of`, `factor`, `unit?`): a
figure or a vector times a constant. The typed calculator's refusals apply
unchanged (units, periods, books, containment).

**Sets** — `sum`, `avg`, `min`, `max`, `std` (`of`: a vector, or a series for
its own history); `abs` (`of`); `rank` (`of`, `direction?` highest/lowest);
`top` (`of`, `n`, `direction?`) = rank, then the first n as a vector; `select` (`of`, `labels`): the entries named, as a vector; `vector` (`entries`: `{label: $scalar, …}`, one unit): named scalars gathered so rank/top/avg apply.

**Series** — `yoy`, `qoq`, `pct`, `cagr`, `latest` (`of`: a series); `at`
(`of`, `period` YYYY-MM-DD): one point as a scalar.

**Scenarios** — `sell` (`run`, `sales: [{ticker, fraction?}]`), `buy` (`run`,
`buys: [{ticker, weight}]`): the after-book as a run-like table; chain them.

## Rules the executor enforces

1. **A binding name is a variable, never a measure.** A derived node's measure
   is built from its operation and operands (`sum[5](issuer_exposures.weight)`,
   `divide(issuer_exposures.market_value, scale(price.adv, 0.25))`); your
   `$name` is a handle. There is no `as_quantity`.
2. **Units come from the algebra.** MONEY ÷ MONEY_PER_DAY is a COUNT of days;
   MONEY ÷ MONEY is a RATIO; a product with no row in the unit table is refused.
3. **A superlative rests on a `rank` node**; a top-N on `top`. The answer's
   `rank` claim must point at one.
4. **A change is two periods of one measure**: `yoy`/`qoq` of a series, or
   `sub` of two readings — never one point written twice.
5. **The prior run is explicit**: `run(portfolio, which="prev")`; no prior run
   → refused, never assumed.

## Examples

Top five share, and against the prior run:
```json
{"let": [
  ["r",    {"fn": "run", "portfolio": "port_001"}],
  ["w",    {"fn": "column", "run": "$r", "table": "issuer_exposures", "col": "weight"}],
  ["top5", {"fn": "sum", "of": {"fn": "top", "of": "$w", "n": 5}}],
  ["prev", {"fn": "sum", "of": {"fn": "top", "of": {"fn": "column", "run": {"fn": "run", "portfolio": "port_001", "which": "prev"}, "table": "issuer_exposures", "col": "weight"}, "n": 5}}],
  ["delta", {"fn": "sub", "a": "$top5", "b": "$prev"}]]}
```

Days to liquidate at a quarter of daily dollar volume, worst first:
```json
{"let": [
  ["r",    {"fn": "run", "portfolio": "port_001"}],
  ["mv",   {"fn": "column", "run": "$r", "table": "issuer_exposures", "col": "market_value"}],
  ["adv",  {"fn": "method", "name": "price.adv", "subject": ["AAPL","MSFT","JPM"], "params": {"window_days": 20}, "key": "adv_dollars"}],
  ["days", {"fn": "div", "a": "$mv", "b": {"fn": "scale", "of": "$adv", "factor": 0.25}}],
  ["worst", {"fn": "rank", "of": "$days", "direction": "highest"}]]}
```

Revenue growth, and a margin compared across issuers:
```json
{"let": [
  ["rev", {"fn": "fundamentals", "ticker": "GOOGL", "metric": "revenue", "months": 12, "last_n": 5}],
  ["g",   {"fn": "yoy", "of": "$rev"}],
  ["gm",  {"fn": "method", "name": "gross_margin", "subject": ["AAPL", "MSFT", "GOOGL"]}],
  ["best", {"fn": "rank", "of": "$gm", "direction": "highest"}]]}
```

Rate sensitivity per name, and a hypothetical sale:
```json
{"let": [
  ["b",     {"fn": "method", "name": "price.beta", "subject": ["AAPL","MSFT","HYG"], "params": {"benchmark": "TLT"}, "key": "beta"}],
  ["most",  {"fn": "rank", "of": "$b", "direction": "highest"}],
  ["after", {"fn": "sell", "run": {"fn": "run", "portfolio": "port_001"}, "sales": [{"ticker": "NVDA"}]}],
  ["w_after", {"fn": "column", "run": "$after", "table": "issuer_exposures", "col": "weight"}],
  ["mv_after", {"fn": "pick", "of": "$after", "key": "exposure_metrics.portfolio_market_value"}]]}
```

## Claims the answer makes over nodes

`respond` states each figure as a claim over facts: `level` (a reading; a
series stands for its latest point), `tier` (a warning/breach/limit level,
said as one), `change` (of = the later reading or a yoy/qoq/sub node or a
series, against = the earlier; `f_…@period` addresses one point), `versus`
(one measure on two subjects), `ratio` (a quotient), `rank` (an entry of a
rank/top node), `room` (a check's current value against its tier), `absent`,
`quote` (a span verbatim, `…` allowed between verbatim parts), `series`, `table`. The gate checks each relation against the
fact's identity; a tier stated as a level, the same point on both sides of a
change, a superlative with no rank node, a MONEY figure called days — refused.

## What comes back

```json
{"program_id": "calc_…", "returns": [...], "settled": 7, "refused": ["x"],
 "nodes": {"top5": {"kind": "scalar", "unit": "RATIO", "measure": "sum[5](issuer_exposures.weight)",
                    "subject": "run_…", "value": 0.7087, "as_of": "2026-09-04", "fact": "f_…"},
           "w":    {"kind": "vector", "unit": "RATIO", "measure": "issuer_exposures.weight",
                    "entries": {"MSFT": {"fact": "f_…", "value": 0.161}, ...}},
           "worst": {"kind": "ranking", "order": ["JPM", "LLY", ...], "leader": "JPM", "entries": {...}},
           "x":    {"kind": "absence", "refusal": {"error": "…", "detail": "…"}}},
 "facts": {"columns": [...], "rows": [...]}}
```
Every figure in `nodes` is a Fact in `facts` with its full identity; the
answer points at facts (`f_…`) or at nodes by name through claims.

## Boundaries (recorded from the V26 program authoring, 2026-09-09)

Things a program cannot say, and why — algebra policy, not language:

- **Book minus market.** The book's window return minus SPY's is refused (`mixed_worlds`): a book figure
  and an issuer's account are two worlds; the ratio goes through. An excess return is read off the two
  figures. (V22 book algebra.)
- **A stock minus a scaled flow.** `2 × EBITDA − net_debt` is refused (`incompatible_bases`); a stock and
  a flow may be divided, not netted. Capacity is stated as the two figures. (V9 rule R4.)
- **Cross-run arithmetic.** Two runs' weights may be differenced (the change) and divided, never summed
  or multiplied (`different_books`); the difference is typed as a flow and does not net against a
  balance. Drift decompositions are written on the latest run's own figures.
- **Sums that share an issuer.** A sum across issuers minus a sum sharing one of them is refused
  (`mixed_basis_operand`); rebuild the smaller sum from its parts.
- **Two method readings of one issuer at two dates** are differenced through the method's series and
  `at`, not through two single readings (`at=` on a flow-based method shifts only its balances).

Data the fixture does not hold (the honest answer names them): `issuer_exposures.quantity` is not a
run column; episode durations are payload literals, not figures; `factor_attributions.*` are
`not_alone` under a collinear fit; a name whose `companies.sector` is missing cannot be bought in a
scenario; `total_debt` cover is incomplete for MSFT/NVDA/KO.
