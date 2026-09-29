# 每种沟通的 schema：取自本轮的真实载荷

## meta → gate · answer
（Q01-amzn-earnings-quality seq 44）
```json
{
 "text": "I can’t yet answer whether Amazon’s earnings quality is deteriorating, because the issuer analyst did not return the quarter-by-quarter filing evidence I asked for.\n\nWhat I can say from the portfolio desk is that AMZN was 7.03% [f_435d3d2c7ab8] of the book, or $756K [f_220abae443ff], as of 2026-09-10, versus 7.07% [f_6a11b108a33b] on 2026-09-09, so the weight edged down. That is the only position-size reading the desk returned.\n\nThe implication for the book is limited until the earnings-quality pieces are settled. If the next filing-backed read shows operating cash flow consistently lagging net income, a worsening accruals ratio, and receivables or inventory growing faster than revenue, that would point to softer earnings quality and would argue for more caution on a 7.03% [f_435d3d2c7ab8] AMZN position. If those lines instead confirm cash generation and inventory/receivables growth in line with revenue, the current position would look easier to carry.",
 "problems": [
  {
   "rule": 8,
   "reason": "measure_mismatch",
   "sentence": "S5"
  }
 ]
}
```
→ refused: measure_mismatch; 1 problem(s), all listed; the first: prose[2] rule 8 — measure_mismatch: the sentence says 'accruals ratio' but the figure beside it is issuer_exposures.weight; the ledger holds accruals_ratio as its own fact — write that value, or drop the phrase

## meta → store · open
（Q05-aapl-risk-and-concentration seq 24）
```json
{
 "id": "r_0796f19e44b4"
}
```
→ 1 row(s) of 1, shown [0, 1]

## meta → sub · ask
（Q03-nvda-where-cash-goes seq 37）
```json
{
 "raw": "{\"tasks\": [{\"analyst\": \"issuer\", \"subjects\": [\"NVDA\"], \"lines\": [\"Trailing twelve months ended 2026-07-26 versus three years earlier: capital expenditure \\u00f7 cash from operations\", \"Trailing twelve months ended 2026-07-26 versus three years earlier: share repurchases \\u00f7 cash from operations\", \"Trailing twelve months ended 2026-07-26 versus three years earlier: dividends paid \\u00f7 cash from operations\", \"Trailing twelve months ended 2026-07-26 versus three years earlier: share-based compensation \\u00f7 cash from operations\"], \"follow_up_of\": \"tsk_e101709d4877\", \"context\": \"Complete the three-year movement comparison for each cash-use share.\"}]}"
}
```
→ invalid_delegation: tasks[0] says which requirement(s) it is for: one or more of R1, R2, R3, R4

## meta → sub:issuer · ask
（Q02-xom-room-if-oil-falls seq 41）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R2",
     "anchor": "Give net debt to EBITDA, EBIT interest coverage and FCF to debt for the latest four quarters against the same four a year earlier"
    }
   ],
   "lines": [
    "1. Net debt to EBITDA for XOM, latest four quarters ending 2026-03-31",
    "2. Net debt to EBITDA for XOM, same four quarters ending 2025-03-31",
    "3. EBIT / interest coverage for XOM, latest four quarters ending 2026-03-31",
    "4. EBIT / interest coverage for XOM, same four quarters ending 2025-03-31",
    "5. Free cash flow / debt for XOM, latest four quarters ending 2026-03-31",
    "6. Free cash flow / debt for XOM, same four quarters ending 2025-03-31"
   ],
   "analyst": "issuer",
   "context": "For Exxon Mobil Corporation; request the values with the periods the desk actually has, then compare latest four quarters with the same four a year earlier.",
   "task_id": "tsk_899b4a5b61aa",
   "subjects": [
    "XOM"
   ]
  }
 ]
}
```
→ issuer [XOM] 6 line(s)

## meta → sub:issuer+market · ask
（Q06-jpm-riskier-than-a-year-ago seq 2）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R1",
     "anchor": "Is the market treating JPMorgan as riskier than a year ago?"
    },
    {
     "id": "R2",
     "anchor": "Thirty-day volatility, beta to SPY and distance from the 52-week high now and twelve months ago,"
    }
   ],
   "lines": [
    "1. 30-session volatility now and 12 months ago",
    "2. beta to SPY now and 12 months ago",
    "3. distance from the 52-week high now and 12 months ago"
   ],
   "analyst": "market",
   "context": "Assess whether JPMorgan is being treated as riskier than a year ago.",
   "task_id": "tsk_4e5b458a0f5a",
   "subjects": [
    "JPM"
   ]
  },
  {
   "for": [
    {
     "id": "R3",
     "anchor": "beside interest expense and the pretax-to-net-income gap over three years."
    },
    {
     "id": "R4",
     "anchor": "Note where the desk's issuer methods do not apply to a bank."
    }
   ],
   "lines": [
    "1. interest expense over the last 3 fiscal years",
    "2. pretax income minus net income over the last 3 fiscal years",
    "3. which issuer methods do not apply to a bank, and why"
   ],
   "analyst": "issuer",
   "context": "Compare bank-specific filing metrics and note the desk policy limits for financial issuers.",
   "task_id": "tsk_ba8d5ee4d299",
   "line_for": {
    "1": [
     "R3"
    ],
    "2": [
     "R3"
    ],
    "3": [
     "R4"
    ]
   },
   "subjects": [
    "JPM"
   ]
  }
 ]
}
```
→ market [JPM] 3 line(s); issuer [JPM] 3 line(s)

## meta → sub:issuer+risk · ask
（Q01-amzn-earnings-quality seq 2）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R2",
     "anchor": "Put operating cash flow beside net income for the last eight quarters"
    },
    {
     "id": "R3",
     "anchor": "show the accruals ratio trend"
    },
    {
     "id": "R4",
     "anchor": "tell me whether receivables and inventory are growing faster than revenue over the same windows"
    }
   ],
   "lines": [
    "1. last eight fiscal quarters: operating cash flow beside net income",
    "2. last eight fiscal quarters: accruals ratio level and trend",
    "3. last eight fiscal quarters: receivables growth versus revenue growth",
    "4. last eight fiscal quarters: inventory growth versus revenue growth"
   ],
   "analyst": "issuer",
   "context": "This is for assessing whether Amazon's earnings quality is deteriorating.",
   "task_id": "tsk_d307fa9f0881",
   "line_for": {
    "1": [
     "R2",
     "R3",
     "R4"
    ],
    "2": [
     "R2",
     "R3",
     "R4"
    ],
    "3": [
     "R4"
    ],
    "4": [
     "R4"
    ]
   },
   "subjects": [
    "AMZN"
   ]
  },
  {
   "for": [
    {
     "id": "R5",
     "anchor": "and say what that means for the size of our AMZN position"
    }
   ],
   "lines": [
    "1. latest run: AMZN weight and market value in the portfolio",
    "2. latest run versus previous run: any change in AMZN weight",
    "3. latest run: what the AMZN position means for the book if earnings quality is deteriorating"
   ],
   "analyst": "risk",
   "context": "This is for judging what the earnings-quality reading means for the size of the AMZN position.",
   "task_id": "tsk_a072bf7bfa70",
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ issuer [AMZN] 4 line(s); risk [port_001] 3 line(s)

## meta → sub:risk · ask
（Q11-closest-to-issuer-limit seq 2）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R1",
     "anchor": "Which position is closest to its issuer-concentration warning"
    },
    {
     "id": "R2",
     "anchor": "how much room is left"
    },
    {
     "id": "R3",
     "anchor": "what percentage move in that name alone would take it to the breach tier with everything else fixed"
    },
    {
     "id": "R4",
     "anchor": "If we capped any single issuer at 8%, who would be over"
    }
   ],
   "lines": [
    "1. For the latest run as of 2026-09-10, give issuer weights for every holding, ordered from largest to smallest, and identify which holding is closest to its issuer-concentration warning tier.",
    "2. For the latest run as of 2026-09-10, give the room left to the issuer-concentration warning tier for that closest holding.",
    "3. For the latest run as of 2026-09-10, give the percentage move in that holding alone, with all else fixed, that would take it to the breach tier.",
    "4. For the latest run as of 2026-09-10, identify any holdings over an 8% single-issuer cap."
   ],
   "analyst": "risk",
   "context": "This determines issuer-concentration risk for the US Growth & Income Portfolio.",
   "task_id": "tsk_41f705ea4731",
   "line_for": {
    "1": [
     "R1"
    ],
    "2": [
     "R2"
    ],
    "3": [
     "R3"
    ],
    "4": [
     "R4"
    ]
   },
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ risk [port_001] 4 line(s)

## sub:issuer → check · submit
（Q01-amzn-earnings-quality seq 31）
```json
{
 "task_id": "tsk_d307fa9f0881"
}
```
→ the analyst stopped without filing a brief

## sub:issuer → ledger · boundaries
（Q01-amzn-earnings-quality seq 27）
```json
{
 "of": "analyst_budget"
}
```
→ 1 boundary row stated

## sub:issuer → store · report
（Q03-nvda-where-cash-goes seq 33）
```json
{
 "status": "verified",
 "task_id": "tsk_e101709d4877",
 "report_id": "rep_28f084fe03e7"
}
```
→ verified: 17 call(s), 2 line(s) settled

## sub:issuer → tools · calc
（Q01-amzn-earnings-quality seq 19）
```json
{
 "op": "yoy",
 "why": "Line 3 needs the receivables growth series to compare against revenue growth over the same quarter windows.",
 "inputs": [
  "f_0ee36e04fb1f"
 ]
}
```
→ r_a02ee03e62d0 calc(op="yoy", inputs=["f_0ee36e04fb1f"]) → 1 row | refused: not_a_series

## sub:issuer → tools · filings_read
（Q01-amzn-earnings-quality seq 8）
```json
{
 "why": "Line 1 needs operating cash flow for the last eight fiscal quarters to compare cash with net income.",
 "line": "operating_cash_flow",
 "last_n": 8,
 "period": {
  "quarter": "latest"
 },
 "ticker": "AMZN"
}
```
→ r_79640e9e4e8f filings_read(ticker="AMZN", line="operating_cash_flow", period={"quarter": "latest"}, last_n=8) → 1 row

## sub:issuer → tools · filings_search
（Q02-xom-room-if-oil-falls seq 9）
```json
{
 "k": 5,
 "why": "Line 4 asks for the 10-K passage on debt maturities and floating-rate exposure.",
 "form": "10-K",
 "item": "7",
 "query": "maturities floating-rate exposure debt",
 "ticker": "XOM",
 "filed_after": "2025-01-01"
}
```
→ r_d7d1426f6805 filings_search(ticker="XOM", query="maturities floating-rate exposure debt", item="7", form="10-K", filed_after="2025-01-01", k=5) → 5 rows

## sub:issuer → tools · filings_section
（Q02-xom-room-if-oil-falls seq 13）
```json
{
 "why": "Line 4 needs the surrounding 10-K text near the debt and interest-rate discussion, so I am reading the Item 7 section around the located passage.",
 "form": "10-K",
 "item": "7",
 "filing": "0000034088-26-000045",
 "offset": 84000,
 "ticker": "XOM"
}
```
→ r_f09fe595d0eb filings_section(ticker="XOM", item="7", filing="0000034088-26-000045", form="10-K", offset=84000) → 1 row

## sub:issuer → tools · list
（Q01-amzn-earnings-quality seq 4）
```json
{
 "why": "Line 1-4 need to be settled with filed-quarter measures; I need the registry names and required periods for operating cash flow, net income, accruals ratio, and the growth/lag measures.",
 "what": "metrics",
 "subject": "AMZN"
}
```
→ r_389791b4c1b2 list(what="metrics", subject="AMZN") → 34 names

## sub:issuer → tools · metric
（Q01-amzn-earnings-quality seq 6）
```json
{
 "why": "Lines 1 and 2 need the accruals ratio level and trend over the last eight fiscal quarters to assess earnings quality deterioration.",
 "name": "accruals_ratio",
 "last_n": 8,
 "subject": "AMZN"
}
```
→ r_ada767c809a3 metric(name="accruals_ratio", subject="AMZN", last_n=8) → 1 row | refused: invalid_params

## sub:issuer → worker · start
（Q02-xom-room-if-oil-falls seq 4）
```json
{
 "why": "Task lines 1-4 require current filings, measures, and 10-K text for Exxon Mobil Corporation, so I need the issuer prepared on the desk first.",
 "kind": "readiness",
 "subject": "XOM"
}
```
→ r_e9f38679d3ff start(kind="readiness", subject="XOM") → started task_c1d8dd844d88; it runs after this turn and returns nothing to it

## sub:issuer → worker · web_search
（Q14-worst-drawdown-episode seq 9）
```json
{
 "why": "Line 1 needs recent web or filing items for AAPL in the drawdown window, so search recent public items.",
 "days": 30,
 "query": "filing OR 10-K OR 10-Q OR earnings OR investor relations",
 "ticker": "AAPL"
}
```
→ r_bb5707db21df web_search(ticker="AAPL", query="filing OR 10-K OR 10-Q OR earnings OR investor relations", days=30) → 5 rows

## sub:market → check · submit
（Q06-jpm-riskier-than-a-year-ago seq 13）
```json
{
 "brief": {
  "lines": [
   {
    "n": 1,
    "why": "I can say the current 30-session volatility, but I was not given a second row for the same measure 12 months ago, so I cannot settle the comparison.",
    "settled": false,
    "boundary": "f_policy_no_estimate"
   },
   {
    "n": 2,
    "why": "I can say JPM’s current beta to SPY, but I was not given a second row for the same beta 12 months ago, so I cannot settle the comparison.",
    "settled": false,
    "boundary": "f_policy_no_estimate"
   },
   {
    "n": 3,
    "why": "I can say JPM’s current distance from the 52-week high, but I was not given a second row for the same measure 12 months ago, so I cannot settle the comparison.",
    "settled": false,
    "boundary": "f_policy_no_estimate"
   }
  ],
  "caveats": [],
  "follow_ups": [
   "Request the same three price statistics as of 2025-09-10, or the underlying daily series at that date so the desk can compute the year-ago comparisons."
  ]
 },
 "task_id": "tsk_4e5b458a0f5a",
 "coverage": {
  "asked": 3,
  "refused": 0,
  "settled": 0,
  "unsettled": 3
 }
}
```
→ accepted

## sub:market → store · report
（Q09-aapl-working-capital-cycle seq 38）
```json
{
 "status": "verified",
 "task_id": "tsk_f54f0fc5e13d",
 "report_id": "rep_152fafea1a30"
}
```
→ verified: 2 call(s), 0 line(s) settled

## sub:market → tools · list
（Q06-jpm-riskier-than-a-year-ago seq 53）
```json
{
 "why": "Task lines 1-3 require the desk's available price measures and their parameters for JPM.",
 "what": "metrics"
}
```
→ r_14822d409380 list(what="metrics") → 7 names

## sub:market → tools · metric
（Q06-jpm-riskier-than-a-year-ago seq 6）
```json
{
 "why": "Line 1 asks for 30-session volatility now; this metric gives the latest 30-session annualised volatility.",
 "name": "price.volatility",
 "params": {
  "window_days": 30
 },
 "subject": "JPM"
}
```
→ r_55c34a308f95 metric(name="price.volatility", subject="JPM", params={"window_days": 30}) → 2 rows

## sub:market → tools · prices_read
（Q06-jpm-riskier-than-a-year-ago seq 9）
```json
{
 "why": "Line 1-3 need the same price field one year ago to compare now with 12 months ago.",
 "date": "2025-09-10",
 "field": "adj_close",
 "ticker": "JPM"
}
```
→ r_fac4680a8014 prices_read(ticker="JPM", field="adj_close", date="2025-09-10") → 1 row

## sub:market → worker · start
（Q06-jpm-riskier-than-a-year-ago seq 4）
```json
{
 "why": "Line 1-3 need JPM price history and factor context; preparing the issuer so the desk can serve the requested volatility, beta, and distance-from-high measures.",
 "kind": "readiness",
 "subject": "JPM"
}
```
→ r_e385f4c012f2 start(kind="readiness", subject="JPM") → started task_02a307e2f2fa; it runs after this turn and returns nothing to it

## sub:risk → check · submit
（Q01-amzn-earnings-quality seq 42）
```json
{
 "brief": {
  "lines": [
   {
    "n": 1,
    "facts": [
     "f_220abae443ff",
     "f_435d3d2c7ab8"
    ],
    "finding": "AMZN was $756K [f_220abae443ff] and 7.03% [f_435d3d2c7ab8] of the book as of 2026-09-10.",
    "settled": true
   },
   {
    "n": 2,
    "facts": [
     "f_435d3d2c7ab8",
     "f_6a11b108a33b"
    ],
    "finding": "AMZN weight was 7.03% [f_435d3d2c7ab8] versus 7.07% [f_6a11b108a33b] on 2026-09-09, so it edged down.",
    "settled": true
   },
   {
    "n": 3,
    "why": "The desk does not hold an earnings-quality reading for AMZN here, and it does not forecast what deterioration would mean for position size.",
    "settled": false,
    "boundary": "f_policy_no_forecast"
   }
  ],
  "caveats": [],
  "follow_ups": []
 },
 "task_id": "tsk_a072bf7bfa70",
 "coverage": {
  "asked": 3,
  "refused": 0,
  "settled": 2,
  "unsettled": 1
 }
}
```
→ accepted

## sub:risk → ledger · boundaries
（Q15-liquidity-and-limits seq 25）
```json
{
 "of": "analyst_budget"
}
```
→ 1 boundary row stated

## sub:risk → store · report
（Q12-jpm-vs-peers-not-on-desk seq 48）
```json
{
 "status": "verified",
 "task_id": "tsk_1df58711d7c2",
 "report_id": "rep_480be8d27e68"
}
```
→ verified: 5 call(s), 0 line(s) settled

## sub:risk → tools · book_read
（Q01-amzn-earnings-quality seq 35）
```json
{
 "row": "AMZN",
 "why": "Line 1 asks for AMZN weight and market value in the latest run, so I’m reading the issuer exposure row for AMZN from the latest completed run.",
 "book": "run_e2945c5ebd5a",
 "table": "issuer_exposures",
 "which": "latest"
}
```
→ r_3f20b61e9d18 book_read(book="run_e2945c5ebd5a", table="issuer_exposures", row="AMZN", which="latest") → 5 rows

## sub:risk → tools · calc
（Q07-tech-cash-conversion-rank seq 60）
```json
{
 "op": "subtract",
 "why": "Serve line 1 by computing AAPL's change from the two cited weight figures instead of stating an unsourced difference.",
 "inputs": [
  "f_d24a9c0765bb",
  "f_854dd85e003c"
 ]
}
```
→ r_877e13b53212 calc(op="subtract", inputs=["f_d24a9c0765bb", "f_854dd85e003c"]) → 1 row

## sub:risk → tools · list
（Q01-amzn-earnings-quality seq 33）
```json
{
 "why": "Line 1 and 2 need the latest and prior run tables for AMZN weight and market value, so I’m checking what book rows are available for the portfolio.",
 "what": "book",
 "subject": "port_001"
}
```
→ r_f5ab04a95c44 list(what="book", subject="port_001") → 22 names

## sub:risk → tools · metric
（Q02-xom-room-if-oil-falls seq 28）
```json
{
 "why": "Line 1 needs the latest XOM weight from the latest portfolio run, and book.analysis is the run-level source for issuer weights.",
 "name": "book.analysis",
 "subject": "port_001"
}
```
→ r_b011f6120e76 metric(name="book.analysis", subject="port_001") → 47 rows | refused: withheld

## sub:risk → tools · scenario
（Q13-sell-half-nvda-into-tlt seq 6）
```json
{
 "why": "Lines 1-5 require the after-book for the exact trade: sell half of NVDA and redeploy the full proceeds into TLT, so I reprice the book and re-run checks.",
 "book": "run_74d9c5372cf7",
 "trades": [
  {
   "sell": "NVDA",
   "fraction": 0.5
  },
  {
   "buy": "TLT",
   "weight": 0.5
  }
 ],
 "funding": "proceeds"
}
```
→ r_69ae4d5dbf2d scenario(book="run_74d9c5372cf7", trades=[{"sell": "NVDA", "fraction": 0.5}, {"buy": "TLT", "weight":, funding="proceeds") → 1 row | refused: run_not_completed

## sub:risk → worker · start
（Q08-capex-roic-three-way seq 34）
```json
{
 "why": "Line 1 asks for the book's exposure to QQQ, and I need the completed run on the portfolio before reading its factor exposure.",
 "kind": "exposure_run",
 "subject": "port_001"
}
```
→ r_aae6fc388647 start(kind="exposure_run", subject="port_001") → started run_e0a212ce25ca; it runs after this turn and returns nothing to it
