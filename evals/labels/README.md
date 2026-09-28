# labels

One file per frozen round, `<TAG>.json`: a list of `{"tag", "turn", "sentence", "verdict",
"reason"}` where `verdict` is one of `true`, `false`, `unsupported`, `not_a_claim`, and `reason`
is a sentence in the labeller's words. The judge (`review.py`) never reads this file; only
`score.py` does.
