# V24 coverage — the fact carries its identity, measured

Companion to docs/IMPLEMENTATION_PLAN_V24.md (§8 F). Everything here was run
on 2026-09-05 against the deployed V24 face after live rounds 1–3.

## §1 The conversation battery: V24 beside V23-R

Same 13 conversations, 31 turns (tests/battery/conversations_v21.json); the
V21 and V23-R columns are V23_COVERAGE §5's. One judge pass each; the new
`honest_absence` criterion (3 turns) is scored for V24 only and shown apart
so the totals compare like with like.

| criterion | V21 | V23-R | **V24** | | deterministic | V21 | V23-R | **V24** |
|---|---|---|---|---|---|---|---|---|
| so_what | 3/15 | 10/15 | **10/15** | | turns answered | 29/31 | 29/31 | **31/31** |
| ranking | 3/10 | 4/10 | **5/10** | | turns lost to the gate | 2 | 2 | **0** |
| trigger | 4/6 | 3/6 | **4/6** | | tool calls | 228 | 237 | **188** |
| grounded_claims | 16/22 | 13/22 | **19/22** | | gate refusals | 15 | 14 | 27 |
| precision | 6/7 | 5/7 | **5/7** | | · pointer written as text | 9 | 1 | 13 |
| follows_on | 13/18 | 12/18 | **16/18** | | · not_on_ledger (was not_on_table) | — | — | 6 |
| netting | 1/2 | 0/2 | 0/2 | | · unsourced_figure (new) | — | — | 3 |
| no_linear_locating | 4/4 | 4/4 | **4/4** | | · unverified_quote | — | — | 3 |
| **total (84)** | 50/84 | 51/84 | **63/84** | | · not_standalone | — | — | 2 |
| honest_absence (new, 3) | — | — | 1/3 | | calls held behind a refusal | 22 | 1 | 12 |
| | | | | | facts pointed at inline / prose links | — | — | 185 / 35 |
| | | | | | verified figures (see note) | 228 | 325 | 191 |

**Note on "verified figures".** V21–V23 counted slots: every `{ref, name}` in
an accepted answer, duplicates included. V24 counts the DISTINCT facts an
accepted answer rests on (pointers and resolved prose links, scalars and
series), once each. The two are not the same unit; 191 distinct facts
against 325 slots is not a fall. `citations` (763) is every fact an answer
named, cites included, and is likewise a different unit from V23-R's 119
evidence ids.

**What moved.** No turn was lost to the gate (V23-R lost two; C03#t3 to a
run id recalled from the transcript, C09#t1 to a figure inside a verified
quotation — both now resolve: a Fact is pointed at by id and a passage's
figure links to the passage). `grounded_claims` 13 → 19 and `follows_on`
12 → 16 with `so_what` held at 10: the answers rest on more of what was
read, and the second turns pick up the first's subject. Tool calls 237 →
188: a `facts` block is read once; there is no `read_quantities` to pull
names one at a time.

**What did not move.** `netting` 0/2 (C04: the rates legs are still listed
side by side — the procedure names `book.analysis` for the netted leg and
the model did not take it); `ranking` 5/10; `honest_absence` 1/3 (§2).

**The refusal mix.** 27 refusals over 31 turns, none fatal. Thirteen are
`pointer_written_as_text` — `{fact:f_…}` inside a string — the V23-R
slot-as-string shape reborn under the new grammar; refused once, fixed on
the retry every time. This is the one class the gate still meets often; it
is a closed shape, and whether to keep refusing it or to parse it (a
well-formed pointer in the wrong place) is decision §4.1. Six are
`not_on_ledger`; three `unsourced_figure` (the model's own arithmetic, each
fixed by a compute call on the retry); three `unverified_quote` (scare
quotes around a paraphrase); two `not_standalone` (a collinear leg pointed
at alone — the row's reason reached the model and it pointed at the sum).

## §2 honest_absence, first reading

| turn | met | what happened |
|---|---|---|
| C04#t2 (TLT vs equity duration) | — | judge: "gives a split and says 'I cannot quantify the split', but does not plainly say the desk lacks a held figure or offer the nearest held substitute" |
| C09#t2 (put a number on Lilly's concentration) | — | judge: "gives figures but does not plainly answer the asked split or say it is unavailable; paraphrases concentration" |
| C13#t2 (see it in the numbers) | ✓ | said which figures the desk holds and which it does not |

Both misses are the same shape: the model hedges instead of pointing at the
absence fact and naming the nearest held figure. The absence facts exist
(`not_held` segment figures; no per-name duration on the desk) and the
system prompt says to point at them; the procedure text for these two
angles does not yet say "point at the absence and name the nearest held
figure" in those words. A registry edit, not a gate one.

## §2a Two things the model reached for that the grammar does not have

- **A point of a series.** C02#t2 twice pointed at ids that were never shown
  for "inventory rose from X to Y" — the series is ONE fact and its points are
  not addressable. A pointer `{fact: id, at: period}` (G2: the fact is a
  series and the period is one of its points; rendered as that point's value
  with its date) would give the model what it wanted without minting a fact
  per point. Decision §4.4.
- **A figure inside a passage.** C09#t1 three times pointed at an invented id
  for "56 percent of total revenues", a number stated in a passage it had
  read. The grammar's answer is to write it in prose with the passage in
  `cites` (G3 links it to the passage) — the refusal's sentence should say
  so. Decision §4.5 (wording).

## §3 The three live rounds before the battery

IMPLEMENTATION_PLAN_V24 §8 F.1 carries the table: round 1 taught the gate
(cites take any fact; the serialised pointer named once; the user's own
number rests on the question) and the adapter (refusal schemas pass through)
and `compute` (a Fact id is an operand); round 2 taught the skill registry
(`trim_to_tier`), the adapter (a single-issuer op result is that issuer's)
and `start`'s description; round 3 taught `read_book` (nearest names) and
the scenario service (a scenario builds on a scenario row).

## §4 The grammar, measured and changed (2026-09-05)

§1 left three questions. Rather than decide them by argument, every respond
the desk had stored (94: the battery, the three live rounds, the reruns) was
replayed with its own ledger and its own question, under the grammar as it
stood and under a candidate.

**What the replay said.** 28 of 48 refusals were one shape, the pointer
object serialised into one of the strings of the `runs` array. Under a prose
grammar 22 of them became clean acceptances, and the decoration left in the
reader's text vanished entirely once the one closed wrapper shape was
stripped. It also **refused half of what had been proposed**: folding `cites`
into the sentence turned two accepted answers into refusals, because a fact a
paragraph RESTS ON is not a fact it STATES, and a figure that may not stand
alone may still be cited. So `cites` stayed a field.

**What was built.** `paragraph {text, cites}`; the fact's id written where the
figure goes; `f_…@period` for one point of a series (the model had invented
ids for points five times because they had no address); the old decoration
normalised to the pointer it carries rather than refused. The rendered OUTPUT
is unchanged — runs of strings, `{fact: …}`, `{link: …}` — so the page and
every stored answer read as before, and the frontend did not change.

**Three defects the replay found, two of them already shipping.**

| defect | how it showed | closed by |
|---|---|---|
| the number token swallowed the comma ending a clause | "in 2024, revenue rose" offered the gate `2024,`, which no lookup resolves; **four of the seven `unsourced_figure` refusals in the whole corpus were this** | the digit run must end in a digit |
| a value exactly on the rounding boundary missed by one float ulp | 0.1625 written as 16.3% did not match | half a unit of the last digit, and a hair |
| a pointer glued to the word before it is invisible to the pointer walk | the id would reach the reader as literal prose — a silent failure | `pointer_not_separated`, refused by name |

**Verified over the same 94 responds:** accepted 44 → 69; no accepted
answer's text shows an id or decoration; every remaining refusal is the gate
working (a fabricated id, a scare quote, the model's own arithmetic).

**The live round after it.** The trim answered in four calls with no refusal.
The rates turn produced twenty verified figures and named the offset. The
model tabulated a series' eight instants as `@period` cells, which crashed
the renderer once and is now a table cell like any other. And the case that
had been unstateable since V21 — a figure that lives only in filing prose —
came out right:

> Lilly's filing says Mounjaro and Zepbound accounted for **56%** of total
> revenues in 2025. It also says the six products … collectively accounted
> for **82%** of total revenues in 2025

Both figures are written in the sentence and linked to the passage the block
cites. Nothing was estimated and nothing was pointed at that was not shown.

## §5 Left for the boss

1. **A passage pointer standing where a figure belongs.** The same Lilly
   question, asked one turn earlier, produced "total revenue of
   [10-K Item 8]" seven times: the model points at the passage instead of
   writing the figure the passage states. The gate accepts it (a passage
   inline is legal and renders as a mark) and the reader gets a mark where a
   number should be. The turn that got it right did the designed thing —
   figure in the prose, passage in `cites`. Refusing an inline passage would
   force that, in one line of G2, at the cost of the footnote-in-a-sentence
   form. **This is a contract change, not a defect fix, so it waits.**
2. **The table block is still unused** in ordinary turns.
3. **Wording** — docs/spikes/V24_WORDING_REVIEW.md, updated for the prose
   grammar.
4. **`honest_absence`** was 1/3 on its first reading; the absence facts it
   needed did not exist then and do now, and the one turn re-run since
   passed. It should be re-measured on the next full battery.
