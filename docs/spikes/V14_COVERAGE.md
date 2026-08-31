# V14 — what was measured, including what did not work

> 2026-08-30/31. Instrument: `scripts/rubric_battery.py` over `tests/battery/questions_v14.json`.
> Traces and scores: session scratchpad (`baseline_n1`, `after_a`, `after_ab_n3`).

## 1. The three configurations

| criterion | baseline n=1 | A only n=1 | A+B n=3 |
|---|---|---|---|
| grounded_claims | 3/3 (100%) | 2/3 (66%) | 6/9 (66%) |
| netting | 3/3 (100%) | 2/3 (66%) | 6/9 (66%) |
| no_linear_locating | 0/1 (0%) | 0/1 (0%) | 0/3 (0%) |
| precision | 3/8 (37%) | 4/8 (50%) | 14/24 (58%) |
| ranking | 2/6 (33%) | 1/6 (16%) | 5/18 (27%) |
| read_required_inputs | 2/4 (50%) | 3/4 (75%) | 6/12 (50%) |
| so_what | 2/6 (33%) | 1/6 (16%) | 6/18 (33%) |
| trigger | 2/2 (100%) | 2/2 (100%) | 4/6 (66%) |
| **TOTAL** | **17/33 (51.5%)** | **15/33 (45.5%)** | **47/99 (47.5%)** |

All three sit in the same band. **Nothing moved outside noise.** The three 100%s
in the baseline column are n=1 flukes on two- and three-item samples; at n=3 the
same criteria read 66%, which is the honest level.

## 2. A-only: the arithmetic landed, the shape did not

`get_portfolio_analysis` was called and used — V1's trace shows it second, right
after the snapshot, and `read_required_inputs` rose 2/4 → 3/4. The ranking, the
netting and the headroom all arrived, correct and citable (§4).

And `ranking` **fell**, 2/6 → 1/6. An ordered payload does not produce an
ordered answer: nothing in the turn asked for one, so the model read the ordered
table and wrote a list. This is the finding A was designed to test, and it
answers cleanly — **ordering the data is necessary and not sufficient**.

One defect surfaced by the run rather than by the score: V7's A-only answer was
a *promise* — "I'm pulling the issuer's latest filed fundamentals … I'll come
back with traced numbers only" — which passed the gate because an answer with no
numbers needs no citations. The gate cannot see it; the rubric scored it 0/4.
The class is the one round 4 named: verification's unit is the number, meaning's
unit is the sentence.

## 3. B: the frames reached the model and did not change the answer

Verified they arrived rather than assumed it: 24 of 24 runs called a frames
carrier, and the tool results carry the key (`keys: portfolios, frames`). So this
is a measurement of the frames, not of their absence.

Against the baseline, the criteria they were written for are flat: `ranking`
33% → 27%, `so_what` 33% → 33%, `no_linear_locating` 0% → 0%. `precision` rose
37% → 58% across the three configurations, but it rose in A-only too (50%) where
no frame existed, so the trend does not belong to B on this evidence.

Cost, measured: 707 tokens on every portfolio locating call, 646 on every issuer
one.

**Conclusion: B does not ship in this form.** V12 earned its payload — total
debt 12/24 → 24/24 — and the standard it set is the one B fails. The lever that
moved ROUTING did not move SHAPE.

Why the two differ is the useful part. V12's knowledge answers *which* — which
metric, which producer, which window — and a model that knows which one to pick
picks it. A frame asks for a property of the finished text: order these, net
those, close on the implication. Between the frame arriving and the answer being
written sit thirty thousand tokens of tool payload and the model's own idea of
what an answer looks like. **A mechanical property can be enforced where it is
mechanical; a property of prose cannot be suggested into existence.**

That is the argument for V14-C, and it is stronger after this measurement than
before it: an ordered table cannot be listed flat if the answer's shape is a
table, and a promise cannot pass an exit whose blocks must resolve to rows.

## 4. What did ship, and how it was verified

**The persist-step repair** (`02a9809`). `_persist_outputs` read `limit_checks`,
a local of `run()`; every exposure run since V13 raised NameError at the last
step, after all the arithmetic. Verified where it failed: worker image rebuilt,
`run_d1bbfadbbb7e` completed, 27 checks each carrying current/warning/breach
against 0 of 27 on the run before it. `tests/test_workflow_name_resolution.py`
holds the class — every function in the three workflow modules is walked for
names that resolve to nothing — and fails on the pre-fix tree.

**V14-A** (`03c7cc3`). On run_d1bbfadbbb7e: market_downside ranked first at 7.44%
and sitting 0.56pp under its breach; `equity_down` net −0.80 against gross 1.57,
the growth (−0.187) and small-cap (−0.197) legs offsetting the market leg
(+1.185); 62 quotable values from one ledger row. The netting is the figure a
flat listing cannot show, and it is now a number rather than a reading.

A ships on its own merits — the arithmetic is correct, cited and cheaper than
having a model redo it — while the answer-shape claim it was half of does not
hold without C.

## 5. Standing

- **E** shipped (`383e80d`): the instrument, and it worked — it caught the
  promise-answer the gate could not, and it is what makes §3 a finding rather
  than an impression.
- **A** shipped (`03c7cc3`).
- **B** written, deployed to the containers for measurement, **not committed**.
  Two reasons and both hold: no measured effect, and the frames are prose the
  model reads, which is wording that gets reviewed before it is committed.
- **C+D** unstarted, and better motivated than when the plan was written.

## 6. Open

- The baseline was measured at n=1 and A+B at n=3. The per-criterion rates are
  what is compared and they are stable across the two n=1 runs, but a baseline
  at n=3 would make §3 exact rather than persuasive. It costs two image rebuilds.
- `no_linear_locating` is 0/3: V2 still spends eleven calls locating ten
  holdings. A gave the book-level question one call; the per-issuer question
  still pays per issuer, and nothing in A addresses that.
- If any part of B is kept, the candidate is the precision rule, which is the
  one mechanical sentence among them — and §3 cannot attribute the precision
  movement to it.

---

# V14-C — the block exit: what it buys, what it costs, and the criterion it fails

## 7. The switch, and the four probes it took

The exit stopped accepting prose. An answer is blocks; a figure is a slot; text
may not carry a number. Four probes of the same three questions, each failure
diagnosed to a deterministic cause rather than to model capacity:

| probe | answered | causes found and fixed |
|---|---|---|
| 1 | 0/3 | the contract never said a slot holds ONE NUMBER — alert sentences and ids went into slots |
| 2 | 2/3 | a refusal named no way out when a figure sat under a different ref |
| 3 | 2/3 | limit thresholds were **unciteable**: V13-S5 added the three columns, `_RUN_CHILDREN` still declared limit_checks as holding no values |
| 4 | 3/3 | tables in two of three, 21 and 10 slots, all resolving |

The third is the same omission as this batch's other repair, one layer over: the
columns were written and nothing could quote them, so "MSFT at 16.3% against a
15% warning level" was refused for a level living in a row the resolver did not
read. A run now resolves **235 values where it resolved 154**.

## 8. What the exit demonstrably buys

V2 — the question the original session answered with ten `describe_issuer` calls
and sell-side prose — now comes back as a table: ticker, business, main macro
risks, one row per holding. That is the integration V14-B asked for in words and
did not get. Nothing suggested it; the schema made a table the natural shape.

Also standing, and mechanical rather than suggested: every figure a reader sees
is the ledger's own value, formatted by the renderer (16.3%, $10.87M) with the
exact value on hover. Two assertion classes are gated for the first time — a
trend must carry the series it was read from, an absence the row a refused read
minted. Neither claim contains a number, so neither was ever visible to the
numeric gate; the risk-history answer round 4 could not refuse is refusable now.

## 9. The criterion it fails

The plan set three acceptance criteria for the switch. ① correctness holds by
construction — a slot resolves to a ledger row or the answer is refused. ③ model
capability is cleared — 8 of 8 answered. **② the ratchet disappears: FAILED.**

| | baseline | after C |
|---|---|---|
| gate refusals, median | 1 | **5** |
| answers reaching the exit | 8/8 | 8/8 |
| questions that exhausted every attempt | 0 | **2** (V4, V7) |
| rubric total | 17/33 | 8/33 |

The ratchet did not go away. It moved: from transcribing one figure at a time to
getting twenty slots' refs right at once. V1 in probe 4 carried 21 slots; an
answer that size, refused, is an answer where the model fixes five slots and
breaks two.

**The rubric total is partly an artefact and must not be read as a fourfold
regression.** The judge scores the STORED PROSE, and for a block answer that
string carries ledger precision and renders a table as pipe-separated lines —
the display conventions live in the renderer, which the judge never sees. So
`precision` and `ranking` are being measured on an artefact the reader is not
shown. V2 scored 3/4 through that handicap. What is NOT an artefact: two
questions produced no answer at all, and those score zero honestly.

## 10. Diagnosed and open

- **Fixed, not yet deployed**: an `absence` block with no ref was a dead end. Most
  of what a model wants to say in that shape is weaker and true — the desk could
  not compute it, the window does not reach — and that is ordinary prose. The
  refusal now says so. V7 spent eight attempts in this trap.
- **Open**: a twenty-slot answer refused once is hard to repair in one edit. The
  refusal reports every problem at once, which is necessary and not sufficient.
- **Open**: `held_instead_by` searches only the refs already in the answer. A
  figure whose row the model never cited gets no hint, and the session trail
  would give one.
- **Open, methodological**: the instrument scores the wrong artefact for block
  answers. Either the rubric reads the rendered form, or the display conventions
  move server-side — and they cannot simply be copied, because two rules about
  how a number looks disagree the first time one changes.

## 11. Standing

C is committed and live. It is the first thing in V14 to change the SHAPE of an
answer rather than ask for it, and it fails the ratchet criterion its own plan
set. Both are true. The decision it leaves open is whether to hold the exit
while the four items in §10 are worked, or to revert to prose and keep the block
layer for the renderer — and that is a product call, not a measurement.
