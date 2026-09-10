# V32 — the gate's unit becomes the sentence, and how to measure it

## What changed

`services/claims.py` gains **G4**, a pass whose argument is the claims of one
sentence. It runs only after every figure in the answer is already accounted for,
so the model fixes one thing at a time. Two rules, both over the facts:

| refusal | fires when | why it exists |
|---|---|---|
| `ordering_not_computed` | a sentence states **two or more readings of one measure** and an ordering word, and no claim in it is a `rank` | C3 accepted 23 answers (upper bound) whose prose ordered figures with nothing that computed the ordering — *"the worst name is NVDA at 1.92× (#1), then AMZN at 1.43× (#2)"* |
| `same_figure_twice` | two claims in one sentence point at one measure, one period, one value, and the subjects are the same or both run/calc handles | `W05-half-taken-back` t1 was accepted saying *"concentration at 8.76%, down from 8.76%"* |

Model-facing (for the wording review): one clause in `respond`'s description and
one sentence in `meta_agent._SYSTEM`, both saying the sentence is read.

`ORDERING_WORDS` now has one home: `scripts/battery_counters.py` imports it, so
the word the gate refuses on and the word the desk counts as a superlative cannot
drift apart.

## Before spending anything: the estimate

    python scripts/v32_estimate.py docs/spikes/v30/V26_C3.json docs/spikes/v30/V26_R2.json

Reads the accepted answers of rounds already on disk and reports what G4 would
have caught. On C3: **23 of 134 accepted answers (17%), an upper bound** — the
claims are not in the traces, so a `rank` claim already present cannot be seen,
and the desk's own counter says 15 of 52 superlative turns wrote a rank/top node.

Precision was chosen over recall deliberately. An earlier form fired on one
figure that was an entry of a vector, and the same estimate put that at **30% of
accepted answers**, several of them *"the closest thing I actually have is…"* —
which orders nothing. The narrow rule misses an ordering over figures the model
computed and did not cite; that stays exactly as unchecked as it is today.

## The round

Everything below needs the fixture database and a provider key; neither exists in
the container this branch was written in, so **no live number here is claimed**.

```bash
# 0. the face and the fixture, as V30 Phase 0 set them up
scripts/battery_fixture.sh restore exposure_gold
scripts/battery_fixture.sh serve  exposure_gold 8106

# 1. does the provider still accept the face? one call, 16 output tokens.
#    V28-R shipped a schema jsonschema accepted and the provider rejected, and
#    the battery then ran 140 turns at zero calls.
python -m pytest tests/test_v28_roles.py::test_the_provider_accepts_every_face_as_written -m live -q

# 2. the round. gpt-5.4-mini, the fixture, `start` off the face so a turn
#    cannot change the book it measures.
BATTERY_DB=exposure_gold BATTERY_MCP_PORT=8106 OPENAI_MODEL=gpt-5.4-mini \
  python scripts/conversation_battery.py --fixture --deny start \
    tests/battery/conversations_v26.json docs/spikes/v32/V26_D1.json

# 3. the counters, beside C3
python scripts/battery_counters.py docs/spikes/v32/V26_D1.json
python scripts/battery_counters.py docs/spikes/v30/V26_C3.json
```

## What the round has to show, for this to have worked

Read against `V26_C3_counters.json`:

| | C3 | what V32 must do |
|---|---|---|
| `superlative_without_rank` | 37 of 52 | **falls** — this is the number the change exists for. NOTE: on C3 this counter is an upper bound with 32 of 37 unverifiable, because it reads a 300-char `args` field and 90% of C3's programs are truncated (§11). Fix the trace cap or record node kinds per step, or D1's figure is as unreadable as C3's |
| answers with a self-contradicting sentence | 1 | 0 |
| `respond` refusals | 243 | rises by at most the estimate; a large rise means the model cannot find the path the refusal names |
| `gate_exhausted` | 6 | must not rise. If it does, G4 is refusing answers the model cannot fix, and the rule is wrong |
| `figures_present` | 8/109 | unchanged either way — G4 is about what a sentence asserts, not which figures were fetched |

**Two replicates, not one.** V30 §3's own finding: the baseline's replicate spread
is as wide as several of the deltas, and at the turn level nothing smaller than
about 7 points is detectable. One round cannot settle this.

**Fix the counter first if the superlative number is to mean anything.** It reads
`'"fn": "rank"' in step.args`, and `args` is stored to 300 characters. `run`
already returns `nodes: {name: {kind}}`; recording that per step, or raising the
cap, makes the one number this change targets readable again.
