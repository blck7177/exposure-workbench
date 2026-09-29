# 每种沟通的 schema：取自本轮的真实载荷

## meta → gate · answer
（Q01-amzn-earnings-quality seq 27）
```json
{
 "text": "Amazon does not look like it is deteriorating on the two quality checks the desk settled.\n\nCash from operations exceeded net income in each of the last eight quarters, so cash broadly confirmed earnings over the window. The reported quarterly cash from operations was $25.28B [f_f63a89c0b3ac], $25.97B [f_f63a89c0b3ac], $45.64B [f_f63a89c0b3ac], $17.02B [f_f63a89c0b3ac], $32.52B [f_f63a89c0b3ac], $35.52B [f_f63a89c0b3ac], $54.46B [f_f63a89c0b3ac], and $26.03B [f_f63a89c0b3ac] against net income of $13.48B [f_d9e6786eb0c8], $15.33B [f_d9e6786eb0c8], $20.00B [f_d9e6786eb0c8], $17.13B [f_d9e6786eb0c8], $18.16B [f_d9e6786eb0c8], $21.19B [f_d9e6786eb0c8], $21.19B [f_d9e6786eb0c8], and $30.25B [f_d9e6786eb0c8].\n\nThe accruals ratio was negative in six of the eight quarters and ranged from -4.10% [f_5ba9658716f0] to 0.46% [f_5ba9658716f0]. That points to cash generally running ahead of earnings, with a mixed trend rather than a steady deterioration. The quarterly series was -2.13% [f_5ba9658716f0], -1.82% [f_5ba9658716f0], -4.10% [f_5ba9658716f0], 0.02% [f_5ba9658716f0], -2.10% [f_5ba9658716f0], -1.97% [f_5ba9658716f0], -4.07% [f_5ba9658716f0], and 0.46% [f_5ba9658716f0].\n\nThe desk did not return an accepted result for the receivables-and-inventory-versus-revenue line, so I cannot responsibly say that working-capital build is or is not accelerating from the evidence that passed checks.\n\nFor the portfolio, AMZN is 7.03% [f_1d57c829a25c] of the latest US Growth & Income Portfolio run as of 2026-09-10 [f_1d57c829a25c]. The desk does not hold a rule that converts an earnings-quality thesis into a new position-size reading, so there is no desk-sanctioned numeric adjustment to the weight from this question alone.\n\nBottom line: the evidence that cleared checks says earnings quality is not clearly deteriorating; cash support is still strong, and the accruals picture is mixed rather than worsening. If you want, I can try again specifically on receivables and inventory growth versus revenue.",
 "problems": [
  {
   "rule": 1,
   "reason": "ambiguous_point",
   "sentence": "S3"
  },
  {
   "rule": 1,
   "reason": "ambiguous_point",
   "sentence": "S3"
  }
 ]
}
```
→ refused: ambiguous_point; 2 problem(s), all listed; the first: prose[1] rule 1 — ambiguous_point ('$21.19B'): this series holds the figure on several dates: write the point's bracket as the desk showed it, with its date — [f_d9e6786eb0c8@2025-09-30], [f_d9e6786eb0c8@2025-12-31]

## meta → store · open
（Q11-closest-to-issuer-limit seq 32）
```json
{
 "id": "r_d793efa35b39"
}
```
→ 3 row(s) of 3, shown [0, 3]

## meta → sub · ask
（Q02-xom-room-if-oil-falls seq 33）
```json
{
 "raw": "{\"requirements\": [{\"id\": \"R2\", \"anchor\": \"net debt to EBITDA, EBIT interest coverage and FCF to debt for the latest four quarters against the same four a year earlier\"}, {\"id\": \"R3\", \"anchor\": \"read what the 10-K says about debt maturities and floating-rate exposure\"}], \"tasks\": [{\"analyst\": \"issuer\", \"subjects\": [\"XOM\"], \"lines\": [\"quarter latest: net debt to EBITDA\", \"quarter latest: EBIT interest coverage\", \"quarter latest: free cash flow to debt\", \"quarter latest: debt maturities\", \"quarter latest: floating-rate exposure\"], \"for\": [[\"R2\"], [\"R2\"], [\"R2\"], [\"R3\"], [\"R3\"]], \"context\": \"Use the issuer\\u2019s own quarter/latest series and the 10-K passage to judge room if oil falls.\", \"follow_up_of\": \"tsk_d22e4d9241bd\"}]}"
}
```
→ invalid_delegation: the question's requirements are declared once, on the first ask; they stand as R1, R2, R3, R4 — say which of them each task is for

## meta → sub:issuer · ask
（Q02-xom-room-if-oil-falls seq 37）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R2",
     "anchor": "net debt to EBITDA, EBIT interest coverage and FCF to debt for the latest four quarters against the same four a year earlier"
    },
    {
     "id": "R3",
     "anchor": "read what the 10-K says about debt maturities and floating-rate exposure"
    }
   ],
   "lines": [
    "1. quarter latest: net debt to EBITDA",
    "2. quarter latest: EBIT interest coverage",
    "3. quarter latest: free cash flow to debt",
    "4. quarter latest: debt maturities",
    "5. quarter latest: floating-rate exposure"
   ],
   "analyst": "issuer",
   "context": "Assess Exxon’s room if oil falls and read the 10-K debt risk disclosures.",
   "task_id": "tsk_e6c596f4d669",
   "subjects": [
    "XOM"
   ],
   "follow_up_of": "tsk_d22e4d9241bd"
  }
 ]
}
```
→ issuer [XOM] 5 line(s)

## meta → sub:issuer+market · ask
（Q06-jpm-riskier-than-a-year-ago seq 2）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R1",
     "anchor": "Thirty-day volatility, beta to SPY and distance from the 52-week high now and twelve months ago"
    }
   ],
   "lines": [
    "1. 30-session volatility now versus 12 months ago",
    "2. beta to SPY now versus 12 months ago",
    "3. distance from the 52-week high now versus 12 months ago"
   ],
   "analyst": "market",
   "context": "Assess whether the market is treating JPMorgan as riskier than a year ago.",
   "task_id": "tsk_edf89cd22598",
   "subjects": [
    "JPM"
   ]
  },
  {
   "for": [
    {
     "id": "R2",
     "anchor": "interest expense and the pretax-to-net-income gap over three years"
    }
   ],
   "lines": [
    "1. interest expense over the latest three annual periods",
    "2. pretax income and net income over the latest three annual periods",
    "3. pretax income less net income over the latest three annual periods"
   ],
   "analyst": "issuer",
   "context": "Add issuer-side context for JPMorgan and note any bank-specific limits on issuer methods.",
   "task_id": "tsk_c59f7da0722d",
   "subjects": [
    "JPM"
   ]
  }
 ]
}
```
→ market [JPM] 3 line(s); issuer [JPM] 3 line(s)

## meta → sub:issuer+market+risk · ask
（Q17-events-touching-holdings seq 4）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R1",
     "anchor": "Anything in the last two weeks that touches something we hold?"
    },
    {
     "id": "R2",
     "anchor": "Search for material news on our top five by weight"
    }
   ],
   "lines": [
    "1. Top five holdings by weight in the latest run, with each name's weight",
    "2. Material news over the last two weeks touching each of the top five holdings by weight"
   ],
   "analyst": "risk",
   "context": "Book-level holdings and mandate context; the task needs the latest portfolio composition and market-relative price state for the names that matter most.",
   "task_id": "tsk_9cfd65969289",
   "subjects": [
    "port_001"
   ]
  },
  {
   "for": [
    {
     "id": "R3",
     "anchor": "for each say whether the price already moved: ten-day window return against SPY and distance from the 52-week high"
    }
   ],
   "lines": [
    "1. Each name's 10-session return versus SPY over the last two weeks",
    "2. Each name's distance from the 52-week high as of the latest close"
   ],
   "analyst": "market",
   "context": "To judge whether the market has already priced the last two weeks' news for the names held in the portfolio.",
   "task_id": "tsk_4266993ab1eb",
   "subjects": [
    "AAPL",
    "JPM",
    "LLY",
    "MSFT",
    "GOOGL",
    "AMZN",
    "HYG",
    "TLT",
    "XOM",
    "NVDA"
   ]
  },
  {
   "for": [
    {
     "id": "R1",
     "anchor": "Anything in the last two weeks that touches something we hold?"
    },
    {
     "id": "R2",
     "anchor": "Search for material news on our top five by weight"
    }
   ],
   "lines": [
    "1. Material news over the last two weeks touching each name held in the portfolio"
   ],
   "analyst": "issuer",
   "context": "Issuer-level news on the held names over the last two weeks; only the held names with accessible coverage are relevant.",
   "task_id": "tsk_f3a85d65af01",
   "subjects": [
    "AAPL",
    "JPM",
    "LLY",
    "MSFT",
    "GOOGL",
    "AMZN",
    "HYG",
    "TLT",
    "XOM",
    "NVDA"
   ]
  }
 ]
}
```
→ risk [port_001] 2 line(s); market [AAPL,JPM,LLY,MSFT,GOOGL,AMZN,HYG,TLT,XOM,NVDA] 2 line(s); issuer [AAPL,JPM,LLY,MSFT,GOOGL,AMZN,HYG,TLT,XOM,NVDA] 1 line(s)

## meta → sub:issuer+risk · ask
（Q01-amzn-earnings-quality seq 2）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R1",
     "anchor": "operating cash flow beside net income for the last eight quarters"
    },
    {
     "id": "R2",
     "anchor": "show the accruals ratio trend"
    },
    {
     "id": "R3",
     "anchor": "whether receivables and inventory are growing faster than revenue over the same windows"
    }
   ],
   "lines": [
    "1. Operating cash flow beside net income for each of the last eight quarters; cash from operations set against net income",
    "2. Accruals ratio trend for each of the last eight quarters",
    "3. Receivables growth and inventory growth versus revenue growth for each of the last eight quarters"
   ],
   "analyst": "issuer",
   "context": "Assess whether Amazon's earnings quality is deteriorating from its filed cash flow, earnings, and working-capital lines.",
   "task_id": "tsk_2d833e580b2c",
   "line_for": {
    "1": [
     "R1"
    ],
    "2": [
     "R2"
    ],
    "3": [
     "R3"
    ]
   },
   "subjects": [
    "AMZN"
   ]
  },
  {
   "for": [
    {
     "id": "R4",
     "anchor": "what that means for the size of our AMZN position"
    }
   ],
   "lines": [
    "1. AMZN weight in the US Growth & Income Portfolio as of the latest run",
    "2. Whether an earnings-quality deterioration thesis would change the reading for the size of the AMZN position"
   ],
   "analyst": "risk",
   "context": "Translate the issuer read into portfolio impact for the held AMZN position.",
   "task_id": "tsk_4136054c335d",
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ issuer [AMZN] 3 line(s); risk [port_001] 2 line(s)

## meta → sub:market · ask
（Q09-aapl-working-capital-cycle seq 68）
```json
{
 "tasks": [
  {
   "for": [
    {
     "id": "R2",
     "anchor": "Where is the cycle now against its three-year low and high,"
    }
   ],
   "lines": [
    "1. cash conversion cycle, three-year low and high, and where the latest reading sits within that range"
   ],
   "analyst": "market",
   "context": "Apple Inc.; the user needs the current cash conversion cycle positioned against its three-year low and high.",
   "task_id": "tsk_f7d144d4a585",
   "subjects": [
    "AAPL"
   ]
  }
 ]
}
```
→ market [AAPL] 1 line(s)

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
    "1. As of run_e2945c5ebd5a, what is the book's issuer-concentration warning tier and breach tier, and which holding is closest to the warning tier?",
    "2. As of run_e2945c5ebd5a, how much room is left from that holding to the warning tier?",
    "3. As of run_e2945c5ebd5a, what percentage move in that holding alone, with all else fixed, would take it to the breach tier?",
    "4. As of run_e2945c5ebd5a, if any single issuer were capped at 8%, which holdings would be over the cap?"
   ],
   "analyst": "risk",
   "context": "This is for issuer-concentration monitoring on the US Growth & Income Portfolio.",
   "task_id": "tsk_08d7326f5f5f",
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ risk [port_001] 4 line(s)

## sub:issuer → check · submit
（Q01-amzn-earnings-quality seq 15）
```json
{
 "brief": {
  "lines": [
   {
    "n": 1,
    "facts": [
     "f_f63a89c0b3ac",
     "f_d9e6786eb0c8"
    ],
    "finding": "Cash from operations exceeded net income in each of the last eight quarters, so cash broadly confirmed earnings over the window. The gap was largest in 2024-12-31 and 2025-12-31, but both operating cash flow and net income remained strongly positive throughout.",
    "settled": true
   },
   {
    "n": 2,
    "facts": [
     "f_5ba9658716f0",
     "f_d182784df95a"
    ],
    "finding": "Amazon's accruals ratio stayed negative in six of the eight quarters, ranging from -4.10% [f_5ba9658716f0] to 0.46% [f_5ba9658716f0], which points to cash generally running ahead of earnings. The series improved sharply around 2025-03-31, then turned back positive at 2026-03-31, so the trend is mixed rather than steadily worsening.",
    "settled": true
   },
   {
    "n": 3,
    "why": "The receivables and inventory series were not available in the requested quarterly balance-series form, so I cannot compare their growth with revenue growth over the last eight quarters.",
    "settled": false,
    "boundary": "f_bdf511293170"
   }
  ],
  "caveats": [],
  "follow_ups": []
 },
 "task_id": "tsk_2d833e580b2c",
 "coverage": {
  "asked": 3,
  "refused": 1,
  "settled": 2,
  "unsettled": 0
 },
 "problems": [
  {
   "n": 3,
   "id": "f_bdf511293170",
   "where": "line 3",
   "reason": "not_a_boundary",
   "way_out": "f_bdf511293170 is not an absence row the desk showed you: point at the row that says what could not be done, or at the policy that stops the line"
  }
 ]
}
```
→ refused: 1 problem(s); not_a_boundary

## sub:issuer → ledger · boundaries
（Q03-nvda-where-cash-goes seq 25）
```json
{
 "of": "analyst_budget"
}
```
→ 1 boundary row stated

## sub:issuer → store · report
（Q01-amzn-earnings-quality seq 18）
```json
{
 "status": "refused",
 "task_id": "tsk_2d833e580b2c",
 "report_id": "rep_3a79a4f057fe"
}
```
→ refused: 8 call(s), 2 line(s) settled

## sub:issuer → tools · calc
（Q01-amzn-earnings-quality seq 12）
```json
{
 "op": "yoy",
 "why": "Line 3 needs revenue growth across the quarterly series so receivables and inventory growth can be compared against it.",
 "inputs": [
  "f_f48ce0d83af0"
 ]
}
```
→ r_2270f8fa366f calc(op="yoy", inputs=["f_f48ce0d83af0"]) → 1 row

## sub:issuer → tools · filings_read
（Q01-amzn-earnings-quality seq 5）
```json
{
 "why": "Line 1 needs operating cash flow for each of the last eight quarters so cash can be set beside net income.",
 "line": "operating_cash_flow",
 "last_n": 8,
 "period": {
  "quarter": "latest"
 },
 "ticker": "AMZN"
}
```
→ r_a37c0557cfc0 filings_read(ticker="AMZN", line="operating_cash_flow", period={"quarter": "latest"}, last_n=8) → 1 row

## sub:issuer → tools · filings_search
（Q02-xom-room-if-oil-falls seq 10）
```json
{
 "k": 5,
 "why": "Line 4 and 5: find the 10-K passages on debt maturities and floating-rate exposure so the answer can be quoted verbatim.",
 "form": "10-K",
 "item": "7",
 "query": "maturities floating-rate exposure debt maturities floating-rate",
 "ticker": "XOM",
 "filed_after": "2025-01-01"
}
```
→ r_bad54fe98274 filings_search(ticker="XOM", query="maturities floating-rate exposure debt maturities floating-, item="7", form="10-K", filed_after="2025-01-01", k=5) → 5 rows

## sub:issuer → tools · filings_section
（Q02-xom-room-if-oil-falls seq 14）
```json
{
 "why": "Line 4 and 5: read the Item 7 passage around the identified market-risk and debt-related disclosure to capture the needed exact wording.",
 "form": "10-K",
 "item": "7",
 "filing": "0000034088-26-000045",
 "offset": 87601,
 "ticker": "XOM"
}
```
→ r_7189867840ff filings_section(ticker="XOM", item="7", filing="0000034088-26-000045", form="10-K", offset=87601) → 1 row

## sub:issuer → tools · list
（Q03-nvda-where-cash-goes seq 4）
```json
{
 "why": "Line 3 needs the latest filing item that may state remaining share repurchase authorization, so I first check what filings and Items are available.",
 "what": "filings",
 "subject": "NVDA"
}
```
→ r_eb19c3be7ea4 list(what="filings", subject="NVDA") → 4 names

## sub:issuer → tools · metric
（Q01-amzn-earnings-quality seq 4）
```json
{
 "why": "Line 2 needs the accruals ratio trend for the last eight quarters, and this measure gives that series directly.",
 "name": "accruals_ratio",
 "last_n": 8,
 "period": {
  "quarter": "latest"
 },
 "subject": "AMZN"
}
```
→ r_94acfd50c053 metric(name="accruals_ratio", subject="AMZN", period={"quarter": "latest"}, last_n=8) → 1 row

## sub:issuer → worker · web_search
（Q17-events-touching-holdings seq 41）
```json
{
 "why": "Line 1 asks for material news touching each held name; I need recent web coverage for AAPL.",
 "days": 14,
 "query": "material news last two weeks",
 "ticker": "AAPL"
}
```
→ r_9454d827354d web_search(ticker="AAPL", query="material news last two weeks", days=14) → 5 rows

## sub:market → check · submit
（Q06-jpm-riskier-than-a-year-ago seq 12）
```json
{
 "brief": {
  "lines": [
   {
    "n": 1,
    "why": "I can report JPM's current 30-session volatility, but the desk did not compute a year-ago volatility reading to compare it with, so the line cannot be settled from the rows on hand.",
    "settled": false,
    "boundary": "f_0ffb124064d5"
   },
   {
    "n": 2,
    "why": "I can report that JPM's beta to SPY was not computed because the desk only has 22 aligned observations, so there is no current beta or year-ago beta to compare.",
    "settled": false,
    "boundary": "f_0ffb124064d5"
   },
   {
    "n": 3,
    "why": "I can report JPM's current distance from the 52-week high, but the desk did not provide a year-ago reading for the same measure, so the comparison cannot be made.",
    "settled": false,
    "boundary": "f_c5908ef0a250"
   }
  ],
  "caveats": [],
  "follow_ups": [
   "Compute JPM volatility and beta as of 2025-09-10 from the historical price series, if the desk can access enough aligned returns.",
   "Compute JPM distance from the 52-week high as of 2025-09-10 for the same one-year-ago comparison."
  ]
 },
 "task_id": "tsk_edf89cd22598",
 "coverage": {
  "asked": 3,
  "refused": 2,
  "settled": 0,
  "unsettled": 1
 },
 "problems": [
  {
   "n": 2,
   "at": "prose[0]",
   "rule": 1,
   "where": "line 2 / why",
   "figure": "22",
   "reason": "unpointed_figure",
   "channel": "why",
   "way_out": "a figure the desk showed is written as shown, followed by its id in brackets (16.0% [f_…]); the desk showed this figure under the ids listed",
   "sentence": "S1",
   "candidates": [
    {
     "id": "f_8b665d381214",
     "as_of": "n/a",
     "measure": "have",
     "subject": "JPM"
    }
   ]
  },
  {
   "n": 3,
   "id": "f_c5908ef0a250",
   "where": "line 3",
   "reason": "not_a_boundary",
   "way_out": "f_c5908ef0a250 is not an absence row the desk showed you: point at the row that says what could not be done, or at the policy that stops the line"
  }
 ]
}
```
→ refused: 2 problem(s); unpointed_figure

## sub:market → store · report
（Q06-jpm-riskier-than-a-year-ago seq 15）
```json
{
 "status": "refused",
 "task_id": "tsk_edf89cd22598",
 "report_id": "rep_2f4f64da53d8"
}
```
→ refused: 5 call(s), 0 line(s) settled

## sub:market → tools · list
（Q06-jpm-riskier-than-a-year-ago seq 8）
```json
{
 "why": "Line 1-3: inspect the held price span so I can ask for the prior-year date or determine whether the current metric can be compared to a year-ago reading.",
 "what": "prices",
 "subject": "JPM"
}
```
→ r_6c6b231f4259 list(what="prices", subject="JPM") → 1 name

## sub:market → tools · metric
（Q06-jpm-riskier-than-a-year-ago seq 4）
```json
{
 "why": "Line 1: need JPM's current 30-session volatility as one side of the now-versus-12-months-ago comparison.",
 "name": "price.volatility",
 "params": {
  "window_days": 30
 },
 "subject": "JPM"
}
```
→ r_ed2bbea7f266 metric(name="price.volatility", subject="JPM", params={"window_days": 30}) → 2 rows

## sub:market → tools · prices_read
（Q06-jpm-riskier-than-a-year-ago seq 10）
```json
{
 "why": "Line 1-3: pull the adjusted close exactly one year earlier to anchor year-ago volatility, beta, and 52-week-high context.",
 "date": "2025-09-10",
 "field": "adj_close",
 "ticker": "JPM"
}
```
→ r_f3f55d5b622f prices_read(ticker="JPM", field="adj_close", date="2025-09-10") → 1 row

## sub:risk → check · submit
（Q01-amzn-earnings-quality seq 24）
```json
{
 "brief": {
  "lines": [
   {
    "n": 1,
    "facts": [
     "f_1d57c829a25c"
    ],
    "finding": "AMZN is 7.03% [f_1d57c829a25c] of the latest run of the US Growth & Income Portfolio as of 2026-09-10 [f_1d57c829a25c].",
    "settled": true
   },
   {
    "n": 2,
    "why": "The desk holds the AMZN size reading, but it does not hold an earnings-quality thesis measure or a rule that translates such a thesis into a different position-size reading.",
    "settled": false,
    "boundary": "f_policy_no_estimate"
   }
  ],
  "caveats": [],
  "follow_ups": [
   "If you want the portfolio impact framed numerically, ask for the current AMZN weight against a specific held risk measure the desk does hold, such as beta, volatility, or contribution."
  ]
 },
 "task_id": "tsk_4136054c335d",
 "coverage": {
  "asked": 2,
  "refused": 0,
  "settled": 1,
  "unsettled": 1
 }
}
```
→ accepted

## sub:risk → ledger · boundaries
（Q07-tech-cash-conversion-rank seq 50）
```json
{
 "of": "analyst_budget"
}
```
→ 1 boundary row stated

## sub:risk → store · report
（Q01-amzn-earnings-quality seq 25）
```json
{
 "status": "verified",
 "task_id": "tsk_4136054c335d",
 "report_id": "rep_92a22cac934c"
}
```
→ verified: 2 call(s), 1 line(s) settled

## sub:risk → tools · book_read
（Q01-amzn-earnings-quality seq 20）
```json
{
 "row": "AMZN",
 "why": "Line 1 needs the latest AMZN weight in the portfolio, and this reads the held issuer exposure directly from the latest completed run.",
 "book": "port_001",
 "table": "issuer_exposures",
 "which": "latest"
}
```
→ r_8a07ed976f0f book_read(book="port_001", table="issuer_exposures", row="AMZN", which="latest") → 5 rows

## sub:risk → tools · calc
（Q07-tech-cash-conversion-rank seq 80）
```json
{
 "op": "subtract",
 "why": "Line 2 needs the change in AAPL book weight since the prior run, so I subtract the prior weight from the latest weight.",
 "inputs": [
  "f_8dd01b42bc82",
  "f_7de5bc1f9f43"
 ]
}
```
→ r_d3bfe8db00f9 calc(op="subtract", inputs=["f_8dd01b42bc82", "f_7de5bc1f9f43"]) → 1 row

## sub:risk → tools · list
（Q01-amzn-earnings-quality seq 22）
```json
{
 "why": "Line 2 needs to know whether the desk holds the issuer read or only the portfolio, so I check the available book tables and rows before trying to translate any thesis into a size reading.",
 "what": "book",
 "subject": "port_001"
}
```
→ r_37f5e22c2e4c list(what="book", subject="port_001") → 22 names

## sub:risk → tools · metric
（Q02-xom-room-if-oil-falls seq 28）
```json
{
 "why": "Line 2 asks for the book beta to USO in the latest run; this measures XOM's sensitivity to the oil ETF proxy named in the context, which is the closest available issuer-level sensitivity.",
 "name": "price.beta",
 "params": {
  "window": "1y",
  "benchmark": "USO"
 },
 "subject": "XOM"
}
```
→ r_592b554b184a metric(name="price.beta", subject="XOM", params={"benchmark": "USO", "window": "1y"}) → 5 rows

## sub:risk → tools · scenario
（Q13-sell-half-nvda-into-tlt seq 15）
```json
{
 "why": "Line 1 and 2 require the book after selling half of NVDA and reallocating the proceeds to TLT, so I need a re-priced after-book to read its post-trade exposures and checks.",
 "book": "run_e2945c5ebd5a",
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
→ r_b2fc9f015cee scenario(book="run_e2945c5ebd5a", trades=[{"sell": "NVDA", "fraction": 0.5}, {"buy": "TLT", "weight":, funding="proceeds") → 1 row | refused: insufficient_proceeds
