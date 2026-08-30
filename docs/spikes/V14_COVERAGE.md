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
