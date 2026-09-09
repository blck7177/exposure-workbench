# V30 Phase 0 — the instrument (record, written as the runs complete)

## What was built

| piece | where | what it does |
|---|---|---|
| frozen fixture | `scripts/battery_fixture.sh` (snapshot / restore / serve / stop), `/home/ubuntu/backups/battery/battery-2026-09-09.sql.gz` (58 MB) | production dumped once; `exposure_battery` restored from it before every set; a local MCP face on :8105 serves the code under measurement over that database; `exposure_gold` is a second copy for gold derivations and Phase A/B/C smoke on :8106 |
| battery on the fixture | `scripts/conversation_battery.py --fixture --deny start` | the loop's own engine and its tool calls both go to the fixture; `start` is off the face (a turn cannot change the book it measures); BATTERY_DB / BATTERY_MCP_PORT choose the copy and the face |
| gold | `scripts/gold/{v21,v24}.py`, `scripts/gold_derive.py`, `tests/battery/gold_{v21,v24}.json`; `scripts/gold_from_programs.py` for V26 | the desk's own services compute each computable turn's figures; `must` marks what the question asks for |
| deterministic scoring | `scripts/rubric_battery.py --gold` (`figures_present`), `--replicates N` (judge spread), `--criteria`; `scripts/v30_figure_recall.py` (graded) | `figures_present`: every must figure appears among the rendered figures (1e-6) — all-or-nothing, and underpowered on V24/V21 (see §Results). The graded reader reports the share of must figures rendered at 0.005 relative tolerance and stores nothing. The judge is asked N times and the spread reported |
| counters | `scripts/battery_counters.py` | refusals split by whose work: spelling / gate / algebra / data / system; round trips, tokens, respond attempts, artifacts, superlatives without a rank |
| baseline runner | `scripts/v30_run_baseline.sh` from a worktree pinned at HEAD (`e6c290b`) | R2 and R3 on gpt-5.4-mini, then V21+V24 on gpt-5.5 (D4) |

## Replicate discipline, and what it cost to learn

- **R1** (`V26_R1`, `V21_R1`, `V24_R1`) ran on the fixture from a face started at 02:33 on the working tree — the pre-`952e046` tree (the peer session's max_vif commit landed after). Kept as a record; not one of the clean pair.
- The runner's first R2 restarted the face from the working tree after V30 Phase B had been wired into it: it measured half-built V30, not the baseline. Stopped after 30 turns and discarded (`DISCARDED_*`). **A fixture face serves whatever tree it starts from; the baseline must be served from a checkout pinned at the commit under measurement** — hence the worktree.
- Clean pair: R2 and R3 from the worktree at `e6c290b`, ten old tools on the face, verified in the face log at each restart.

## Service defects the gold derivations surfaced (not fixed in V30; recorded for the owner)

1. `evaluate_formula_series(ticker, days_inventory, months=3)` yields 424–479 days: a days measure on a 3-month grid is not annualised (inventory ÷ one quarter's COGS × 365). `evaluate_formula(at=<date>)` without a window pin divides last year's balance by the latest TTM flow.
2. `evaluate_formula_series` for `days_sales_outstanding` on months=3 falls back to the balance grid and never retries `total_revenues` for NVDA (whose `revenue` tag is superseded).
3. `companies.sector` holds a SIC code for names admitted from the listed universe (KO → `2080`), so a `buy` scenario refuses `no_sector` or checks the sector limit against `2080`.
4. `get_run_freshness` orders by as_of desc / completed_at desc while the runs list orders by created_at: two answers to "latest run" on a book with several runs a day. `prev` in the program language is "the completed run with the latest earlier as_of".
5. `total_debt` incomplete cover: MSFT (commercial_paper last at 2025-06-30), NVDA, KO; cascades to net_debt, debt_to_ebitda, net_debt_to_ebitda, fcf_to_debt, debt_to_operating_cash_flow, invested_capital, roic. `debt_to_ebitda` resolves for AMZN and XOM only.
6. MSFT `depreciation_amortization` is not filed; `depreciation` and `amortization_of_intangibles` exist separately.
7. Drawdown and explain-episode ledger rows carry `through` / `end` rather than `as_of` (the typed calculator now reads those as the row's date).

## C2 (claims round 2, V24 + V21 on exposure_gold, 03:50–04:08Z): what the answers showed

C2 is cheaper than every earlier round (V24: 3.5 tool calls, 51k prompt tokens, 0.60 gate refusals a
turn; V21: 4 calls, 0.29 gate refusals) and its figures_present read lower (V24 5/16, V21 3/12) — a
movement that turned out not to be one, see the note on the metric under §Results. Reading the
eleven V24 misses turn by turn, by role:

| # | turn | what the reader saw | whose boundary | root cause | fix (this tree) |
|---|---|---|---|---|---|
| 1 | N01 t1, N02 t1/t2 | the "latest" accruals ratio, DSO and revenue growth dated 2022-01-30 / 2026-01-25 while the desk holds quarters to 2026-07-26 | tool (data honesty) | NVDA's `revenue` line holds 3 facts to 2022-01-30; `total_revenues` runs to 2026-07-26. `get_flow(months=12)` / `last_n=5` settled silently on the retired line, and `evaluate_formula_series` built the DSO grid on it (defect 2 above, now understood) | `get_flow`: a latest-anchored request on a superseded line refuses `line_superseded` naming the continuing line and where the asked-for one ends; a dated start/end still reads it as filed. `evaluate_formula_series`: the grid follows the candidate whose facts reach the latest period |
| 2 | N02 t1 | "accounts receivable rose accounts receivable yoy" — a label where a figure goes; 0 figures rendered | validation (rendering identity) | a yoy over five quarterly balances has one point; `answer.fill` summarised a series only from two points | a one-point series displays its point |
| 3 | N12 t1 | "the desk has no completed run for port_1" — a false absence, gate-accepted | LLM asked with no id; tool answered a guessed id; validation accepted text | `describe(expand=…)` with no subject refused without the desk's ids; `describe('port_1', expand=…)` opened a domain view on a book that does not exist; `run(portfolio='port_1')` refused `no_completed_run` (a data class) instead of `unknown_portfolio` (an address); an `absent` claim with `text` and no fact passed | the root refusal carries `portfolios` and `issuers_prepared`; a domain view checks the subject exists first; `run` refuses `unknown_portfolio` with the ids; an absent claim points at an absence fact, and one born of a spelling-class refusal (`SPELLING_REFUSALS`, one list shared with the counters) is refused `refused_not_absent` |
| 4 | N01 t2 | three `relation_does_not_fit` on the same claim, then "6.50% (2026-01-25) from 6.50% (2026-01-25)" | validation (G2) | a change claim on a yoy point with `against` = the same point; the gate checked `against` was a scalar and nothing else | `same_figure` / `different_measures` on a change over a yoy/qoq/subtract node; the refusal says to leave `against` out or point it at the earlier reading of the base measure |
| 5 | N05 t1 | "portfolio.reconcile was not computed … unknown_run" — a real figure reported absent | tool | `method(book.reconcile, subject=port_001)`: the tool says a book method's subject may be a portfolio id; four services take a run id | run-addressed book methods (analysis, reconcile, sell, buy) resolve a `port_` subject to the book's latest completed run; the drawdown methods keep the portfolio id |
| 6 | N04 t2 | eleven holding window returns with `as_of: n/a` | tool (typing) | `calc_service.window_return` recorded no `basis`, so the typed resolver left the row undated | the row carries `basis.interval = [start, end]` |
| 7 | N01 t1 | the annual history read where the trailing-twelve-month reading was asked for | skill | the earnings-quality snippets carried only `last_n` series | the snippets open with the now-readings (TTM method, TTM flows) and then the history (model-facing: in V30_WORDING_REVIEW.md) |
| — | N03 t1/t2, N04 t1, N07 t2, N10 t1 | the gold figure not among those rendered | LLM (choice) | the model answered with neighbouring figures (full-ADV days but not quarter-ADV; drawdown depth but not its length) | none in this round; these are what the judge criteria and the skill's `close` lines are for |

Checked against the pinned baseline, so the scope of defect 1 is not overstated: the SCALAR formula
path was already correct. `evaluate_formula('GOOGL', 'net_margin')` substitutes the continuing line on
both trees and says so (`substituted_inputs: {revenue: total_revenues}`, definition "net income ÷
revenue [total revenues used for revenue]"). What was wrong, and is fixed, is the direct read
(`fundamentals(metric='revenue', months=12 | last_n=5)`) and the SERIES grid
(`evaluate_formula_series`, which anchored on the first candidate with any facts). A dated read of the
retired line still works as filed, by design.

Pins: `test_claims` (+3), `test_program_service` (chain test on the continuing line), `test_v11_absence_live`
(the superseded line), `test_v27_directory` (the root refusal carries ids; marked live). Offline suite: 2244
passed after the edits (the one failure was that unmarked live test). The counter
`answers_with_passage_mark_as_figure` now reads the model's own prose, not the rendered text (V30 renders a
quote's passage with its item in brackets, which the old counter mistook for the V24 habit).

## C3, in flight (04:18Z onward): the absence-provenance rule is too broad

C3 is the acceptance round for the C2 fixes. Reading its first 36 V26 turns while it runs, the new
rule "an `absent` claim points at a fact" fires on 10 turns. Sorting them by what the model was trying
to say:

| what it wanted to say | count | the rule's verdict | right? |
|---|---|---|---|
| a call error dressed as an absence ("abs takes one figure, so the sum was not computed") | 2 | refused; the model dropped it | yes — this is the N12 class |
| an absence the desk had already produced as a fact | 3 | refused, then the model pointed at the fact | yes — the fix working as designed |
| a policy the desk publishes ("the desk does not forecast") with no fact on this session's ledger | 1 | refused; the absence vanished from the answer | **no** |
| a refused program node whose fact WAS on the ledger | 1 | refused; the model dropped it rather than find it | partly — discoverability |
| a concept the desk does not model at all (a bond's wrapper-vs-underlying split) | 1 | refused; dropped | **no** |
| coverage refusals (`unknown_name`: "$run holds no column x.y"; `unknown_point`; `unknown_method`) | 2 | refused as "spelling" | **no** |

Two defects, both in the same place — `claims.SPELLING_REFUSALS` is doing the work of a distinction it
cannot make:

1. **The list conflates "the desk did not understand the address" with "the desk understood and does not
   hold it".** `unknown_portfolio` on a guessed id is the first; `unknown_name` ("this run holds no column
   `issuer_exposures.quantity`; available: …"), `unknown_point` ("no point at 2025-03-31; held: …"),
   `unknown_method` ("not a method this desk has; nearest: …") and `unknown_metric` ("not a normalised
   metric") are all the second — each names what the desk does hold, which is exactly a coverage
   statement a reader is entitled to. Fix: narrow the set to ids, argument shapes and type errors, and
   let the vocabulary/coverage refusals be claimable absences.
2. **A policy the desk publishes has no address unless `describe` was called.** `catalogue_service.CANNOT`
   holds three rules (no forecast; no per-name factor sensitivity; a scenario does not re-fit). They
   become facts only through a `describe` result, so whether the model can honestly say "this desk does
   not forecast" depends on whether it happened to open the catalogue first. A rule is not session state.
   Fix: an absent claim may address a rule instead of a fact — `{"relation": "absent", "policy":
   "forecast"}` — and the gate resolves the key against the desk's own table, rendering the desk's
   sentence verbatim rather than the model's paraphrase. The model can neither invent a policy nor
   reword one.

By role: (1) is validation over-reaching into what the tool said — the gate was asked to judge
provenance and instead judged a refusal code it had no business classifying that finely. (2) is skill
knowledge (what this desk will not do) with no address in the answer protocol, so validation could only
see free text and was right to refuse it; the missing piece is the address, not the check.

Both fixes are held until C3 finishes — the tree stays still while a round is being measured — and land
as C4. C3's `honest_absence` therefore measures the over-broad rule, and is expected to sit at or below
C2's.

Also read from the same turns (the other process of this transcript, before the split): 14 turns were
refused `no_ordering` (a rank claim on a fact with no rank) and none went back to compute a `rank`/`top`
node — all reworded; the counters' `superlatives_without_rank` is the number to watch on C3. Six
`change` claims put two measures of one subject against each other (rolling_vol_30d against
rolling_vol_60d); that is a `versus`, and the refusal now says so. Two gate changes made while C3 ran
(they reach C4, not C3): `claim_without_of` on an absent claim lists the session's absence facts with
their refusal class and citability, and says an absence the ledger holds no fact for is said in the prose
with no claim.


## Results

**Counters.** Every `*_counters.json` was recomputed at 04:42Z with one classifier (the earlier V24 C2 scoring predated the shared spelling list, so `malformed_program` fell into "other"); the spelling row below is on that classifier.

**Validity.** Baseline replicates come from the worktree pinned at e6c290b (`run_all.log` says so per set).
V26 R1 was run before that worktree existed and is discarded; V26 R2 is the V26 baseline. Every round
listed below finished before 04:12Z with zero `calls=0` turns. Judge columns are three replicates
(so_what / follows_on / honest_absence); blank where the judge did not run.

**Which rounds count.** The OpenAI account ran out of credits twice today (`429 insufficient_quota`, at
04:12Z and again at 04:54Z). A turn that hits it records `calls=0` with an `ExceptionGroup` and no
answer, so the rounds sort cleanly:

| round | turns | failed | verdict |
|---|---|---|---|
| V26 R2, V21 R2, V24 R2 (baseline) | 140 / 31 / 20 | 0 | valid |
| V26 R3 (baseline) | 140 | 0 | valid (its one `calls=0` is a legitimate no-tool answer) |
| V21 R3 (baseline) | 31 | 0 | valid |
| V24 R3 (baseline) | 20 | 20 | **invalid — every turn hit the 429** |
| V21 C1/C2, V24 C1/C2 (V30) | 31 / 20 | 0 | valid |
| V26 C3 (V30) | 140 | 0 | valid |
| V24 C3 (V30) | 20 | 1 | usable, 19 of 20 (N12 t2 lost to the 429) |
| V21 C3 (V30) | 19 | 19 | **invalid — stopped at 04:55Z** |

The gpt-5.5 arm (D4) is dropped on the boss's instruction: gpt-5.4-mini only.

**To resume when credits are added.** The tree has moved since C3's face was loaded, so the next round is
C4, not a C3 repeat: `/tmp/run_c4_after_c3.sh` (edit out the wait on `C3 done`) restarts the :8106 face
over `exposure_gold` and runs v26 → v24 → v21 into `*_C4.json` with scoring chained. C4 is worth two
things at once — the SECOND V30 replicate on the powered set, which is what a correctness claim needs,
and the measurement of the five fixes made after C3's face loaded. Also outstanding: V24 R3 and V21 C3
reruns, and the V26 C3 judge (`scripts/v30_score.sh docs/spikes/v30/V26_C3.json v26 3`).

### V24 (20 turns)

| metric | R1 | R2 | B1 | C1 | C2 |
|---|---|---|---|---|---|
| tool calls p50 | 8.5 | 7 | 5 | 4 | 3.5 |
| prompt tokens p50 | 82.9k | 62.7k | 54.9k | 71.4k | 51.3k |
| respond attempts | 1.55 | 1.75 | 2 | 2.85 | 2.05 |
| gate exhausted | 1 | 1 | 0 | 1 | 0 |
| spelling refusals/turn | 1.20 | 1.40 | 0.85 | 0.75 | 0.55 |
| gate refusals/turn | 0.55 | 0.75 | 0.50 | 1.30 | 0.60 |
| double-figure artifacts | 0 | 1 | 0 | 0 | 0 |
| superlatives w/o rank | 6 | 5 | 5 | 6 | 5 |
| figures_present | 9/16 | 7/16 | 7/16 | 7/16 | 5/16 |
| so_what (×3) | 4/9 | | 5/9 | 4/9 | 6/9 |
| follows_on (×3) | 7/8 | | 6/8 | 6/8 | 6/8 |
| honest_absence (×3) | 1/3 | | 3/3 | 1/3 | 1/3 |

### V21 (31 turns)

| metric | R1 | R2 | B1 | C1 | C2 |
|---|---|---|---|---|---|
| tool calls p50 | 7 | 7 | 5 | 4 | 4 |
| prompt tokens p50 | 96.4k | 73.2k | 49.3k | 46.3k | 57.4k |
| respond attempts | 1.9 | 1.61 | 2.65 | 2.26 | 2 |
| gate exhausted | 2 | 1 | 2 | 0 | 0 |
| spelling refusals/turn | 1.71 | 1.29 | 1.13 | 0.94 | 0.68 |
| gate refusals/turn | 0.94 | 0.61 | 1.16 | 0.48 | 0.29 |
| double-figure artifacts | 3 | 3 | 0 | 1 | 0 |
| superlatives w/o rank | 7 | 10 | 7 | 6 | 9 |
| figures_present | 4/12 | 3/12 | 2/12 | 4/12 | 3/12 |
| so_what (×3) | 8/15 | | 6/15 | 9/15 | |
| follows_on (×3) | 12/18 | | 12/18 | 13/18 | |
| honest_absence (×3) | 1/3 | | 1/3 | 1/3 | |

### V26 (140 turns) — the powered comparison

Two baseline replicates from the pinned worktree against one V30 round on the fixed tree. All three
finished with zero exceptions; R3's single `calls=0` turn is a legitimate no-tool answer.

| metric | R2 (base) | R3 (base) | C3 (V30) |
|---|---|---|---|
| tool calls p50 | 6 | 6 | **4** |
| round trips p50 | 8 | 8 | **6** |
| prompt tokens p50 | 67.6k | 68.0k | 66.5k |
| respond attempts | 2.07 | 2.08 | 2.70 |
| gate exhausted | 3 | 3 | 6 |
| spelling refusals/turn | 1.21 | 1.31 | **0.45** |
| gate refusals/turn | 1.04 | 1.06 | 1.00 |
| algebra refusals/turn | 0.04 | 0.08 | **0** |
| data refusals/turn | 0.21 | 0.20 | 0.10 |
| double-figure artifacts | 12 | 11 | **5** |
| passage mark as figure | 12 | 11 | 16 |
| superlatives without a rank | 37 | 36 | 37 |
| figures_present (binary) | 6/109 | 4/109 | 8/109 |
| **must-figure recall** | 29.6% | 22.8% | **31.0%** |

What it says, kept to what the numbers carry:

- **Addressing is where V30 wins, and the win is larger than the replicate spread.** Wrong-address
  refusals fall from 1.21–1.31 a turn to 0.45, algebra refusals to zero, data refusals by half. The
  program with a symbol table replaces most of what the per-call protocol got wrong.
- **Cost falls by a third in calls and round trips, and not at all in tokens.** 6→4 calls, 8→6 round
  trips, 67.6k→66.5k prompt tokens. On V24 and V21 tokens fell a third; on V26 they do not, because the
  answer loop puts back what the addressing loop saved — respond attempts rise from 2.07 to 2.70.
- **Reader-visible arithmetic defects halve**: 11–12 double-figure artifacts to 5.
- **Correctness is unchanged.** The figure-weighted recall (31.0% against 29.6% and 22.8%) reads like a
  small gain and is not one. Must-figures inside a turn are not independent: one liquidity ladder
  contributes thirteen of them from a single program, so the effective sample is the 109 TURNS, not the
  707 figures. Scored per turn and paired, C3 against R2 is better on 26 turns, worse on 26, tied on 57
  — a dead heat — while the two BASELINE replicates of identical code differ more than that (R2 better
  on 28, worse on 17). Turn-mean recall: R2 26.0%, R3 22.7%, C3 27.0%.

  The same non-independence makes every per-family reading an artefact until it is split by replicate:

  | family | turns | musts | R2 | R3 | C3 | baseline spread |
  |---|---|---|---|---|---|---|
  | W | 62 | 349 | 24.1% | 26.6% | 24.9% | 2.6 pts |
  | L | 12 | 154 | 48.1% | 12.3% | 50.6% | **35.7 pts** |
  | F | 9 | 80 | 20.0% | 23.8% | 31.2% | 3.7 pts |
  | NEW | 12 | 70 | 24.3% | 22.9% | 15.7% | 1.4 pts |
  | FQ | 8 | 28 | 42.9% | 39.3% | 57.1% | 3.6 pts |
  | B | 6 | 26 | 23.1% | 11.5% | 7.7% | 11.5 pts |

  The liquidity family looks like V30's clearest win (+26 points over R3) and is entirely R3 having a bad
  L run on identical code; C3 is simply back at R2's level. W is the only family with both a large sample
  and replicate stability, and there V30 is flat. **No per-family gain should be reported from this data.**

- **What the instrument can and cannot see.** At the turn level the two baseline replicates differ by
  about 7 points, so nothing smaller than that is detectable. More figures per turn do not help — they
  are correlated within the turn. Only more REPLICATES do.
- **The gate is where V30 pays.** Gate-exhausted turns double (3 → 6) and respond attempts rise a third.
  The claims protocol is not converging on those turns, and the C3 refusal census says why: 48
  `claim_without_of` (an absence with no fact), 27 figure-relations aimed at a filing passage, 19
  change-across-two-measures, 15 superlatives with no rank node. The first two are fixed in this tree
  after C3's face was loaded and are what C4 measures; the last two are the model's choice.
- **Superlatives without a rank do not move** (37 / 36 / 37). Neither protocol makes the model compute
  an ordering before claiming one; the gate refuses the claim, and the model re-words rather than ranks.

### What the numbers say so far

- The cost side moved the way the plan predicted and holds across two sets and two replicates of the
  baseline: half the tool calls, a third fewer prompt tokens, spelling refusals down 2–3×, no gate
  exhaustion in C1/C2, no double-figure artifacts.
- **The correctness metric cannot discriminate on V24 or V21, and its own baseline proves it.**
  `figures_present` is all-or-nothing over a turn's `must` figures, and V24 carries 23 of them across 16
  scored turns, V21 21 across 12 — one miss zeroes a turn. Graded recall (the SHARE of must figures
  rendered, `scripts/v30_figure_recall.py`, same tolerance, no rescoring) puts the two BASELINE
  replicates at V24 60.9% (R1) against 43.5% (R2): a 17-point swing from the same code, fixture and
  model. Every V30 arm on V24 and V21 sits inside that spread. V21 C2 is the sharpest illustration —
  the highest recall of any V21 round at 57.1%, and joint-lowest on the binary metric at 4/12. So the
  earlier reading, that figures_present "fell" in C2, is withdrawn: it is replicate noise, and the
  binary form of the metric is the wrong instrument on these two sets.

  | round | recall | must | turns | binary |
  |---|---|---|---|---|
  | V24 R1 / R2 / B1 / C1 / C2 | 60.9% / 43.5% / 43.5% / 52.2% / 39.1% | 23 | 16 | 9 / 7 / 7 / 7 / 5 |
  | V21 R1 / R2 / B1 / C1 / C2 | 47.6% / 42.9% / 28.6% / 42.9% / 57.1% | 21 | 12 | 4 / 3 / 2 / 4 / 3 |
  | V26 R2 (baseline) | 29.6% | 707 | 109 | 6 |

- **V26 is the only powered correctness comparison** — 707 must figures over 109 turns — and it is the
  one whose V30 arm (C3) had not been run when the C2 conclusions were written. Of the eleven V24 C2
  misses, seven were desk defects the round exposed (the table above) and are fixed in this tree; four
  are the model's choice of figure. Until V26 C3 is scored against R2 and R3, the honest statement stays
  "cost halved, correctness of the delivered figure not yet measured with an instrument that could show
  it".
- The judge (three replicates) is within its own spread everywhere except V24 B1 honest_absence 3/3,
  which C1/C2 did not repeat; the absence provenance fix is aimed at exactly that criterion.
- The baseline's own replicate spread (R1 vs R2: V24 figures 9→7, tokens 83k→63k) is as wide as several
  of the V30 deltas; the R3 replicate and the gpt-5.5 arm are what settle which deltas are real.

