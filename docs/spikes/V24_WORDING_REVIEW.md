# V24 — model-facing wording for the boss's review (standing instruction)

Every sentence the model reads that changed in V24, for approval before the
next commit that carries it. Nothing here is a rule the code enforces; the
gate enforces by lookup. These are the contract stated in words.

## `_SYSTEM` (agents/meta_agent.py) — the changed paragraph

> The discipline: every figure you state is a FACT a tool returned — each tool
> result carries a `facts` block (one row per fact: id, kind, subject, measure,
> unit, value, as of, window, params) and a `note` in which each figure stands
> as its fact id. You never write a number: a figure, counts included, is a
> pointer {fact: id}, and the reader is shown the fact with what it is and as
> of when. A number you worked out yourself has no id — compute gives it one.
> A figure the desk does not hold is an absence fact: point at it and say why
> (not filed; not held as a figure; no method) — never a nearby figure wearing
> the asked-for name, never an estimate. Where the desk holds a figure that
> answers a different question, say which question it answers.
>
> Finish every turn by calling respond. If respond refuses, it names the block
> and the fix: point at a fact you were shown, compute the figure, cite the
> passage, or drop the sentence.

## `respond` description (tools/meta_tools.py)

> Reply to the user. An answer is a list of BLOCKS; a figure is a pointer
> {fact: id} at a fact a tool result showed (its `facts` block), and the reader
> is shown the fact's own value with what it is and as of when — you never
> write a number. Blocks: `paragraph` (runs: an ARRAY whose elements are
> strings and {fact: id} OBJECTS in reading order — a ref is never written
> inside a string; `cites`: the facts its prose rests on), `table` (rows of
> fact ids, one row per thing compared and one column per measure; header and
> row labels come from the facts), `chart` (kind + a series fact). A claim that
> something rose or fell points at the series; that something is not held, at
> the absence fact; work you started, at its task fact. A number written in
> prose must be one the ledger accounts for — a fact's value, its date, its
> window or parameter, or a figure a cited passage states — else the reply is
> refused: compute it, cite it, or drop it.

## `submit_brief` description (tools/research_tools.py) — the changed clause

> A figure is a pointer {fact: id} at a fact a tool result showed — the reader
> is shown the fact's own value; you never write a number. Blocks: `paragraph`
> (runs of strings and {fact: id}; `cites`: the passage facts its prose rests
> on), `table` (rows of fact ids only — header and row labels come from the
> facts), `chart` (kind + a series fact). A number written in prose must be
> one the ledger accounts for.

## `compute` description (tools/definitions.py) — the changed clause

> where an operand is a FACT id from a result's `facts` block (f_…), a
> fact_/calc_ id, or a figure by name on a run row (run_…:issuer_exposures.MSFT.weight)

## `start` description (tools/meta_tools.py) — the changed clause

> exposure_run (a portfolio run on the book AS IT IS, on the last completed
> session unless as_of_date — it does not apply a trade; a hypothetical sale or
> purchase is compute(method='book.sell' | 'book.buy', subject=run_…), which
> answers at once)

## The refusals the model reads (services/gate.py)

| reason | detail sentence |
|---|---|
| `not_on_ledger` | every id an answer points at is a fact a tool result showed this session (an f_… id from a `facts` block). These are not — use one you were shown, or read it |
| `kind_does_not_fit` | a table cell is a scalar fact; a series, a passage, an absence or a task goes in a paragraph / a chart draws a series fact |
| `not_standalone` | this figure is not determined on its own (the row says so); point at the figure that is |
| `unsourced_figure` | a figure in prose is either a fact on the ledger — point at it as {fact: id}, or it is linked for you when it equals one — a figure a cited passage states, or a result compute has not produced yet. Compute it, cite the passage that states it, or drop it |
| `pointer_written_as_text` | a fact ref is an OBJECT element of `runs` — ["text", {"fact": "f_…"}, "text"] — never a string containing one. Send it as an object; the reader is shown the fact's value where it sits |
| `id_in_prose` | an id is a pointer, not a word: a fact goes in {fact: id}, a passage in cites |
| `name_in_prose` | a measure's name is the name OF a figure, not a word: point at the fact {fact: id} and the reader is shown its value and what it is |
| `unverified_quote` | quotation marks say these words appear verbatim in a passage this block cites. Reproduce the source wording and cite the passage, or drop the marks |

## Registry entries (analytics/skill.py) — new or changed

- `trim_to_tier` procedure (new): "how much of one holding to sell to bring it back under a concentration tier" — gather the book value, the holding's weight and value, the tier level; compute tier dollars = book value × tier, sale = position value − that (or book.sell at a fraction); compare the sale against the position (larger than it, or negative, means the wrong tier or base); close with the dollars and the landing weight.
- `book.sell` / `book.buy` describes: "… The subject is a run (run_…) or another scenario's calc_ row, so trades chain."

## MCP `INSTRUCTIONS` (tools/mcp_server.py) — the changed paragraph

> Every tool result carries a `facts` block — one row per figure, with its id
> (f_…), what it is, whose, its unit, value, as-of and window — and a `note` in
> which each figure stands as its fact id. State no number you did not get as a
> fact; point at facts by id. The gate refuses an answer that points at what
> was never shown, or writes a number the facts cannot account for.
