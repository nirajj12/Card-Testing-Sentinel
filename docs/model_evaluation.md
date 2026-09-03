# Model and policy evaluation

Development training uses deterministic device-grouped folds. Each device has
total evaluation weight one; training additionally balances legitimate and
attack device classes. Thirteen regularized-linear, interaction and Histogram
Gradient Boosting candidates were compared using actor-safe grouped
cross-validation. The active frozen artifact is Model v3.1 candidate
`hist_gb_2`, a Histogram Gradient Boosting classifier with sigmoid calibration
bound to the ordered 44-feature `merchant-visible-causal-3.1` contract.

Policy v2 was selected under Model v2 before the historical Blind v2 evaluation
and intentionally retained unchanged when Model v3.1 became active. The active
binding is declared by `configs/runtime_v3_1.yaml`. The older logistic model and
isotonic calibration remain preserved as historical Model v2 evidence; they are
not the current scorer.

Sequential evaluation replays raw request/outcome/checkout events. The current
request is scored before its outcome. A block suppresses only the linked outcome
and checkout; later requests continue through the scorer. Device-level review
and block coverage are primary policy measurements.

## Historical frozen Blind v2 evidence

The earlier Model v2 evidence includes 3,200 legitimate and 800 attacker
devices. Its frozen verdict is `WEAK`: attack REVIEW+ was 70.50%, attack BLOCK
was 34.125%, legitimate REVIEW+ was 14.9062%, and legitimate BLOCK was 5.0937%.
It is retained as negative historical evidence rather than presented as the
active evaluation.

## Current shifted stress evidence

The active Model v3.1/Policy v2 stack was evaluated once on frozen PBRSS-v1.
That evaluation is consumed, was not followed by tuning, and has a `MIXED`
conclusion: strong attack intervention coverage with excessive legitimate
review friction. It is synthetic stress evidence, not production performance.

The application reads committed aggregate evaluation artifacts. It never
regenerates or rescores frozen Blind v2 or PBRSS-v1 evidence at runtime.
