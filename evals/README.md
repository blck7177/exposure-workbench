# evals — offline measurement, never the runtime

Design v0.4 §05/§10 (V2 P5): the semantic reviewer is a **measuring instrument**. It reads a
frozen corpus of a round's questions, replies and refusals with their evidence, and a set of
human labels, and reports how often a model judge agrees with the labels — false alarms, misses
and undecided — so the desk can decide what its deterministic checks are missing.

What it may not do, and what `tests/test_v2_audit.py` pins (acceptance A1):

- nothing under `src/`, `apps/` or `scripts/` imports `evals`;
- the three Dockerfiles copy no `evals/`, so the containers cannot reach it;
- its output lands in `evals/reports/` and nowhere else — never a table, never a step, never
  a model's context, never a verdict the loop reads.

Flow: `corpus.py` freezes a battery output (`docs/spikes/v1/<TAG>.json`) into
`evals/corpus/<TAG>.jsonl`; a person writes `evals/labels/<TAG>.json`; `review.py` asks a model
about the frozen sentences and writes `evals/reports/<TAG>.review.json`; `score.py` compares the
two and writes `evals/reports/<TAG>.score.json`. The labels are never shown to the judge.
