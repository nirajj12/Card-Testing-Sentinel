# V2 Phase 1 gate audit

This audit authorizes no Phase 2 work. No V2 candidate, calibration, policy,
prediction, or blind-test artifact was created.

## Evaluation boundary and shared IPs

The raw development stream deliberately contains 989 IP fingerprints shared
across train and validation devices. The original Phase 1 feature build used a
single global engine and therefore allowed bidirectional cross-split IP state.
The gate audit fixed this before Phase 2.

Development uses **isolated group evaluation**. `replay_partitioned_events`
creates a fresh engine per split and processes all events inside that split
globally by `(timestamp, event_sequence)`. Shared-network behavior remains real
inside each partition, but train state cannot enter validation features and
validation state cannot enter train features. `ip_fingerprint` remains raw
event linkage metadata and is absent from the model allowlist.

IP device/session history is committed only by processor outcomes. Prospective
IP request history is registered at precheck. The current request is included
once. The manual concurrency test demonstrates the globally shared result and
the partition-isolated result with two interleaved devices, one IP and a
timestamp tie.

## Training-only diagnostics

The sanity model now uses five-fold device-grouped out-of-fold predictions over
8,000 training devices only. Every fold has zero fit/holdout device overlap.
Device-weighted results are PR-AUC 0.9099, ROC-AUC 0.9506 and F1 0.8783 at the
training-only OOF threshold 0.4532. These are dataset diagnostics, not model
performance or selection evidence.

Labels are shuffled once per device, then mapped consistently to all its rows
and evaluated with the same folds. Shuffled ROC-AUC is 0.4816.

The shortcut search evaluates all 39 features, every unique threshold, both
`>=` and `<=` directions, using device weights and training rows only. The
strongest is `prior_attempts_7d >= 3`, weighted F1 0.7241 and average precision
0.7399, below the frozen 0.85 shortcut guardrail.

## Window and V1 characterization gates

All configured windows—10 seconds, 60 seconds, 5 minutes, 1 hour, 24 hours and
7 days—have explicit before/exactly-on/after lower-boundary tests. Processed
history uses `[request_time - window, request_time)`: closed lower bound, open
upper bound. Timestamp ties use `event_sequence`.

The complete frozen V1 `select_policies` search is rerun read-only in a
characterization test. It confirms 15 rules candidates with 9 feasible, 15/15
ML-only, 150/150 combined, the frozen method thresholds, budget rejection,
`_better_key`, deterministic tie behavior, and rules-only champion. No V1
output is rewritten.

## Scenario overlap

`reports/v2/data_quality/training_scenario_overlap.csv` reports 13 behavior
families for all seven training scenarios with raw device denominators. The
validator rejects any scenario/feature range disjoint from every other
scenario. Patient session count and burst velocity shortcuts found during the
audit were corrected; the final disjoint-range list is empty.
