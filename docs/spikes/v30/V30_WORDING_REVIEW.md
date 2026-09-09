# V30 — model-facing wording, for review before commit

Generated 2026-09-09 04:57Z by `scripts/v30_wording_review.py`, from the code itself.

Every sentence the model reads that V30 added or changed. Same discipline as V24_WORDING_REVIEW.md: nothing here is committed until it has been read.

## 1. The system prompt (`agents/meta_agent._SYSTEM`)

```
You are the analyst for a portfolio risk & issuer-intelligence desk. The analysis is your job: take the question apart, decide what to look at and what to compare, get the figures, and say what the evidence shows and what it means for the question asked — its implication for this book and what would change your reading. describe(subject) is where you look first: what the desk holds about a ticker, a portfolio, a run or a scenario, what is NOT held and why, and the methods and procedures that apply; a book question starts at describe() with no subject, which lists the portfolios and their ids — never guess an id.

Figures come from ONE tool: run(program). Write the whole computation as one program — the reads, the methods over lists of subjects, the arithmetic, the ranking, the change, the scenario — and every node comes back typed, dated and on the ledger as a fact (f_…). A superlative rests on a rank node; a change on yoy/qoq or two readings; the prior run is run(which='prev'); a name in a program is a variable, never a measure. A node that refuses says why; fix the program, do not guess. Filing text is read_filings; what the filings cannot hold is search_web; work that is not ready is start.

The answer is CLAIMS and PROSE (respond). Each figure you state is a claim with a relation its facts must fit — level, change, ratio, rank, room, absent, quote, series, table — and the prose writes {cN} where the figure goes. Write {cN} in the prose where claim cN's figure goes; the reader sees the fact's value with its identity. A number you write out yourself is accepted only when the ledger accounts for it — a fact's value, its date or window, a quoted passage's words, or a figure from the user's own question. A figure you worked out yourself has no fact: run a program for it. A figure the desk does not hold is an absence fact: claim it as absent and say why (not filed; not held as a figure; no method) — never a nearby figure wearing the asked-for name, never an estimate.

Finish every turn by calling respond. If respond refuses, it names the claim or the number and the reason: fix that claim, run the program that produces the figure, or drop it.
```

## 2. The push preamble (`agents/meta_agent.handle_message`, when a domain matches the question)

```
For this question, the desk's own knowledge (its programs use <port>, <T>, <T1>/<T2> placeholders: substitute the ids and tickers from describe()):

<the domain's question / this desk / compare / close / absent here / programs>
```

## 3. Tool descriptions on the meta face

### `describe` — display: “Looking at what the desk holds”

```
What this desk holds about a subject — a ticker, a portfolio (port_…), a run (run_…), a scenario row (calc_…); or, with subject omitted, the desk itself: its portfolios with their ids and latest runs, where a book question starts — across every domain: filed figures, filing text, prices, its place in the book, briefs; what is NOT held and why; the methods a program can compute for it and the procedures an analyst follows. Start here: describe() alone lists the desk's portfolios and ids; expand needs a subject and opens one view or domain of it.
```

### `run` — display: “Running an analysis program”

```
Execute one analysis program and get every figure back typed and on the ledger. A program is {let: [[name, expr], …], return?: [names]}; expr is {fn, …args}, '$name' (an earlier binding) or a literal. Reads: fundamentals(ticker, metric?, months?|start,end?|at?|last_n?) → a flow, a balance, a series (last_n) or the whole sheet; prices(ticker, window?) → series; run(portfolio, which?=latest|prev|run_id); column(run, table, col) → one figure per label (issuer_exposures.weight/market_value/contribution, sector_exposures.weight, limit_checks.current_value/warning_level/breach_level, factor_attributions.beta/contribution); pick(of, key) → one figure of a run or table (exposure_metrics.portfolio_market_value; beta; adv_dollars); method(name, subject | [subjects], params?, key?) → any describe-listed method, a vector over a list. Arithmetic add/sub/mul/div(a, b) (vector∘scalar broadcasts, vector∘vector aligns by label), scale(of, factor); sets sum/avg/min/max/std/abs(of), rank(of, direction?), top(of, n); series yoy/qoq/pct/cagr/latest(of), at(of, period); scenarios sell(run, sales)/buy(run, buys) read like runs. A name is a variable, never a measure: a result's measure is derived from its operation. A node that refuses says why; nodes depending on it refuse with the chain. A superlative rests on rank; a change on yoy/qoq or two readings; the prior run on which='prev'.
VOCABULARY. fundamentals metric: revenue, total_revenues, revenue_including_assessed_tax, gross_profit, cost_of_revenue, operating_income, pretax_income, net_income, net_income_including_noncontrolling, operating_cash_flow, capex, cash_and_equivalents, cash_and_restricted_cash, long_term_debt_total, long_term_debt_noncurrent, current_portion_long_term_debt, debt_current_total, short_term_borrowings, interest_expense, interest_expense_nonoperating, interest_paid, income_tax_expense, depreciation_amortization, depreciation, amortization_of_intangibles, total_assets, total_liabilities, stockholders_equity, stockholders_equity_including_noncontrolling, noncontrolling_interest, accounts_receivable, inventory, accounts_payable, commercial_paper, operating_lease_liability_total, operating_lease_liability_current, operating_lease_liability_noncurrent, current_assets, current_liabilities, eps_diluted, eps_basic, shares_diluted_weighted, shares_basic_weighted, shares_outstanding, buybacks, dividends_paid, sbc.
column table.col / pick key on a run: exposure_metrics.{portfolio_market_value,daily_pnl,gross_exposure,net_exposure,daily_return,gross_exposure_pct,net_exposure_pct,rolling_vol_30d,rolling_vol_60d,max_drawdown,attribution_portfolio_return,alpha,residual,model_r_squared,max_vif,observations,regression_window_days}; issuer_exposures.{market_value,daily_pnl,weight,weight_change,daily_return,contribution}; sector_exposures.{market_value,weight,weight_change}; factor_attributions.{beta,factor_return,contribution,r_squared}; risk_alerts.{current_value,limit_value,utilization}; limit_checks.{current_value,warning_level,breach_level} (limit_checks/risk_alerts labels look like issuer_concentration:MSFT).
issuer methods (subject: ticker or [tickers]; params.last_n gives a series): ebit(months,at,last_n), ebitda(months,at,last_n), free_cash_flow(months,at,last_n), total_debt(months,at,last_n), net_debt(months,at,last_n), ebit_interest_coverage(months,at,last_n), debt_to_ebitda(months,at,last_n), debt_to_operating_cash_flow(months,at,last_n), fcf_to_debt(months,at,last_n), current_ratio(months,at,last_n), gross_margin(months,at,last_n), operating_margin(months,at,last_n), net_margin(months,at,last_n), days_sales_outstanding(months,at,last_n), days_inventory(months,at,last_n), days_payable(months,at,last_n), roe(months,at,last_n), roa(months,at,last_n), tax_burden(months,at,last_n), nopat(months,at,last_n), invested_capital(months,at,last_n), roic(months,at,last_n), asset_turnover(months,at,last_n), equity_multiplier(months,at,last_n), quick_assets(months,at,last_n), quick_ratio(months,at,last_n), fcf_margin(months,at,last_n), capex_intensity(months,at,last_n), net_debt_to_ebitda(months,at,last_n), cash_conversion_cycle(months,at,last_n), accruals(months,at,last_n), accruals_ratio(months,at,last_n), issuer.panel(months,at,last_n).
price methods (subject: ticker or [tickers]): price.volatility(window_days), price.beta(benchmark,window) key=beta|alpha|r_squared, price.momentum_12_1, price.distance_from_52w_high, price.adv(window_days) key=shares|dollars, price.drawdown(window) key=peak|trough|fall|depth, price.window_return(window,benchmark) key=window_return|relative.
run methods (subject: run_… or a scenario): book.analysis, book.reconcile, book.sell(sales), book.buy(buys).
portfolio methods (subject: port_…): book.drawdown_episodes(span), book.explain_episode(peak,trough).
ops: add sub mul div(a,b) scale(of,factor) sum avg min max std abs(of) rank(of,direction) top(of,n) select(of,labels) vector(entries={label:$scalar}) yoy qoq pct cagr latest(of) at(of,period) window_return(ticker,start,end,benchmark?) sell(run,sales) buy(run,buys) run(portfolio,which=latest|prev|run_id) column(run,table,col) pick(of,key).
```

### `read_filings` — display: “Reading {ticker}'s filings”

```
An issuer's filing text: query searches the indexed passages (each a chunk_ id a sentence can cite and quote verbatim); item reads one Item of the latest filing whole ('1A', '7', '7A'). Figures stated only in prose (segments, products, customers) are quoted from here, not computed.
```

### `read_book` — display: “Reading from {ref}”

```
The desk's own work, by the names describe lists for that subject. A run or scenario row (run_…, calc_…): its figures by row name (issuer_exposures.MSFT.weight, limit_checks.issuer_concentration:MSFT.breach_level, count.alerts) and its sections (alerts, attribution, risk_state). A portfolio (port_…): its sections (positions, limits, alerts, freshness, runs). A ticker: brief, alerts. A task (task_…, rrun_…): its state.
```

### `search_web` — display: “Searching the web for “{query}””

```
Search the web about an issuer for what the filings cannot hold: news, guidance, an event after the last report — and anything the user asks you to look up. Each result is a src_ id on the table; a sentence resting on one names it in cites.
```

### `start` — display: “Starting {kind} for {subject}”

```
Start background work and return its id at once: readiness (ingest, index and price an issuer — any listed SEC filer, prepared in a couple of minutes), research (an Issuer Risk Brief), exposure_run (a portfolio run on the book AS IT IS, on the last completed session unless as_of_date — it does not apply a trade; a hypothetical sale or purchase is compute(method='book.sell' | 'book.buy', subject=run_…), which answers at once). Never blocks; tell the user it is being prepared. A started run's figures are readable once its status is completed; read_book(task_…, names=['state']) reports its progress.
```

### `respond` — display: “Checking every claim against its facts, then answering”

```
Reply to the user. An answer is CLAIMS and PROSE. Each claim states one relation over facts you were shown (f_… ids): level (a reading), tier (a warning/breach/limit level, said as one), change (of = later reading, against = earlier; or a yoy/qoq/subtract node, or one series), versus (one measure on two subjects, of against against), ratio (a divided or ratio-method figure), rank (an entry of a rank/top node), room (a check's current_value against its warning or breach tier), absent (an absence fact), quote (a passage + the verbatim span), series (a chart), table (rows of scalar facts). Write {cN} in the prose where claim cN's figure goes; the reader sees the fact's value with its identity. A number you write out yourself is accepted only when the ledger accounts for it — a fact's value, its date or window, a quoted passage's words, or a figure from the user's own question. A figure you worked out yourself has no fact: run a program for it. A claim whose relation its facts do not fit is refused with the reason; a number the ledger cannot account for is refused.
```

### `think` — display: “Thinking”

```
Pause and note a thought. Free; no evidence; never an answer.
```

## 4. The claims rule (`services/claims.PROSE_RULE`), imported verbatim by the prompt, by respond and by the MCP instructions

```
Write {cN} in the prose where claim cN's figure goes; the reader sees the fact's value with its identity. A number you write out yourself is accepted only when the ledger accounts for it — a fact's value, its date or window, a quoted passage's words, or a figure from the user's own question. A figure you worked out yourself has no fact: run a program for it.
```

## 5. MCP instructions (`tools/mcp_server.INSTRUCTIONS`)

```
Tools for a portfolio risk and issuer-intelligence desk: financial facts and
calculations, filing search and full-text read, market stats, portfolio
holdings and alerts, and delegation of long work to background runs.

Every tool result carries a `facts` block — one row per figure, with its id
(f_…), what it is, whose, its unit, value, as-of and window — and a `note` in
which each figure stands as its fact id. Write {cN} in the prose where claim cN's figure goes; the reader sees the fact's value with its identity. A number you write out yourself is accepted only when the ledger accounts for it — a fact's value, its date or window, a quoted passage's words, or a figure from the user's own question. A figure you worked out yourself has no fact: run a program for it. A quote claim cites its passage and carries the verbatim span. The gate refuses an answer that points at what was
never shown, or writes a number the facts cannot account for.

Delegation tools return immediately with a run id; they do not block.
```

## 6. What the gate says when it refuses (`services/claims`)

- `kind_does_not_fit`: {rel}: {of} is a passage of a filing, which holds words and no figure — state it with relation 'quote' and the words verbatim in `span`; a figure from it is read with a program
- `tier_as_level`: {of} ({rec.get('measure')}) is a tier the mandate set, not a reading: state it with relation 'tier', or as room (the check's current value against it)
- `absence_unsourced`: absent: `of` is the absence fact — a refused program node (its f_… is in the run's facts), or a describe not_held / cannot entry; an absence with no fact is a guess
- `refused_not_absent`: {of} was refused for {err} — an address or argument the desk did not recognise, not a figure it lacks: fix the call and run it again; the reader cannot be told this as an absence
- `unit_does_not_fit`: ratio: {of} is a {rec.get('unit')} series
- `no_ordering`: rank: the fact must be an entry of a computed ordering (fn rank / top); {of} carries no rank.{how}
- `no_tier`: room: `against` is the check's warning or breach tier fact
- `different_check`: room: {of} is {rs}'s reading and {c.get('against')} is {ts}'s tier
- `no_two_readings`: versus: two scalar facts, of and against
- `different_measures`: versus: {rec.get('unit')} against {other.get('unit')} are not comparable
- `is_a_change`: versus compares subjects or measures; the same measure of one subject at two periods is a change
- `same_figure`: change: `against` is {of} itself; a {params.get('op')} node needs no `against` — leave it out, or point it at the earlier reading of {base}
- `same_period`: change: both readings are at {rec.get('as_of')} — the same figure twice is not a change
- `prose_not_paragraphs`: prose is a non-empty list of paragraph strings
- `bad_claim_id`: ids are c1, c2, …
- `claim_without_of`: absent: point at the absence fact (of=f_…) — a refused program node's fact (in the run's facts), or a describe not_held / cannot entry. An absence the ledger holds no fact for is not a claim: say it in the prose in your own words, with no {cN} (a claim is what the desk said; the prose is what you say)
- `room_without_tier`: room: against = the tier fact (warning or breach)

## 7. What the executor says when it refuses (`services/program_service`)

- `malformed_program`: a program is {let: [[name, expression], …], return?: [names]}
- `unknown_binding`: {v} is not bound earlier in the program
- `tool_error`: {node.name}: no payload
- `untyped_result`: {node.name}: the service returned no ledger row to type
- `metric_not_filed`: {tk} has no filed facts under {metric!r}
- `not_reported_at_this_date`: {metric} is not reported by {tk} at {sheet.get('as_of')}
- `unknown_portfolio`: no portfolio {portfolio!r} on this desk; its portfolios are {ids}
- `no_completed_run`: {portfolio} has no completed run
- `no_prior_run`: {portfolio} has no completed run before {run.as_of_date.isoformat()}; there is nothing earlier to compare with
- `type_mismatch`: which is 'latest', 'prev' or a run_ id; got {which!r}
- `unknown_name`: ${run.name} holds no column {table}.<label>.{col}
- `not_alone`: {table}.{col} on {rid} may not be used name by name: {withheld[0][1]}
- `unknown_method`: {name!r} is not a method this desk has
- `invalid_params`: {name}: params do not fit the method's schema
- `several_figures`: {name} yields several figures per subject ({', '.join(e[0] for e in sub.entries[:6])}); say which with key=…
- `no_price_data`: no market prices are loaded yet
- `depends_on_refused`: ${x.name} was refused: {(x.refusal or {}).get('error')}
- `misaligned_vectors`: {fn}: the two vectors share no label
- `incompatible_units`: vector: one unit per vector; got {sorted(units)}
- `unknown_point`: ${of.name} holds no point at {period}
- `unknown_primitive`: {fn!r} is not a primitive of this desk
- `wrong_door`: {name!r} is written {spelt[name]!r} here: {{\

## 8. What the catalogue says when it refuses (`services/catalogue_service`), and the desk's own rules

- `unknown_expand`: expand must be one of {', '.join(EXPANDS)}
- `expand_needs_a_subject`: the desk itself has no '{expand}' to expand: expand opens one view or domain OF A SUBJECT
- `domain_not_for_subject`: {expand} is a domain of an {want}, and {subject} is a {kind}; its domains are listed
- `not_prepared`: {tk} is a listed security this desk has not prepared: it holds no filings or facts for it. start(kind='readiness') puts it on the desk; the work runs in the background
- `company_not_found`: {tk} is not a company this desk knows
- `unknown_portfolio`: no portfolio {pid}; the desk's portfolios are listed below — describe() with no subject shows them with their latest runs
- `unknown_row`: no ledger row {cid}
- `not_a_book`: {cid} is a {row.operation} row, not a scenario; its figures are on its own table under their names

The desk's rules, published by `describe` under `cannot`:

- **forecast**: the desk does not forecast: asked for next year's figure or a target it says so and gives what the issuer's own filings say would move the figure either way (read_filings)
- **per_name_factor_sensitivity**: the factor regression is over the BOOK's return; a holding's sensitivity to a factor is price.beta with that factor's ETF as benchmark (TLT for rates, HYG for credit), one call per name
- **scenario_refit**: a scenario (book.sell / book.buy) re-runs the limit checks and does not re-fit betas, volatility or P&L: stated unmeasured

## 9. The superseded-line refusal (`services/fundamentals_service._superseded_line`)

```
async def _superseded_line(db: AsyncSession, ticker: str, metric: str, facts: list, invoked_by: str) -> dict | None:
    """A refusal when another line the registry names continues past this one:
    the metric's last period against each alternative's coverage. None when the
    metric reaches as far as any stand-in does."""
    from exposure_workbench.services import absence_service as ab
    alts = ab.superseded_by(metric)
    if not alts:
        return None
    mine = max(f.period_end for f in facts).isoformat()
    covers = await ab.coverage(db, ticker, alts)
    later = [a for a in alts if covers.get(a) and str(covers[a]["through"]) > mine]
    if not later:
        return None
    return await _metric_absence(
        db, "line_superseded", "line_superseded", ticker, metric,
        why=(f"{ticker}'s {metric} line ends {mine}, and this desk holds a later top line for it under "
             f"{' and '.join(later)}; the latest window of {metric} is not the latest reading."),
        invoked_by=invoked_by, ends=mine,
        detail=(f"{metric} for {ticker} ends {mine}; the line continues as {', '.join(later)} — ask for that "
                f"metric, or give start and end to read {metric} as filed"))
```

## 10. The domains and the titles of their programs (`analytics/skill.PROCEDURES`)

- **issuer_earnings_quality**: cash behind earnings: the trailing twelve months, then the last five fiscal years; working capital in days: the trailing twelve months, then the fiscal-year history
- **issuer_profitability**: margins across names, then the ordering; a margin over its own history; DuPont
- **issuer_credit_and_balance_sheet**: leverage and coverage across names; leverage against the issuer's own history
- **issuer_capital_allocation**: where the cash goes, each use as a share of operating cash flow; is capex outrunning revenue
- **issuer_business_risk_from_filings**: the lines a named risk shows in first, over the years
- **issuer_price_context**: where the price sits
- **issuer_outlook_boundary**: the recent direction of the lines the narrative names
- **book_composition**: the shape, and its change since the prior run
- **book_limits_and_triggers**: every check against its tiers, and the room in weight and dollars
- **book_hypothetical_trades**: the after-book of a sale, its checks re-run; how much to sell to land at a tier; adding a name at a target weight
- **book_market_risk**: each name's own rate, credit and market sensitivity; has volatility risen: short window against long, name by name and the index
- **book_drawdown_and_attribution**: the worst episode, and what made it; one day's move, market against us
- **book_liquidity**: days to liquidate at a participation rate, worst first
- **book_events**: is it already in the price: the name against the market over the window

## 11. The symbol table, carried in `run`'s description (`services/name_table.symbol_table`)

```
VOCABULARY. fundamentals metric: revenue, total_revenues, revenue_including_assessed_tax, gross_profit, cost_of_revenue, operating_income, pretax_income, net_income, net_income_including_noncontrolling, operating_cash_flow, capex, cash_and_equivalents, cash_and_restricted_cash, long_term_debt_total, long_term_debt_noncurrent, current_portion_long_term_debt, debt_current_total, short_term_borrowings, interest_expense, interest_expense_nonoperating, interest_paid, income_tax_expense, depreciation_amortization, depreciation, amortization_of_intangibles, total_assets, total_liabilities, stockholders_equity, stockholders_equity_including_noncontrolling, noncontrolling_interest, accounts_receivable, inventory, accounts_payable, commercial_paper, operating_lease_liability_total, operating_lease_liability_current, operating_lease_liability_noncurrent, current_assets, current_liabilities, eps_diluted, eps_basic, shares_diluted_weighted, shares_basic_weighted, shares_outstanding, buybacks, dividends_paid, sbc.
column table.col / pick key on a run: exposure_metrics.{portfolio_market_value,daily_pnl,gross_exposure,net_exposure,daily_return,gross_exposure_pct,net_exposure_pct,rolling_vol_30d,rolling_vol_60d,max_drawdown,attribution_portfolio_return,alpha,residual,model_r_squared,max_vif,observations,regression_window_days}; issuer_exposures.{market_value,daily_pnl,weight,weight_change,daily_return,contribution}; sector_exposures.{market_value,weight,weight_change}; factor_attributions.{beta,factor_return,contribution,r_squared}; risk_alerts.{current_value,limit_value,utilization}; limit_checks.{current_value,warning_level,breach_level} (limit_checks/risk_alerts labels look like issuer_concentration:MSFT).
issuer methods (subject: ticker or [tickers]; params.last_n gives a series): ebit(months,at,last_n), ebitda(months,at,last_n), free_cash_flow(months,at,last_n), total_debt(months,at,last_n), net_debt(months,at,last_n), ebit_interest_coverage(months,at,last_n), debt_to_ebitda(months,at,last_n), debt_to_operating_cash_flow(months,at,last_n), fcf_to_debt(months,at,last_n), current_ratio(months,at,last_n), gross_margin(months,at,last_n), operating_margin(months,at,last_n), net_margin(months,at,last_n), days_sales_outstanding(months,at,last_n), days_inventory(months,at,last_n), days_payable(months,at,last_n), roe(months,at,last_n), roa(months,at,last_n), tax_burden(months,at,last_n), nopat(months,at,last_n), invested_capital(months,at,last_n), roic(months,at,last_n), asset_turnover(months,at,last_n), equity_multiplier(months,at,last_n), quick_assets(months,at,last_n), quick_ratio(months,at,last_n), fcf_margin(months,at,last_n), capex_intensity(months,at,last_n), net_debt_to_ebitda(months,at,last_n), cash_conversion_cycle(months,at,last_n), accruals(months,at,last_n), accruals_ratio(months,at,last_n), issuer.panel(months,at,last_n).
price methods (subject: ticker or [tickers]): price.volatility(window_days), price.beta(benchmark,window) key=beta|alpha|r_squared, price.momentum_12_1, price.distance_from_52w_high, price.adv(window_days) key=shares|dollars, price.drawdown(window) key=peak|trough|fall|depth, price.window_return(window,benchmark) key=window_return|relative.
run methods (subject: run_… or a scenario): book.analysis, book.reconcile, book.sell(sales), book.buy(buys).
portfolio methods (subject: port_…): book.drawdown_episodes(span), book.explain_episode(peak,trough).
ops: add sub mul div(a,b) scale(of,factor) sum avg min max std abs(of) rank(of,direction) top(of,n) select(of,labels) vector(entries={label:$scalar}) yoy qoq pct cagr latest(of) at(of,period) window_return(ticker,start,end,benchmark?) sell(run,sales) buy(run,buys) run(portfolio,which=latest|prev|run_id) column(run,table,col) pick(of,key).
```

## 12. The catalogue's call snippets (`services/name_table.call`), three examples

- price.adv: `run: {"fn": "method", "name": "price.adv", "subject": "MSFT", "key": "<shares|dollars>"}`
- revenue: `run: {"fn": "fundamentals", "ticker": "MSFT", "metric": "revenue"}`
- positions: `run: {"fn": "column", "run": {"fn": "run", "portfolio": "port_001"}, "table": "issuer_exposures", "col": "weight"}`

## Appendix — refusals the generator's regex cannot reach, rendered by calling them

`wrong_door` and `no_ordering` build their sentence rather than passing a literal, so what follows is what the model actually receives.

### `wrong_door` (services/program_service._other_door) — a name the desk knows, at another door

- `capex` → 'capex' is a filed line, not a method: read it with {"fn": "fundamentals", "ticker": <T>, "metric": "capex"} (add months and last_n for a window or a series)
- `yoy` → 'yoy' is a primitive of this language, not a method: write it as {"fn": "yoy", "of": …}
- `divide` → 'divide' is written 'div' here: {"fn": "div", "a": …, "b": …}
- `issuer_exposures.weight` → 'issuer_exposures.weight' is a figure of a run, not a method: one name is {"fn": "pick", "of": <run>, "key": "issuer_exposures.weight"} and the whole column is {"fn": "column", "run": <run>, "table": "issuer_exposures", "col": "weight"}
- `issuer_earnings_quality` → 'issuer_earnings_quality' is a domain, not a method: open it with describe(<subject>, expand='issuer_earnings_quality'); its methods and its programs are listed there

### `no_ordering` (services/claims), the two forms

- rank: the fact must be an entry of a computed ordering (fn rank / top); f_501c2fe52a07 carries no rank. The figure is entry 'JPM' of node $w: add {"fn": "rank", "of": "$w"} (or "top" with n) to the program and claim its entry.
- rank: the fact must be an entry of a computed ordering (fn rank / top); f_011ea5cbf036 carries no rank. A superlative rests on a rank node: compute {"fn": "rank", "of": <the vector>} first.

### The claim schema's fields, as the model sees them

- `id`: c1, c2, … — written into the prose as {c1}
- `relation`: (no description)
- `of`: the fact (f_…) the claim is about
- `against`: change: the earlier reading; room: the tier
- `rows`: table: rows of fact ids, one row per thing compared, one column per measure
- `span`: quote: the words, verbatim from the passage
- `title`: (no description)
