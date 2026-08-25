# V2 evidence-first weakness audit

V1 is the immutable historical release. Its former test split is the **legacy seen V1 benchmark**, not evidence of V2 generalization.

| Claim | Status | Repository evidence |
|---|---|---|
| Rules-only blocked 47/68 attacker devices (69.12%). | confirmed | `artifacts/metrics/final_test_metrics.json`, `sequential_methods.rules_only.metrics.attacker_block_coverage` |
| Coverage was 37/37 burst, 10/21 evasive, and 0/10 patient. | confirmed | Same artifact, `attacker_subtypes.*.detected` |
| Four of 570 legitimate devices were blocked, all flash-sale. | confirmed | Same artifact, `legitimate_overall.ever_blocked` and `legitimate_subgroups` |
| Flash-sale blocking was 4/120, one above the integer allowance of three. | confirmed | Same artifact, `sequential_methods.rules_only.budgets.flash_sale_block` (`passed: false`) |
| Hard-retry blocking was 3/22 (13.64%). | confirmed | Same artifact, `flash_hard_retry_block` |
| HGB row classification was strong but rules-only was the selected sequential champion. | confirmed | `static_champion_metrics` and `selected_policy_method`; `src/card_testing_sentinel/api/app.py:ArtifactRegistry.evaluate` labels HGB advisory/comparators separately |
| Rules review and block thresholds were both three. | confirmed | `artifacts/policy/frozen_policy.json`, `selected_thresholds`; this produces no review-only interval |
| V1 API accepts a complete 26-feature snapshot and maintains no event state. | confirmed | `src/card_testing_sentinel/api/app.py:EvaluationRequest` and `ArtifactRegistry.evaluate` |
| Sequential artifacts persist synthetic `card_token`, while API replay masks it. | confirmed | `artifacts/predictions/final_test_event_decisions.csv` header; `api/app.py:timeline` maps tokens to `Card N` |
| Policy search/tie-breaking tests are thin. | confirmed | Before V2, `tests/unit/test_policy_selection.py` covered only `budget_checks`; `_better_key` and `select_policies` lacked direct characterization tests |
| Final rerun refusal is based on expected output paths. | confirmed | `src/card_testing_sentinel/evaluation/final_test.py:guard_final_test` and `final_artifact_paths`; useful but bypassable by a repository owner |
| Atomic JSON writing is duplicated. | confirmed | `scripts/freeze_policy.py`, `scripts/evaluate_final_test.py`, `evaluation/eda.py`, `modeling/training.py`, and `data/validation.py` |
| Historical archive path has spaces/parentheses. | confirmed | `configs/base.yaml:data.archive_path` and `common/config.py:FrozenDatasetConfig.archive_path` |
| Application coverage is below project coverage. | confirmed | V2 baseline: `api/app.py` 77% versus 88% overall (53 tests) |
| Conda defaults is a verified licensing defect. | not_found | `environment.yml` records `defaults`; no repository evidence establishes a legal defect. V2 keeps the environment unchanged. |
| V1 local prototype is broken because it uses Uvicorn. | overstated | `scripts/run_app.py` uses a valid ASGI server; auth, durable state, rate limits, and deployment controls are deferred production concerns. |

## Weakness register and routing

| Weakness | V2 treatment |
|---|---|
| Patient attacks completely missed | Phase 1 adds multi-session/long-horizon behavior; Phase 2 uses subtype-aware policy objectives. |
| Evasive recall is weak | Phase 1 adds slow-pattern evidence; Phase 2 uses subtype-balanced validation objectives. |
| Flash-sale/hard-retry false positives | Phase 1 adds retry/continuity context; Phase 2 enforces subgroup constraints. |
| Rules dominate deployed policy | Phase 2 compares calibrated ML and simple hybrid policies fairly; ML is not assumed to win. |
| No meaningful review band | Phase 2 freezes distinct allow/review/block actions. |
| Row and sequential stories differ | Phase 2 makes device-sequential metrics primary. |
| Seen V1 test cannot validate V2 | Phase 3 uses a post-freeze user/evaluator-supplied blind challenge. |
| Synthetic token persisted | V2 stores opaque synthetic fingerprints; a real adapter requires keyed HMAC or a token vault. |
| Separate offline/online logic | One Phase 1 engine powers incremental and batch replay. |
| Snapshot-only V1 API | Phase 1 documents raw lifecycle events; Phase 4 exposes the stateful endpoints. |
| V1 acts after authorization | V2 prechecks the current request and commits its later outcome separately. |
| Thin selection tests | Phase 1 characterizes V1; Phase 2 directly tests V2 search/ties. |
| Path-local run-once guard | Phase 1 specifies an honest content-addressed ledger; Phase 3 implements it. |
| Small subgroup counts | Development support increases; later reporting includes counts and Wilson intervals. |
| No calibration evidence | Phase 2 adds validation-only reliability reporting. |
| Potentially preventable is not causal savings | Retain only as a labeled offline upper bound, never currency savings. |
| Duplicate utilities/historical paths | V2 adds shared atomic I/O and clean versioned paths without refactoring V1. |
| Missing production controls | Phase 4 backlog: durable state, auth, isolation, rate limits, secrets, monitoring, rollout. |
