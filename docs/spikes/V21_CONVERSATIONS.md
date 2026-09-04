# The conversation battery — 13 conversations, 31 turns, and what they say about the analysis

2026-09-04. The first battery on this desk made of CONVERSATIONS rather than
questions: natural language, and every second and third turn depends on the one
before it ("and the other two?", "is that a one-off or has it been building?",
"say I sell the one you landed on"). Thirteen angles none of the earlier
batteries covered — a name to cut, a bear case from primary text, an open-ended
diligence sweep, a rates scenario with the stress tool withheld, capital
allocation, a name outside the book, a wrong premise asserted by the user,
revenue concentration from filing prose, news to position, pure ellipsis,
trigger levels, and whether a thesis still holds.

Run against the deployed stack (`scripts/conversation_battery.py`, one session
per conversation, a turn claimed and released around each message, three
conversations concurrent). Questions in `tests/battery/conversations_v21.json`,
criteria in `tests/battery/criteria_conversations_v21.json`, scores in
`docs/spikes/V21_CONVERSATION_RUBRIC.json`.

## §1 The scores

Every turn answered — 31 of 31 reached the gate — except two that exhausted it
(C01#t3, C02#t2) and published the standard "I could not produce an answer I
can stand behind".

| criterion | met | what the misses look like |
|---|---|---|
| `no_linear_locating` | 4/4 | locating never scaled with the book |
| `precision` | 6/7 | figures at reader precision |
| `trigger` | 4/6 | levels quantified when asked for levels |
| `follows_on` (new) | 13/18 | the follow-ups that failed are the ones whose PREVIOUS turn failed |
| `grounded_claims` | 16/22 | |
| `netting` | 1/2 | |
| **`ranking`** | **3/10** | "It names a smallest holding, not the largest driver, and gives no ordered ranking by magnitude" |
| **`so_what`** | **3/15** | "It ends by restating the data"; "It offers to do more work" |

`follows_on` is new to `scripts/rubric_battery.py` this batch, with its FALSE
condition stated where the other six are. The instrument now reads a
conversation file directly; a record may state its own question tag.

## §2 The finding that matters most: what is missing is not skills

The working hypothesis before the run was that the analysis is thin because the
desk has too few named methods. The battery says otherwise, and the number is
unambiguous:

    59 evaluate_formula calls, 19 distinct names asked for
    names the 32-entry registry does not hold: 4
      total_revenues, net_income, capex   — filed lines; get_flow holds them,
                                            and the refusal already says so (V19)
      return_on_capital                   — an alias for roic, which exists

**Zero genuinely missing formulas in 31 turns of real analysis.** Every named
measure the analysis reached for was already in the registry. Adding methods is
not the lever.

## §3 What actually costs the turns: the answer grammar, not the evidence

Refusals at the exit, all 31 turns:

| refusal | count | layer |
|---|---|---|
| `malformed_answer` | 32 | the block grammar |
| `invalid arguments` (shape) | 12 | the respond schema |
| `not_on_table` | 8 | evidence |
| `unknown_name` | 5 | evidence |
| `unsupported_assertion` | 1 | evidence |

Grammar outnumbers evidence three to one. Replaying the 32 malformed answers
through `validate_shape` decomposes them into **43 `digits_in_text`** and **13
`row_width_mismatch`**, and the digits split into three causes that the one
refusal cannot tell apart:

1. **an evidence id written into prose** (`run_3c94a47d6547`, `fact_…`) — the
   rule works, the model repeats it;
2. **a figure that IS on the table, written as text** — "16.0% of the book and
   $1,738,870 market value, versus a 15.0% limit" where every one of those four
   has a name. Recoverable, one wasted round trip each;
3. **a figure that exists only in filing PROSE** — "82% of total revenues",
   "Mounjaro revenue of $22,965 million". There is no slot for it, because it
   is not a quantity the desk computed (see §5).

**12 of 31 turns sent the identical failing `respond` at least twice.** Two
turns died that way. The clearest is C01#t3, which wrote a slot as a STRING —
`"{ref\": \"run_…\", \"name\": \"issuer_exposures.NVDA.weight\"}"` inside
`runs` — and re-sent it **eight times unchanged**, because the refusal it got
back (`digits_in_text`: "text carries no figures — put each one in a slot") is
the same sentence it would get for writing a percentage, and never says *this
run is a string; a slot is a JSON object*.

C04#t1 is the other shape: two blocks were malformed (one written as
`{"cites": …, "paragraph": "…"}` with no `type`, one as `{"metric_table,":
"placeholder"}`), the schema answered "is not valid under any of the given
schemas" — `arg_validation._unpack` can only name a branch when the instance
carries `type`, and this one did not — and after five attempts the model
deleted the substantive blocks and published the one that validated:

> "The latest completed run is the one returned in the snapshot, as of
> 2026-09-02. It holds 10 positions, 7 factor exposures, 2 alerts, and 20 limit
> checks."

That was the answer to *"rates back up 100bp — walk me through what that does
to this book, name by name"*. **Gate pressure degrades content**: refused often
enough, the model ships whatever passes.

## §4 Three holes found in the gate and its labels

**(a) `derive_table` mislabels a heterogeneous table — the V19 error class,
reintroduced by the machinery built to prevent it.** C10#t1 showed the reader:

    issuer exposures MSFT weight | 16.0% | 4.13% | 12.4% | 14.8%

The four cells are MSFT, NVDA, GOOGL and JPM weights. Reproduced directly:
when rows do not share a name family, `derive_table` returns an empty header,
takes the row label from cell 0, and leaves `explicit` False — so no cell shows
its own caption and three issuers' figures sit under a fourth issuer's name.
Nothing catches it: the labels are derived, so the gate does not judge them,
and `prose_critic` reads only paragraphs — precisely because tables were
supposed to be safe after V19.

**(b) A literal `{ref}` in prose passes the gate.** C06#t1 was published to the
user as "It is marked {ref}investigable{ref} in the issuer registry".
`validate_shape` returns zero problems for it.

**(c) A slot written as a string passes the gate** unless it happens to contain
digits. C01#t3 was caught only because a run id looks like a figure; the same
mistake with `{ref": "calc_x", "name": "gross_margin"}` would have been shown
to the user as raw JSON.

All three are closed lexical checks — the kind the gate already is — not
judgements.

## §5 What the desk genuinely cannot do

**Segment, product and geography figures do not exist.** The fact store holds
**0 dimensional facts out of 73,861**: `financial_facts.dimensions` is `{}` on
every row. The cause is upstream and structural — the provider reads SEC
*companyfacts*, which serves only undimensioned values; dimensional facts live
in each filing's own XBRL instance. So "how much of Lilly's revenue is
Mounjaro", "how is Azure growing", "where does Exxon earn it" are answerable
only from filing prose, whose figures cannot be slotted (§3 cause 3), which is
why C09 had to drop every number it had read.

**`rank` cannot order anything about the book.** `typed_calculator._resolve`
accepts `fact_` and `calc_` refs only; a run's own quantities
(`issuer_exposures.MSFT.weight`, `limit_checks.*.current_value`) are neither.
Meanwhile the system prompt says a highest/lowest claim is "a rank call FIRST".
So every natural portfolio ordering — biggest position, closest to breaching,
who hurt most — has no primitive, and the model either avoids ordering
(`ranking` 3/10) or asserts one it is not allowed to make.
`get_portfolio_analysis` precomputes two orderings server-side (`stress_ranked`,
`headroom`); there is no general one.

**`unknown_formula` does not suggest a near name.** It returns all 32 known
names, and for a filed metric it points at `get_flow` (V19). `return_on_capital`
is neither, so it got the flat list, four times, while `roic` sat in it.

## §6 The prompt forbids the sentence the rubric asks for

`so_what` is 3/15. The system prompt says:

> "Do not give a verdict. Whether leverage is high, whether to lend or invest —
> lay out the evidence that bears on it; the judgement is the reader's."

The desk is behaving as instructed. Whether an *implication for this book* is a
verdict or the point of the analysis is a product decision, not a defect, and
it is the cheapest lever available on analytical quality: one clause in
`_SYSTEM`. The no-verdict ban is long-standing (AS_BUILT §11,
IMPLEMENTATION_PLAN_V12/V13), so this is a decision to revisit, not a bug to
fix.

## §7 The V21 batch hold, measured in the wild

C13#t2 sent nine `evaluate_formula` calls in one message led by
`net_income` — not a formula. The hold saved eight round trips, then the model
re-sent the same batch and the hold saved eight more. But the eight it held
were `free_cash_flow`, `debt_to_ebitda`, `capex_intensity`, `fcf_margin`,
`ebit_interest_coverage`, `asset_turnover`, `net_debt_to_ebitda` — **all real
registry entries**. `unknown_formula` is an ARGUMENT-level refusal: it says
that *name* is wrong, not that the tool is. Holding by tool alone punished
seven valid calls, twice.

Refinement, not a retraction: when a refusal names the offending argument
(`formula`, `metric`, `name`), hold only later calls in the batch that repeat
that argument's VALUE; hold by tool only when the refusal is about the call
itself. `agents/batch.py`, one predicate.

## §8 The critic on this batch

`prose_critic` over the 31 answers: 90 slots in prose, **82 agrees, 2
disagrees, 6 unclear** — and both disagreements are false positives
(`risk_alerts.issuer_concentration:MSFT.current_value` *is* the current weight;
`.limit_value` *is* the limit). The grammar in `_NAME_GRAMMAR` does not
describe the alert columns. Zero true mislabels in prose this batch — while
§4(a) shows the mislabels moved into the tables, where the critic does not look.

## §9 What to do, in the order the evidence supports

1. **Teach the refusals** (`answer_blocks`, `arg_validation`): name the block
   type a malformed block was trying to be; separate "you wrote a number" from
   "your slot is a string"; refuse `{ref` in text; say when an identical answer
   was already refused. This is where the turns are going — 44 refusals across
   31 turns, two turns lost, one answer degraded to nothing.
2. **Fix `derive_table`** for heterogeneous rows: fall back to per-cell captions
   (`explicit` True) whenever the rows do not share a name family, and pin it.
   A wrong label reached a user in this batch.
3. **Let `rank` take run quantities** — or precompute the orderings a book
   question asks for. `ranking` 3/10 is downstream of this.
4. **Decide the `so_what` question** (§6). One clause, and the largest single
   move in measured analytical quality.
5. **Refine the batch hold** to argument scope (§7).
6. **Dimensional facts** (§5) — the biggest capability gap, and the most
   expensive: it means reading each filing's XBRL instance rather than
   companyfacts. Nothing else on this list unlocks segment analysis.
7. **A near-name suggestion in `unknown_formula`** — `difflib` over the 32
   known names, a closed lookup.

Adding formulas is not on this list, and §2 is why.
