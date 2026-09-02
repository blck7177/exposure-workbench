# V19 — labels the model cannot write, a web the chat can reach, a chain that reaches the filing

Status: **as built** (2026-09-02; coverage in `docs/spikes/V19_COVERAGE.md`). Five
things the plan did not have were added by the live rounds: the search query
carries the issuer and a `days` window; `evaluate_formula` on a filed metric
names `get_flow`; a ledger row's issuer (`calc_ledger.company_id`) rides to the
table as the ref's *subject* and prefixes the label derivation; every table cell
carries a `caption`; `TABLE_RULE` no longer tells the model to write anything. Ordered by the boss after the 9/2 functional
review; the three items are structural, and the paragraph critic that the review
also named is *not* in this batch (it is an LLM outside the gate and gets its own
plan once these land).

## Why

Three findings from reading the 9/2 battery (R20) and the stored answers:

1. **Wrong-name slots in tables.** `Peak-to-trough decline | $205.10` — the slot
   was `NVDA.adj_close@2026-06-05`, the trough, and the *row label* was the model's
   own text. The gate proves the figure has a source; it cannot see that the label
   beside it lies. Three of twenty answers carried this shape (drawdown table, LLY
   "market cap" = `LLY.close`, TLT "trades back up to" = the last close).
2. **The chat has no web.** `search_external_research` is on the research face
   only; the meta-agent's capability statement says "cannot search the web from
   this face" — and that statement rides only on `describe_run`, so an issuer
   question never reads it. Asked for the web, the model reads filings.
3. **Two dead ends in the evidence chain.** A fact card stops at an accession
   number (the `filings` row has the SEC URL; the resolver does not carry it), and
   a run card has `upstream: []` — a weight or a day P&L cannot be followed to the
   holdings it was computed over.

## S1 — table and trend labels are derived from the name (answer_blocks, meta_tools, web)

- `metric_table` grammar: `rows` are rows of **slots only**; `columns` is gone. A
  string cell is refused by the schema (before the gate) and by `validate_shape`
  (for direct callers) as `cell_not_a_slot`, with the fix in the detail.
- `rendered()` derives, per table, a `header` (one string per column: the tokens
  every row of that column shares) and `labels` (one per row: the tokens that vary).
  When the names of a column do not align token-for-token, the column is
  `explicit` and each cell shows its own full name. A duplicate slot now shows as a
  duplicate row, not as a second measure.
- `trend` blocks get a `series` summary — the series' own name, its first and last
  dated point, and the direction *computed* from those two values — attached by
  the resolver from the table it already loaded. The model's sentence stays as
  commentary; the reader sees the series say what it did.
- Front end renders the derived header/labels and the series line; stored blocks
  from before V19 (`columns` + string cells) keep rendering as they were.

Not done here, by the 9/1 contract: no lexical rule judges the model's prose
against the computed direction. That is the critic's job, outside the gate.

## S2 — `search_external_research` on the meta face

- Registered once (`register_search_tool`) and called by both registry builders;
  `FACE_META_AGENT` names it. Budget unchanged: `external_search_budget` (5) per
  session, reserved in the wrapper by `budget_key`; `src_` ids go on the table
  through the existing `Evidence()` declaration and the existing `src_` resolver
  and card.
- Outside a research run `research_run_id` is NULL on the source row (the column
  was already nullable; `research_sources` carries no RLS).
- A ticker the desk has not admitted is admitted from the listed universe
  (`company_service.admit`, V17) so "news on X" works for any listed filer.
- `_FACE_CAPABILITIES` moves the web from `cannot` to `can`; `_SYSTEM` gains one
  sentence saying when the web is the instrument. Both are model-visible wording
  → `docs/spikes/V19_WORDING_REVIEW.md`.

## S3 — the chain reaches the filing and the holdings

- `_fact` carries `source_url`, `form_type`, `filing_date` from the filing row
  (by `filing_id`, else by accession). The fact card gets "Open at SEC".
- `_run` lists its holdings as `upstream` (`pos_` ids with a label), resolved the
  one way the workflow resolves them (`portfolio_service.positions_for_run`, moved
  out of the workflow so there is one definition). The run card lists them.

## Acceptance

- Offline: grammar refuses string cells and `columns`; `rendered` derives
  header/labels on the three real shapes (rank table, run-child table,
  mixed-shape table → explicit); trend summary direction on a real series; faces
  resolve with the search tool on both; capability statement says `can`.
- Live: one chat turn that asks for the web calls `search_external_research`
  on the meta face, cites a `src_` id, and the card opens; a fact card shows the
  SEC link; a run card lists holdings that resolve.
- Deploy: images rebuilt, code grepped in the containers, R20-18 rerun renders
  the drawdown table with derived labels.
