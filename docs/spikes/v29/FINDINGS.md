# V29 — the rebuild, and what 331 live turns say about V27 and V28

Run 2026-09-08 against the rebuilt stack (`fbe240c`), the four images rebuilt and each
V27/V28 marker verified by grepping the code **inside the containers** (the 2026-08-27 rule:
the criterion is the container, not the commit record).

Instrument conditions (X26): serial, `--concurrency 1`; a fresh completed run already on the
book so no turn reaches for `start`; every tool call through the MCP container
(`MCP_URL=127.0.0.1:8104`); two replicates.

| | turns | exceptions | book before → after |
|---|---|---|---|
| replicate 1 (V26 + V21 + V24) | 191 | 0 | 40 runs → 40 runs, same as_of |
| replicate 2 (V26 only, see §5) | 140 | 0 | 40 → 41 (one turn started a run) |

---

## 1. What the directory bought — mechanical counters, 09-07 serial → 09-08 R1 (191 turns each)

Countable, reproducible, and independent of the judge. The replicate-to-replicate spread on
identical code is in the third column (V26 set, 140 turns, R1 vs R2).

| counter | 09-07 | 09-08 R1 | R1 vs R2 spread |
|---|---|---|---|
| method name → `read_book` (Y1, the run's dominant error) | 132 in 51 turns | **5 in 3** | 5 vs 7 |
| domain name → `read_book` (P2) | 10 in 6 | **1 in 1** | 0 vs 0 |
| method name → `read_fundamentals` (X13) | 17 in 7 | **2 in 2** | 2 vs 3 |
| filed line → `compute(method=)` (P6) | 46 in 7 | **14 in 6** | 8 vs 7 |
| `unknown_method` | 32 in 13 | **0** | 0 vs 0 |
| `unknown_series` (A1) | 43 in 23 | **0** | 0 vs 0 |
| `op_or_method` at the service (A2) | 43 in 23 | **0** | 0 vs 0 |
| … now refused by the schema before spend | — | 22 in 9 | 13 vs 10 |
| `describe(expand='filings')` crashing the adapter (C2/X3) | 21 | **0** | 0 vs 0 |
| ONE domain opened (`expand=<domain>`, V27 new) | 0 (impossible) | **172 in 127** | 119 vs 121 |
| all domains opened at once (`expand='procedures'`) | 6 | 0 | 0 vs 0 |
| distinct methods that produced a figure | 35 / 46 | **40 / 46** | — |

The five methods the 2026-09-07 run named as never producing a figure:

| method | 09-07 ok / fail | 09-08 ok / fail |
|---|---|---|
| `price.beta` | 4 / 10 | **9 / 2** |
| `gross_margin` | 5 / 2 | **10 / 0** |
| `book.drawdown_episodes` | 2 / 3 | **10 / 5** |
| `book.explain_episode` (never attempted on 09-07) | 0 / 0 | **7 / 2** |
| `issuer.panel` | 3 / 0 | **9 / 0** |

**A counter that rose and means the opposite of what it looks like.** `metric_not_filed` 26 → 34.
On 09-07 those 26 were 17 method names at the wrong door, 6 invented names and 3 genuine
absences. On 09-08 all 34 are genuine — "this issuer did not file that line". Wrong-door and
invented names are gone; what is left is the desk being honest about ingest. (This counter is
also the noisiest: 33 in R1 against 11 in R2 on the same code.)

## 2. What the tree costs

`expand` at the root is refused 91 times in ~67 of 140 turns. The model writes
`describe(subject=null, expand=<domain>)` because the root's domain list carries a PLACEHOLDER
subject (`describe('<port_…>', expand=…)`) — by design, the root does not choose a subject.
After the refusal: 79 recover to `describe()` (correct), 19 jump straight to
`describe(subject, expand=<domain>)` (best), and **30 write the same call again**.

Cost: ~0.7 calls per turn. Calls per turn median 5 → 6, mean 6.1 → 7.0; turns at or over the
15-call budget 8 → 9; calls held back behind a refusal 82 → 60.

**Candidate fix, not built:** the refusal already carries `next` with placeholders. Carrying the
desk's REAL portfolio ids there would make recovery one call instead of two — listing the ids is
a fact about the desk, not a choice made for the model, so it stays inside the rule that the tree
returns facts and addresses and never resolves intent.

## 3. Three more adapter crashes, all of one shape: a payload nobody had exercised

Found by the rerun, fixed after it (so they are still present in both replicates' traces):

| crash | why it had never been seen |
|---|---|
| `book.explain_episode` → `portfolio_window_return` undeclared | called **0 times** in the 244-turn V26 battery; V27's directory routed the model there and the route died on first use |
| `compute(method=[…list…])` → `TypeError: unhashable type: 'list'` | introduced by this batch's own fix; `method` may be a list and `method in skill.METHODS` raises |
| `op` set statistic → `entries` undeclared | V25's set statistics were measured at **zero uses** in 102 turns, so the key had never met the adapter |

Fix, at the boundary the V28 C2 rule names: a method's unit is declared once on the METHOD
(`skill.Method.unit_class`) and the adapter reads it; a specific key still wins (`sessions` stays
a COUNT). Guard extended from "every method" to **every compute shape and all twelve ops** —
fixtures cannot cover a shape nobody has asked for.

**The discipline this run adds:** *a capability with zero uses is not "unused", it is unverified.*
Three of this run's defects were in routes the previous battery never took.

## 4. And one that took the whole desk down

The V28 A2 exclusivity shipped as a top-level JSON Schema `not`. jsonschema accepted it, 2,191
offline tests passed, and the provider rejected every function:

> `schema must have type 'object' and not have 'oneOf'/'anyOf'/'allOf'/'enum'/'const'/'not' at the top level`

The first battery run produced 140 turns of **zero tool calls**, and live chat on
desk-for-one.com was broken from the deploy until it was found. The constraint moved to the
tool's own declaration (`registry.Shapes`), enforced by the registry after validation and before
any spend. Two guards: a structural test encoding the provider's rule, and a live test that asks
the provider itself.

**The discipline:** *offline green is not a contract. Anything sent to an external service needs
one guard that actually sends it.*

## 5. Scores — settled with two replicates

| set | 09-07 serial | 09-08 R1 | 09-08 R2 |
|---|---|---|---|
| V26 (140 turns) | 266/466 | 248/466 | **270/466** |
| V21 (31 turns) | 59/87 | 54/87 | **62/87** |
| V24 (20 turns) | 25/53 | 23/53 | **31/53** |
| **total** | **350/606** | 325/606 | 363/606 |

**Two replicates of identical code differ by 38 points on 606 (6.3%), and 09-07's 350 sits inside
that spread.** The apparent −25 in replicate 1 was the instrument, not the change; replicate 2 is
+13 the other way. Mean of the two replicates 344/606 against 09-07's 350/606. **Overall answer
quality is unchanged, within a spread this instrument cannot resolve.** (X7 measured the same
thing at ±5 on 87 for V21 alone; at 606 judgements the spread is ±19.)

Per criterion, the useful test is whether 09-07 falls INSIDE the two replicates' range:

| criterion | 09-07 | R1 | R2 | 09-07 inside the spread? | reading |
|---|---|---|---|---|---|
| precision | 74/103 | 57 | 65 | **NO — above both** | genuinely down |
| so_what | 44/97 | 35 | 39 | **NO — above both** | genuinely down |
| follows_on | 69/110 | 73 | 75 | **NO — below both** | genuinely up |
| honest_absence | 47/87 | 49 | 52 | **NO — below both** | genuinely up |
| trigger | 9/20 | 10 | 10 | NO — below both | up by one |
| grounded_claims | 81/135 | 79 | 92 | yes | no signal |
| ranking | 16/37 | 12 | 18 | yes | no signal |
| netting | 6/13 | 6 | 9 | yes | no signal |

So the directory bought `follows_on`, `honest_absence` and `trigger`, cost `precision` and
`so_what`, and left the total flat.

### Why precision fell, and which layer owns it

The criterion rewards reader-appropriate rounding and penalises ledger-raw precision. Read
against the traces, the same questions now carry MORE figures because more methods resolve:

- `L06`: 09-07 *"$2.20M … 0.0002 days"* → 09-08 *"16.1% … 15.0% … 20.0% … 3.90% … $10.86M"*
- `B03`: 09-07 *"AMZN at 0.65×, XOM at 0.23×"* → 09-08 *"0.11×, 0.10×"* — not a wrong figure:
  09-07 computed `debt_to_ebitda` and 09-08 computed `net_debt_to_ebitda`, each correct for what
  it computed (though the sentence calls the second by the first's name)

**The precision a reader sees is decided in exactly one place and the model has no say in it.**
The model writes `{fact: id}`; `analytics/display_conventions.display()` prints the value
(mirrored by `apps/web/lib/display.ts`). Confirmed against the live function:

| value, unit | printed |
|---|---|
| 0.161050 RATIO | `16.1%` |
| 0.0390 RATIO | `3.90%` |
| 10,859,692 MONEY | `$10.86M` |
| 0.65357918 MULTIPLE | `0.65×` |

The conventions did not change between the runs; what changed is how many figures reach the
sentence. So `precision` is a **user report** matter, fixable without touching the model or the
gate — and `3.90%` (a trailing zero on a sub-10% ratio) is the clearest case.

Budget is NOT the cause: turns at the 15-call ceiling went 8 → 9, calls per turn median 5 → 6.
`rank` succeeded MORE often (7 turns → 11), so the `ranking` reading is not fewer orderings.

## 5b. The instrument again: the desk under test is a live production book

Two exposure runs appeared on `port_001` during 2026-09-08. One at 04:32 tagged
`agent:sess_ff4075e179c2` — **a battery turn started it**: that session's step 23 is
`start(kind='exposure_run', reason="Need the portfolio's market-risk and drawdown…")`, and it
succeeded. The other, at 10:30, is tagged `scheduled`: the production daily update, outside any
battery. So replicate 2 broke the X26 condition twice over, once by the battery and once by the
desk's own clock.

The model started a run although `sessions_behind` was 0 and a completed run for the same session
already existed — X2 unchanged: nothing tells it that the fresh run it wants is already there.

They are numerically identical to the run replicate 1 read — same market value 10,859,692.00,
same daily return −0.01142426, same MSFT weight 0.161050; `max_drawdown` differs in the seventh
decimal — so figure-level comparisons between replicates are unaffected. What changes is
`latest_completed_run`: replicate 1 read `run_72e6617afeb7`, and anything run after 10:30 reads
`run_34042d64f60c`.

**X26 needs one more condition:** a battery must run against a frozen book or its own portfolio.
`port_001` is the live demo book, and its scheduler will change what "latest" means mid-run.
The 2026-09-07 finding was that the battery mutates the desk; this run adds that the DESK mutates
itself on a clock.

## 5c. The scores, settled: the instrument cannot resolve the difference

Two replicates of the SAME code, all three sets, 606 criteria judgements:

| | 09-07 serial | 09-08 R1 | 09-09 R2 | \|R1−R2\| | 09-07 inside the replicate range? |
|---|---|---|---|---|---|
| V26 (466) | 266 | 248 | 270 | 22 | yes |
| V21 (87) | 59 | 54 | 61 | 7 | yes |
| V24 (53) | 25 | 23 | 30 | 7 | yes |
| **TOTAL (606)** | **350** | **325** | **361** | **36 (5.9%)** | **yes** |

**The 09-07 baseline lies between the two replicates of the new code.** The −25 I flagged after
replicate 1 was the instrument, not the change. This is X7 restated with the spread finally
measured on the code under test rather than assumed.

Per criterion, the baseline is outside the replicate range in five places — the only places where
a directional read is even arguable:

| criterion | 09-07 | R1 | R2 | reading |
|---|---|---|---|---|
| follows_on | 69/110 | 73 | 73 | improved, and both replicates agree |
| honest_absence | 47/87 | 49 | 51 | improved |
| trigger | 9/20 | 10 | 10 | improved |
| **precision** | **74/103** | **57** | **65** | **worse, in both replicates** |
| **so_what** | **44/97** | **35** | **38** | **worse, in both replicates** |

`precision` and `so_what` are the two to watch. Read against the traces, the mechanism is
visible and is a consequence of the fixes: more methods resolve, so answers carry more figures,
and the criterion penalises "ledger-raw precision" — `L06` went from *"$2.20M … 0.0002 days"* to
*"16.1%, 15.0%, 20.0% … 3.90% … $10.86M"*. Whether that is worse for a reader is a judgement the
rubric makes and this run does not settle. Budget is not the cause (turns at the 15-call ceiling
8 → 9) and neither is less ordering (`rank` succeeded in 7 turns → 11).

## 5d. A fourth crash of the same shape, and the one that reached the reader

`rank`'s `spread` is max − min **of the ranked measure**, so it carries that measure's unit —
MONEY when market values are ranked. `fact_adapters.UNIT_BY_KEY` pinned `"spread": RATIO`, and
the key list beats the producer's declaration, so a $1,135,470 spread was minted as a RATIO and
rendered to the reader as **"113547000.0%"** (`L01-raise-by-friday#2`).

That is the fourth time in this batch that a consumer-side guess overruled a producer that knew,
and the first one that reached a reader rather than throwing. Fixed the same way: keys whose unit
is not a property of their name (`spread`, `difference`, `gap`) take the unit the result declares
in `type.unit_class`, and an undeclared one is refused, not defaulted. Verified: rank over
MONEY → MONEY spread, over RATIO → RATIO, and `book.reconcile`'s ratio gaps unchanged.

**The rule this settles:** a unit belongs to a QUANTITY, not to a key name. Where a key can carry
different units in different results, only the producer can say which, and the adapter must read
it rather than guess — `UNIT_BY_KEY` is for names whose unit is fixed by definition (`sessions` is
always a count, drawdown `depth` is always a ratio).

## 6. Still open

- Reader-visible defects: `620.9% days` (a ratio called days, the X15 role-error class, unchanged
  by this batch — it was deliberately out of scope) and `$$10.86M × 3.90%` (an arithmetic
  expression written into prose instead of computed). Full adversarial sweep pending.
- The 27 pre-existing live-test failures: all V23 leftovers referencing tools deleted then
  (`get_flow`, `_get_task_status`, `formulas`). Baseline confirmed: 28 before this batch, 27
  after, **0 new**, 1 fixed. "Live green" has not been a meaningful claim in this repo for weeks.
