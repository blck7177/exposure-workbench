# V19 coverage — labels the model cannot write, a web the chat can reach, a chain that reaches the filing

Date: 2026-09-02. Plan: `docs/IMPLEMENTATION_PLAN_V19.md`. Module note: MODULE_NOTES §M21.
Wording awaiting review: `docs/spikes/V19_WORDING_REVIEW.md`.

## §1 What was measured before

From the stored answers of 2026-09-02 (R20 battery, twenty questions) and the
`agent_steps` table:

- 3 of 20 answers carried a **wrong-name slot** — a correct figure under a
  label the model wrote: `Peak-to-trough decline | $205.10` (the slot was the
  trough), "market cap at $919.77" (`LLY.close`), "trade back up to … $82.52"
  (the last close). The gate had verified every one of them.
- `search_external_research` had been called **5 times in the life of the
  desk**, last on 2026-08-22, all from research runs: the meta face did not
  carry it, and the capability statement saying so rode only on `describe_run`.
- A fact card ended at an accession number; a run card had `upstream: []`.

## §2 What was built, and what the live turns corrected

Four live rounds of the same four questions (web news, drawdown table, LLY FCF
trend, rank by net income) plus one three-issuer table, on the deployed stack,
each round after a rebuild. What each round changed:

| round | finding | change |
|---|---|---|
| 1 | the web search went to the engine as "latest news from the past week" — no issuer — and returned five front pages (NPR, BBC, CBS…) | `compose_query` binds the issuer into the query in the tool; `days` became a request parameter (Tavily `topic=news`) |
| 1 | rank: 10 of 15 calls spent on `evaluate_formula("net_income")` → `unknown_formula` ten times | the refusal names the tool that holds a filed metric (`get_flow` / `get_balance_sheet`) |
| 1 | single-row table transcript read `$235.47 \| $164.98 \| $235.47` with no names | explicit cells say their name in the transcript |
| 3 | per-issuer rows all named `net_income@…` derived to empty labels; the model then tried `MSFT.net_income` (unknown_name) because `TABLE_RULE` told it to "write the entity in the name" | the ledger row's `company_id` (a ticker) rides to the table as the ref's **subject** and prefixes the derivation; `TABLE_RULE` reworded: labels are not written by the model |
| 5 | three issuers as three columns: AAPL's cell captioned `net income` | every table cell carries a `caption` = subject + name |

Round 4 (after the subject fix), verbatim shapes:

- **web**: `search_external_research` → `respond`, 0 refusals, 2 `src_` cited,
  the answer about Jensen Huang's data-centre remarks and a director sale.
- **drawdown table**: one row, three explicit cells —
  `NVDA adj close 2026-05-14 | $235.47 | NVDA adj close 2026-07-29: $190.01 | NVDA adj close 2026-05-14: $235.47`.
  The third cell is still the peak slotted for "decline"; it now *reads* as the
  peak. The mislabel is gone; the missing subtraction is the model's initiative
  (see §3).
- **LLY trend**: a `trend` block whose series line is
  `operating cash flow.pct: 186.3% (2025-09-30) → 65.4% (2026-03-31), down`,
  computed, above the model's sentence.
- **rank**: `get_fundamental_panel` ×10 → `rank` → an honest refusal (two ETFs
  and a bank); no table. Round 2 of the same question produced the derived
  header `net income` with period rows; the per-issuer labelled table is pinned
  by tests and by the three-issuer turn (`MSFT net income | $125B | AAPL net
  income: $123B | GOOGL net income: $244B` after the caption fix).

Evidence chain, through the public API: `fact_8adc3c937f26` → `10-Q · filed
2026-04-29` → `https://www.sec.gov/Archives/edgar/data/789019/…/msft-20260331.htm`;
`fact_9a62c12e1625` (no filing row) → the derived EDGAR index for its
accession, kind `edgar_index`, HTTP 200; `run_690a3a2db838` → 10 holdings,
each resolving to a position card.

## §3 Residuals (registered, not patched)

- **Paragraph prose is unjudged**, by the 9/1 contract. "market cap at $919.77"
  is still writable in a paragraph; the critic outside the gate is the next
  batch.
- **Composition initiative**: the drawdown "decline" is one `calculate` away
  and the model slots the peak instead; the label now says so, nothing makes it
  subtract.
- **The 15-call turn budget vs. ten holdings**: a batch of ten wrong calls
  cannot be corrected by a refusal the model reads only afterwards. Round 4
  spent 10 on `get_fundamental_panel` and got to `rank`; round 1 spent 10 on
  `evaluate_formula` and did not.
- **Facts whose filing was never ingested** are 12,239 of 13,343 at mapping v4;
  their pointer is the EDGAR index of the accession, not the document, and the
  card says which.
- **Web search is issuer-scoped**: an ETF's news is refused
  (`not_investigable`), because `research_sources.company_id` is the row's
  shape.
- The text rule's frozen classifier refused "Jetson Orin Nano 2" and "second
  quarter fiscal 2027" three times in one turn (round 3). Known cost of the
  frozen nine; not touched.

## §4 Suite

- Offline: 1948 → **1973** (`tests/test_v19_labels.py`, 25 cases; three
  fixtures in `test_output_grammar` moved to the new grammar).
- Live: see the bottom line below.
- Deployed: four images rebuilt (final build after the caption change), code
  grepped in `exposure-api` / `exposure-mcp` / worker / web.

Live suite: **262 passed** (1:53) against the final stack; offline **1973 passed**. Three-issuer table on the final stack: `MSFT net income | $125B | AAPL net income: $123B | GOOGL net income: $244B`, captions carrying each subject.
