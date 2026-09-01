# V15 — the table, measured

> 2026-09-01. Instrument: `scripts/agent_battery.py` over `tests/battery/questions_v14.json`
> (8 questions, n=1 each), scored by `scripts/rubric_battery.py --semantic`, and the exit
> measured by `scripts/exit_metrics.py` — the same computation the S0 baseline was done by hand.
> Traces: `docs/spikes/V15_TRACES.json` (official, after the second image build),
> `V15_TRACES_pass1.json` (the first pass, before the confidence-level and window-label
> classes landed). Scores: `V15_RUBRIC.json`; exit: `V15_EXIT.json`, `V15_EXIT_pass1.json`.
> Baseline: `V15_BASELINE.json` / `V15_BASELINE_EXIT.json` / `V15_BASELINE_TRACES.json` (S0, 9/1 morning).

## 1. The switch criteria (plan §4 S7)

| criterion | S0 baseline | V15 pass 1 | **V15 official** | met |
|---|---|---|---|---|
| ① figures with no basis | 276 in the 8/27–8/31 corpus | 0 by construction | **0** — `slot.value` does not exist; every slot resolved to a named row | ✅ |
| ② `read_required_inputs` ≥ S0; linear locating gone | 2/4; 0/1 | — | **2/4; 0/1** (V2 still locates ten issuers one call each) | ❌ see §4 |
| ③ refusal rate ≤10%, attempts median 1, no answer 0 | 79%, 5, 0/8 | 70%, 3, 0/8 | **50%, 2, 0/8** | ❌ (no-answer met) |
| ④ rubric ≥ 15/33 | 15/33 | — | **21/33** | ✅ |
| ⑤ peak prompt −30% | avg 22.4k / max 35.5k | 15.4k / 20.9k | **16.8k / 35.9k** (−25% avg) | ❌ (close) |

Abort criterion (attempts median >2 or no answer >0 over two rounds, not converging): **not
triggered** — median 3 → 2, no answer 0 → 0, and the refusal classes shrank (§3).

## 2. What moved in the rubric

| criterion | S0 | V15 | note |
|---|---|---|---|
| ranking | 2/6 | **4/6** | the table gives the model the ordered names; V14's finding ("ordering the data is necessary and not sufficient") holds — two still flat |
| precision | 1/8 | **5/8** | figures render at reader precision (`display_conventions`) in the stored prose; the three misses are `$10.87M` written where a date belonged and repeated slots |
| so_what | 3/6 | 4/6 | |
| netting | 3/3 | 2/3 | n=1 noise band (V14 measured 66% at n=3) |
| grounded_claims | 3/3 | 2/3 | V8 refused twice then answered thinly |
| read_required_inputs | 2/4 | 2/4 | `get_risk_state` still uncalled on V1/V3; `describe_run` was read on V1 |
| no_linear_locating | 0/1 | 0/1 | §4 |
| trigger | 1/2 | 2/2 | |

## 3. The exit, refusal by refusal

S0 (8 turns): 38 attempts, 30 refused — `unresolved_slots` 17, `malformed_answer` 10,
`invalid_citations` 2, `invalid_arguments` 1. Median 5 attempts a turn.

V15 official (8 turns): 16 attempts, 8 refused, median 2:

| refusal | n | what it was |
|---|---|---|
| `digits_in_text` (id written into prose) | 3 turns | V2 put `run_…` in table cells; V7 wrote `calc_…` after each figure — twice. The refusal now says where an id belongs (`cites` / a slot); the prompt says it too. The model's habit from four batches of "cite after the claim" is the residue |
| `digits_in_text` ("95%") | 1 | "VaR (" + slot + ") at 95%" — the confidence class was there but the rule read each run alone; it now reads the paragraph whole (landed after the run) |
| `unknown_name` | 2 | V7 wrote `net_margin` for a row the table called `calc.scalar.divide` — the formula's name was never on its row. Fixed after the run: a formula names its final step (`as_quantity`), and a row's name is what it says it is a quantity of. V8 wrote run names under a calc ref — a genuine miss |
| `row_width_mismatch` | 1 | a table row shorter than its columns |
| `not_on_table` | 1 | `src_?` — a placeholder id |

Pass 1 (before the confidence-level and window-label classes): 27 attempts, 19 refused, of
which **8 were one turn negotiating "VaR (95%)"** — the class the V3 gate had and V15's
first cut dropped. Three classes were added back after measurement (window labels, sessions,
confidence levels); the text rule is now seven closed classes, not one. The plan said "date
only"; the corpus said otherwise, and the corpus is the authority (V8 rule).

The refusal classes the plan set out to delete are gone: no `unresolved_slots` (there is no
value to resolve), no `invalid_citations` against ids the session really held (every declared
id is on the table), no `figure_not_held_by_this_ref`, no `held_instead_by`.

## 4. What the table did not fix, and why

- **Linear locating (V2)**: eleven calls for ten holdings. `describe_run` is the book's
  manifest for the *run*; the per-issuer questions still pay `describe_issuer` per issuer.
  A book-scoped issuer manifest is the next asymmetry to close, and it is a different tool
  from this batch's.
- **`get_risk_state` uncalled**: the tail measures are on the table via `describe_run`
  (group `risk`), so the criterion as written — "the tool was called" — no longer measures
  what it meant. It should be re-stated as "the quantity was on the table and slotted".
- **Ids in prose**: three turns. Structural options (accept an id token in text as an
  implicit cite; strip it) are fallbacks and were not taken. The measured line is the
  prompt sentence plus the sharper refusal; it will be re-measured on the next battery.
- **Peak prompt**: −25% on average, but one turn (V4) hit 35.9k — `describe_run` plus its
  table plus `get_portfolio_analysis` in one turn is ~23k of payload. The manifest is read
  once and the rest by name, which the prompt now says; the ceiling is 28k a result.

## 5. Structure, verified

- offline **1562** (S0: 1484), live **246** (S0: 238), vitest **32** (S0: 19), smoke_ui 7/7.
- 235/235 quantity names unique on `run_1d6e9e05bee6` (alerts qualified by `entity_id`).
- The absence path end to end: `get_flow` refuses → the row is on the table → an `absence`
  block passes (`test_v15_table_live`). Before V15 the id never reached the trail.
- One resolver for both exits (`test_one_resolver`); `not_alone` decided in `table.py` only.
- Deleted: `extract_evidence_refs`, `_harvestable`, `collect_trail`, `trajectory_gate`,
  `_COMPATIBLE`-based slot matching, `_DERIVATIONS`, `held_instead_by`, 26 runtime shape
  codes, the prose `_respond`. `numeric_verification.py` 1041 → 534 lines (v1 report path only).
- Live defects found by the new guards during the batch: `_summarize` deleted with the
  walker (every trace write failed, silently); `search_external_research` registered without
  a declaration; `flow.series` points named `@None` (three producers, three period keys);
  `portfolio.window_return` typed MONEY for 43 rows (now RATIO at the writer, backfilled).

## 6. What to decide next

1. Re-state `read_required_inputs` in terms of the table (quantity slotted), not the tool.
2. A book-scoped issuer manifest (the V2 shape) — the remaining asymmetry.
3. Whether the id-in-prose habit warrants a structural answer after one more battery.
4. The daily report stays on the v1 prose gate (plan §7-⑥); block it or leave it.

## 7. Pass 3 — after the post-run fixes, measured, nothing changed

> 2026-09-01 evening, same instrument, same 8 questions, n=1. Traces `V15_TRACES_pass3.json`,
> exit `V15_EXIT_pass3.json`, scores `V15_RUBRIC_pass3.json`. Recorded as measured; no code was
> touched after this run.

| | S0 | official | **pass 3** |
|---|---|---|---|
| respond attempts (total / refused) | 38 / 30 (79%) | 16 / 8 (50%) | **10 / 2 (20%)** |
| attempts per turn, median | 5 | 2 | **1** (6 turns at 1, 2 at 2) |
| no answer | 0/8 | 0/8 | **0/8** |
| peak prompt tokens avg / max | 22.4k / 35.5k | 16.8k / 35.9k | **11.0k / 15.3k** (−51% / −57%) |
| tool calls per turn | 5.9 | 4.0 | **2.6** |
| rubric | 15/33 | 21/33 | **19/33** |
| no_linear_locating | 0/1 | 0/1 | **1/1** (V2 answered from the snapshot's table, one call) |
| read_required_inputs | 2/4 | 2/4 | 1/4 |
| precision | 1/8 | 5/8 | 3/8 |

Switch criteria now: ① ✅, ③ ✅ except the refusal rate (20% against ≤10%), ④ ✅, ⑤ ✅;
② half — linear locating gone, `read_required_inputs` 1/4 (the criterion still counts tool
names; the quantities it wants were on the table from `describe_run` in V1 and V4).

The two refusals: one `invalid_arguments` (a slot written with `value`, refused by the
schema before the gate), one `digits_in_text`. No id written into prose this round.

What the rubric drop is: `precision` 5/8 → 3/8 and `read_required_inputs` 2 → 1 are the
model slotting the WRONG name — V3 "net exposure to rates is 100.0% of portfolio value"
(slotted `net_exposure_pct` for a rates figure), V7 "latest filed balance-sheet date is
$43.37B" (a money quantity where a date belonged). These pass the gate by construction —
the figure is a real row's value under its real name — and are the residue V14-B predicted:
a mechanical property is enforced, a prose property (the right name for the sentence) is
not. Three rounds: attempts 3 → 2 → 1, refusals 70% → 50% → 20%, no answer 0 throughout;
the abort criterion is not in reach, and the next defect is named — wrong-name slots.
