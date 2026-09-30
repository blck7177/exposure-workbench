# 每种沟通的 schema：取自本轮的真实载荷

## meta → gate · answer
（X01-largest-weight-then-its-cash seq 25）
```json
{
 "text": "MSFT [f_02b57c2dc359] is the largest holding in the book.\n\nFor MSFT, capex intensity was 13.3% [f_93c4ac41fe10] in 2023-06-30, 18.1% [f_93c4ac41fe10] in 2024-06-30, and 22.9% [f_93c4ac41fe10] in 2025-06-30. Free cash flow margin was 28.1% [f_dc694ef6e9a2] in 2023-06-30, 30.2% [f_dc694ef6e9a2] in 2024-06-30, and 25.4% [f_dc694ef6e9a2] in 2025-06-30. EBIT / interest coverage was 52.84× [f_efee41d31b7e] for 2024-07-01 to 2025-06-30.\n\nThat says cash is being pushed more into capital expenditure over the three years, while free cash flow margin remains healthy but has eased in the latest year. Interest coverage is very strong, so the company covers its interest many times over."
}
```
→ accepted

## meta → store · open
（X02-weakest-fcf-margin-then-sell-it seq 118）
```json
{
 "id": "rep_ac4cca916642"
}
```
→ unknown_id: open takes the id of a row (f_…), a call (r_…), a task, or a built book (calc_…)

## meta → sub · ask
（X02-weakest-fcf-margin-then-sell-it seq 83）
```json
{
 "raw": "{\"tasks\": [{\"analyst\": \"risk\", \"subjects\": [\"port_001\"], \"lines\": [\"current Technology sector weight\", \"book after removing AAPL entirely\", \"book after removing MSFT entirely\", \"book after removing NVDA entirely\"], \"context\": \"Assess how selling one technology holding entirely changes the Technology sector weight.\"}, {\"analyst\": \"risk\", \"subjects\": [\"port_001\"], \"lines\": [\"largest name weight and its rank\", \"top three name concentration and its change since the prior run\", \"nearest concentration check and the room left to it\", \"every concentration check against its warning and breach tiers\"], \"context\": \"Assess which concentration checks loosen or tighten after removing one technology holding entirely.\"}]}"
}
```
→ invalid_delegation: the risk analyst is asked twice about port_001 in one call; put every line for them in one task

## meta → sub:issuer · ask
（X01-largest-weight-then-its-cash seq 12）
```json
{
 "tasks": [
  {
   "lines": [
    "1. Capital expenditure as a share of revenue for each of the last three fiscal years",
    "2. Free cash flow margin for each of the last three fiscal years",
    "3. Interest coverage for the latest fiscal year"
   ],
   "analyst": "issuer",
   "context": "Use the top-weight holding from the portfolio to assess where cash is going and whether earnings cover interest.",
   "task_id": "tsk_abba43ffc080",
   "subjects": [
    "MSFT"
   ],
   "follow_up_of": "tsk_e02eb613af86"
  }
 ]
}
```
→ issuer [MSFT] 3 line(s)

## meta → sub:issuer+market · ask
（X03-furthest-below-high-then-filings seq 61）
```json
{
 "tasks": [
  {
   "lines": [
    "1. Rank the held equity issuers by price.distance_from_52w_high using the existing rows from the prior task, lowest distance to highest distance, and identify the furthest below its 52-week high",
    "2. Give the ranked row id for each holding in that ordering"
   ],
   "analyst": "market",
   "context": "Need the deepest drawdown holding with desk-computed rank to answer the superlative correctly.",
   "task_id": "tsk_2a9c540e892f",
   "subjects": [
    "port_001"
   ],
   "follow_up_of": "tsk_853ce1dd0c04"
  },
  {
   "lines": [
    "1. For the eventual top-ranked holding only, latest 10-K and latest 10-Q risk-factor language on what can go wrong, quoted from the filing",
    "2. For the eventual top-ranked holding only, operating margin for the latest four reported quarters and whether the margin has slipped over that span"
   ],
   "analyst": "issuer",
   "context": "Need the issuer risk text and operating-margin trend for whichever holding is furthest below its 52-week high.",
   "task_id": "tsk_b897fa43b698",
   "subjects": [
    "AAPL",
    "AMZN",
    "GOOGL",
    "JPM",
    "LLY",
    "MSFT",
    "NVDA",
    "XOM"
   ],
   "follow_up_of": "tsk_c7aebd2e9228"
  }
 ]
}
```
→ market [port_001] 2 line(s); issuer [AAPL,AMZN,GOOGL,JPM,LLY,MSFT,NVDA,XOM] 2 line(s)

## meta → sub:market · ask
（X03-furthest-below-high-then-filings seq 2）
```json
{
 "tasks": [
  {
   "lines": [
    "1. For each equity holding in the US Growth & Income Portfolio as of the latest run, distance from the 52-week high and rank them from furthest below to nearest"
   ],
   "analyst": "market",
   "context": "Identify which holding sits furthest below its 52-week high.",
   "task_id": "tsk_853ce1dd0c04",
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ market [port_001] 1 line(s)

## meta → sub:risk · ask
（X01-largest-weight-then-its-cash seq 2）
```json
{
 "tasks": [
  {
   "lines": [
    "1. Largest holding by weight in the latest book",
    "2. Largest holding by weight and its rank in the latest book"
   ],
   "analyst": "risk",
   "context": "Identify the top-weight holding in the portfolio before asking issuer fundamentals for that company.",
   "task_id": "tsk_e02eb613af86",
   "subjects": [
    "port_001"
   ]
  }
 ]
}
```
→ risk [port_001] 2 line(s)

## sub:issuer → check · submit
（X01-largest-weight-then-its-cash seq 20）
```json
{
 "notes": [],
 "result": {
  "detail": "accepted items are kept; repair or withdraw the named notes, then submit again",
  "accepted": false,
  "evidence": [
   "f_02b57c2dc359",
   "f_93c4ac41fe10",
   "f_dc694ef6e9a2",
   "f_efee41d31b7e"
  ],
  "note_ids": [
   {
    "id": "nte_4467c24c1c72",
    "index": 0
   }
  ],
  "problems": [
   {
    "at": "prose[0]",
    "item": "nte_4467c24c1c72",
    "rule": 2,
    "word": "largest",
    "where": "finding",
    "linked": [
     "f_02b57c2dc359"
    ],
    "reason": "superlative_without_rank",
    "channel": "finding",
    "way_out": "this figure holds no such place in an ordering the desk built — have the figures ranked and point at the ranked row, or drop the word",
    "sentence": "S1",
    "candidates": []
   }
  ],
  "kept_notes": []
 },
 "task_id": "tsk_abba43ffc080",
 "problems": [
  {
   "at": "prose[0]",
   "item": "nte_4467c24c1c72",
   "rule": 2,
   "word": "largest",
   "where": "finding",
   "linked": [
    "f_02b57c2dc359"
   ],
   "reason": "superlative_without_rank",
   "channel": "finding",
   "way_out": "this figure holds no such place in an ordering the desk built — have the figures ranked and point at the ranked row, or drop the word",
   "sentence": "S1",
   "candidates": []
  }
 ],
 "protocol": "evidence-v2",
 "submission": {
  "notes": [
   {
    "refs": [
     "f_02b57c2dc359",
     "f_93c4ac41fe10",
     "f_dc694ef6e9a2",
     "f_efee41d31b7e"
    ],
    "text": "MSFT carries the largest weight in the book at 16.0% [f_02b57c2dc359]. For MSFT, capex intensity was 13.3% [f_93c4ac41fe10] in 2023-06-30, 18.1% [f_93c4ac41fe10] in 2024-06-30, and 22.9% [f_93c4ac41fe10] in 2025-06-30. Free cash flow margin was 28.1% [f_dc694ef6e9a2] in 2023-06-30, 30.2% [f_dc694ef6e9a2] in 2024-06-30, and 25.4% [f_dc694ef6e9a2] in 2025-06-30. EBIT / interest coverage was 52.84× [f_efee41d31b7e] for 2024-07-01 to 2025-06-30."
   }
  ],
  "evidence": [
   "f_02b57c2dc359",
   "f_93c4ac41fe10",
   "f_dc694ef6e9a2",
   "f_efee41d31b7e"
  ]
 }
}
```
→ refused: 1 problem(s); superlative_without_rank

## sub:issuer → ledger · boundaries
（X02-weakest-fcf-margin-then-sell-it seq 70）
```json
{}
```
→ r_0b1a97521396 metric(name="operating_cash_flow", subject="NVDA", period={"fy": 2025}) → 1 row | refused: invalid_arguments

## sub:issuer → store · report
（X01-largest-weight-then-its-cash seq 23）
```json
{
 "status": "stopped",
 "task_id": "tsk_abba43ffc080",
 "protocol": "evidence-v2",
 "report_id": "rep_5e2adf10b650",
 "stop_reason": "submission_rejected"
}
```
→ 5 evidence rows; 1 checked notes; submission_rejected

## sub:issuer → tools · calc
（X02-weakest-fcf-margin-then-sell-it seq 22）
```json
{
 "op": "subtract",
 "why": "Need the post-sale Apple weight change; if one position is removed entirely, its weight is the amount that leaves the sector sleeve.",
 "factor": null,
 "inputs": [
  "f_374b6e469258"
 ]
}
```
→ r_b6e27640f854 calc(op="subtract", inputs=["f_374b6e469258"]) → 1 row | refused: operands

## sub:issuer → tools · filings_read
（X02-weakest-fcf-margin-then-sell-it seq 6）
```json
{
 "why": "Need fiscal 2025 revenue to support the free cash flow share comparison.",
 "line": "revenue",
 "period": {
  "fy": 2025
 },
 "ticker": [
  "AAPL",
  "MSFT",
  "NVDA"
 ]
}
```
→ r_7024c78acf31 filings_read(ticker=["AAPL", "MSFT", "NVDA"], line="revenue", period={"fy": 2025}) → 3 rows | refused: window_not_derivable

## sub:issuer → tools · filings_search
（X02-weakest-fcf-margin-then-sell-it seq 11）
```json
{
 "k": 3,
 "why": "Need Apple's filing wording for the free cash flow definition used in fiscal 2025.",
 "form": "10-K",
 "item": "8",
 "query": "free cash flow operating cash flow capital expenditures",
 "ticker": "AAPL",
 "filed_after": "2025-01-01"
}
```
→ r_61d62ff367e3 filings_search(ticker="AAPL", query="free cash flow operating cash flow capital expenditures", item="8", form="10-K", filed_after="2025-01-01", k=3) → 3 rows

## sub:issuer → tools · filings_section
（X02-weakest-fcf-margin-then-sell-it seq 16）
```json
{
 "why": "Need to inspect NVIDIA Item 8 directly because the search did not surface the relevant cash flow lines.",
 "item": "8",
 "filing": "0001045810-26-000021",
 "offset": 0,
 "ticker": "NVDA"
}
```
→ r_5ca6df35f981 filings_section(ticker="NVDA", item="8", filing="0001045810-26-000021", offset=0) → 1 row

## sub:issuer → tools · list
（X02-weakest-fcf-margin-then-sell-it seq 4）
```json
{
 "why": "Need the free cash flow and sector weight/concentration measures available before comparing the three holdings and portfolio effects.",
 "what": "metrics"
}
```
→ r_39eb567d9a80 list(what="metrics") → 34 names

## sub:issuer → tools · metric
（X01-largest-weight-then-its-cash seq 14）
```json
{
 "why": "Need capital expenditure as a share of revenue for each of the last three fiscal years for the top-weight holding.",
 "name": "capex_intensity",
 "last_n": 3,
 "subject": "MSFT"
}
```
→ r_dc0057501394 metric(name="capex_intensity", subject="MSFT", last_n=3) → 1 row | refused: invalid_params

## sub:issuer → worker · web_search
（X03-furthest-below-high-then-filings seq 37）
```json
{
 "why": "Find recent web item on price relative to 52-week high to identify the holding furthest below its high.",
 "days": 30,
 "query": "52-week high current price drawdown latest",
 "ticker": "AAPL"
}
```
→ r_d23157420d3e web_search(ticker="AAPL", query="52-week high current price drawdown latest", days=30) → 5 rows

## sub:market → check · submit
（X03-furthest-below-high-then-filings seq 25）
```json
{
 "notes": [],
 "result": {
  "detail": "accepted items are kept; repair or withdraw the named notes, then submit again",
  "accepted": false,
  "evidence": [
   "f_bcee1f55e854",
   "f_11295427ffa8",
   "f_afa7c133a093",
   "f_c35fbff4bcb8",
   "f_b86a120050a2",
   "f_1dcd502a794a",
   "f_ad09a892a678",
   "f_aa6ff0114cb1"
  ],
  "note_ids": [
   {
    "id": "nte_f5cdb50aff6d",
    "index": 0
   }
  ],
  "problems": [
   {
    "at": "prose[0]",
    "item": "nte_f5cdb50aff6d",
    "rule": 2,
    "word": "furthest",
    "where": "finding",
    "linked": [
     "f_bcee1f55e854"
    ],
    "reason": "superlative_without_rank",
    "channel": "finding",
    "way_out": "this figure holds no such place in an ordering the desk built — have the figures ranked and point at the ranked row, or drop the word",
    "sentence": "S1",
    "candidates": []
   }
  ],
  "kept_notes": []
 },
 "task_id": "tsk_853ce1dd0c04",
 "problems": [
  {
   "at": "prose[0]",
   "item": "nte_f5cdb50aff6d",
   "rule": 2,
   "word": "furthest",
   "where": "finding",
   "linked": [
    "f_bcee1f55e854"
   ],
   "reason": "superlative_without_rank",
   "channel": "finding",
   "way_out": "this figure holds no such place in an ordering the desk built — have the figures ranked and point at the ranked row, or drop the word",
   "sentence": "S1",
   "candidates": []
  }
 ],
 "protocol": "evidence-v2",
 "submission": {
  "notes": [
   {
    "refs": [
     "f_bcee1f55e854",
     "f_11295427ffa8",
     "f_afa7c133a093",
     "f_c35fbff4bcb8",
     "f_b86a120050a2",
     "f_ad09a892a678",
     "f_1dcd502a794a",
     "f_aa6ff0114cb1"
    ],
    "text": "Among the equity holdings, GOOGL sits furthest below its 52-week high at -17.3% [f_bcee1f55e854]. The full equity ordering from furthest below to nearest is GOOGL, LLY, AMZN, MSFT, NVDA, AAPL, JPM, XOM [f_bcee1f55e854][f_11295427ffa8][f_afa7c133a093][f_c35fbff4bcb8][f_b86a120050a2][f_ad09a892a678][f_1dcd502a794a][f_aa6ff0114cb1]."
   }
  ],
  "evidence": [
   "f_bcee1f55e854",
   "f_11295427ffa8",
   "f_afa7c133a093",
   "f_c35fbff4bcb8",
   "f_b86a120050a2",
   "f_1dcd502a794a",
   "f_ad09a892a678",
   "f_aa6ff0114cb1"
  ]
 }
}
```
→ refused: 1 problem(s); superlative_without_rank

## sub:market → store · report
（X03-furthest-below-high-then-filings seq 31）
```json
{
 "status": "stopped",
 "task_id": "tsk_853ce1dd0c04",
 "protocol": "evidence-v2",
 "report_id": "rep_4169ccd143f9",
 "stop_reason": "submission_rejected"
}
```
→ 25 evidence rows; 1 checked notes; submission_rejected

## sub:market → tools · calc
（X03-furthest-below-high-then-filings seq 27）
```json
{
 "op": "rank",
 "why": "Build the desk-computed ordering of the equity holdings by distance from 52-week high so the superlative can be stated with its rank.",
 "inputs": [
  "f_bcee1f55e854",
  "f_11295427ffa8",
  "f_afa7c133a093",
  "f_c35fbff4bcb8",
  "f_b86a120050a2",
  "f_ad09a892a678",
  "f_1dcd502a794a",
  "f_aa6ff0114cb1"
 ],
 "direction": "lowest"
}
```
→ r_0a69208540b2 calc(op="rank", inputs=["f_bcee1f55e854", "f_11295427ffa8", "f_afa7c133a093", "f_c3, direction="lowest") → 9 rows

## sub:market → tools · list
（X03-furthest-below-high-then-filings seq 4）
```json
{
 "why": "Identify the available portfolio-level and holding-level measures needed to answer the 52-week-high ranking and later operating-margin question.",
 "what": "metrics",
 "subject": "port_001"
}
```
→ r_63eff3da3f47 list(what="metrics", subject="port_001") → 7 names

## sub:market → tools · metric
（X03-furthest-below-high-then-filings seq 6）
```json
{
 "why": "Measure each equity holding’s distance from its 52-week high so the holdings can be ranked from furthest below to nearest.",
 "name": "price.distance_from_52w_high",
 "subject": [
  "AAPL",
  "JPM",
  "LLY",
  "MSFT",
  "GOOGL",
  "AMZN",
  "XOM",
  "NVDA"
 ]
}
```
→ r_f1d0e69b83e5 metric(name="price.distance_from_52w_high", subject=["AAPL", "JPM", "LLY", "MSFT", "GOOGL", "AMZN", "XOM", "NVDA) → 16 rows

## sub:market → tools · prices_read
（X07-drawdown-repeated-in-dollars seq 8）
```json
{
 "why": "Get the adjusted close at the requested date so I can connect the drawdown percentage to the current position value basis if needed.",
 "date": "2026-09-10",
 "field": "adj_close",
 "ticker": "NVDA"
}
```
→ r_d314988cc8f9 prices_read(ticker="NVDA", field="adj_close", date="2026-09-10") → 1 row

## sub:risk → check · submit
（X01-largest-weight-then-its-cash seq 9）
```json
{
 "notes": [
  {
   "id": "nte_c99c9a458965",
   "refs": [
    "f_02b57c2dc359"
   ],
   "text": "MSFT is the largest holding by weight in the latest book, and it is ranked 1st by weight in the latest issuer exposures.",
   "blocks": [
    {
     "runs": [
      "MSFT is the largest holding by weight in the latest book, and it is ranked 1st by weight in the latest issuer exposures."
     ],
     "type": "paragraph"
    }
   ],
   "raw_text": "MSFT is the largest holding by weight in the latest book, and it is ranked 1st by weight in the latest issuer exposures.",
   "verified": {
    "figures": 0,
    "matches": [],
    "sources": 0,
    "sentences": {
     "checked": 0,
     "judgement": [
      "MSFT is the largest holding by weight in the latest book, and it is ranked 1st by weight in the latest issuer exposures."
     ],
     "unchecked": 1
    }
   }
  }
 ],
 "result": {
  "detail": "work returned",
  "accepted": true,
  "evidence": [
   "f_02b57c2dc359"
  ],
  "note_ids": [
   {
    "id": "nte_c99c9a458965",
    "index": 0
   }
  ],
  "problems": [],
  "kept_notes": [
   "nte_c99c9a458965"
  ]
 },
 "task_id": "tsk_e02eb613af86",
 "problems": [],
 "protocol": "evidence-v2",
 "submission": {
  "notes": [
   {
    "refs": [
     "f_02b57c2dc359"
    ],
    "text": "MSFT is the largest holding by weight in the latest book, and it is ranked 1st by weight in the latest issuer exposures."
   }
  ],
  "evidence": [
   "f_02b57c2dc359"
  ]
 }
}
```
→ accepted

## sub:risk → ledger · boundaries
（X02-weakest-fcf-margin-then-sell-it seq 114）
```json
{
 "of": "analyst_budget"
}
```
→ 1 boundary row stated

## sub:risk → store · report
（X01-largest-weight-then-its-cash seq 10）
```json
{
 "status": "returned",
 "task_id": "tsk_e02eb613af86",
 "protocol": "evidence-v2",
 "report_id": "rep_278e621becb5",
 "stop_reason": "submitted"
}
```
→ 10 evidence rows; 1 checked notes; submitted

## sub:risk → tools · book_read
（X01-largest-weight-then-its-cash seq 6）
```json
{
 "why": "Read issuer weights in the latest run to identify the largest holding by weight.",
 "book": "run_e2945c5ebd5a",
 "table": "issuer_exposures",
 "column": "weight"
}
```
→ r_3438bd9adaa3 book_read(book="run_e2945c5ebd5a", table="issuer_exposures", column="weight") → 10 rows

## sub:risk → tools · calc
（X02-weakest-fcf-margin-then-sell-it seq 108）
```json
{
 "n": 1,
 "op": "rank",
 "why": "Need to determine which of AAPL, MSFT, and NVDA has the smallest weight, which is the basis for the position to remove entirely.",
 "inputs": [
  "f_0df5bd94814a",
  "f_29304cec3b5b",
  "f_e2e7c9ea31ab"
 ],
 "direction": "lowest"
}
```
→ r_577fdd0f829e calc(op="rank", inputs=["f_0df5bd94814a", "f_29304cec3b5b", "f_e2e7c9ea31ab"], direction="lowest", n=1) → 1 row | refused: unknown_operand

## sub:risk → tools · list
（X01-largest-weight-then-its-cash seq 4）
```json
{
 "why": "Identify the latest book holdings and the issuer-weight rows needed to find the top-weight holding.",
 "what": "book",
 "subject": "port_001"
}
```
→ r_d94344919f9f list(what="book", subject="port_001") → 22 names

## sub:risk → tools · metric
（X02-weakest-fcf-margin-then-sell-it seq 91）
```json
{
 "why": "Need available issuer beta rows to locate issuer records and confirm the desk can read issuer-level data for the holdings mentioned.",
 "name": "price.beta",
 "params": {
  "window": "1y",
  "benchmark": "SPY"
 },
 "subject": [
  "AAPL",
  "MSFT",
  "NVDA"
 ]
}
```
→ r_eadf11f65589 metric(name="price.beta", subject=["AAPL", "MSFT", "NVDA"], params={"window": "1y", "benchmark": "SPY"}) → 15 rows

## sub:risk → tools · scenario
（X02-weakest-fcf-margin-then-sell-it seq 111）
```json
{
 "why": "Need the post-trade book after removing the smallest technology holding entirely, to assess the resulting Technology sector weight and the concentration checks.",
 "book": "run_e2945c5ebd5a",
 "trades": [
  {
   "sell": "NVDA"
  }
 ]
}
```
→ r_d4bc7e9743e0 scenario(book="run_e2945c5ebd5a", trades=[{"sell": "NVDA"}]) → 7 rows; made calc_19b1b082d58f | refused: not_run
