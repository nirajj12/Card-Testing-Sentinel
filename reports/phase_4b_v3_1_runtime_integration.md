# Phase 4B — Frozen Model v3.1 Runtime Integration

## 1. Scope

Phase 4B integrates the already-frozen Model v3.1 stack into the application runtime. It changes serving selection, integrity validation, runtime state lineage, read-only evidence display, and verification coverage only. It does not change the model, feature formulas, feature order, calibration, policy, or PBRSS evidence.

## 2. Starting commit

The authoritative starting commit and current HEAD are both `5d7fa914fd4ac13c3717dc4c936ba0d0b49ffb80`. Phase 4B remains an uncommitted working-tree change.

## 3. Active runtime identity

- Runtime: `postblind-v3.1-prototype-runtime`
- Runtime stage: `evaluated_prototype_candidate`
- Model: `model-v3.1`
- Model family: `hist_gradient_boosting`
- Candidate: `hist_gb_2`
- Calibration: `sigmoid`
- Feature contract: `merchant-visible-causal-3.1`
- Features: 44
- Policy: `validation-selected-v2` / `evidence_gated_v2`
- Evaluation: `pbrss-v1`, consumed
- Evaluation conclusion: `MIXED`
- Synthetic evaluation: `true`
- Production ready: `false`

## 4. Frozen Model v3.1 identity

The runtime is bound to `artifacts/model_v3_1/risk_model_v3_1.joblib` with SHA-256 `093254b63674f50b62caf5eddeaeba47d79f9327902e2567ffed75418a59b1e4`. The registry also validates the frozen model metadata, selected family, candidate parameters, calibration method, fitted feature order, artifact interface, and metadata SHA-256.

## 5. Feature contract identity

The active contract is the exact ordered 44-feature `merchant-visible-causal-3.1` contract. Its semantic hash is `af66f693eee5043f0e97dfef1c31b1773ae480e38228f47612575d336abe2ce0`; the contract artifact SHA-256 is `522aa6327617bfed687bd2f0955405b5f63f6595fb0c86da9077b4442af554a8`. Source specification, contract artifact, metadata, loaded artifact, offline replay, and online engine order are checked against the same tuple.

## 6. Historical v2 preservation

`configs/runtime.yaml`, `scripts/verify_release.py`, the v2 model/evaluation evidence, and historical runtime semantics are unchanged. Explicit selection of `configs/runtime.yaml` still binds `FeatureEngineV2`, Model v2, 39 ordered features, Policy v2, and Blind-v2 evidence.

## 7. Registry refactor

`ArtifactRegistry` now dispatches only two known manifest identities: historical `frozen-v2-runtime` and active `postblind-v3.1-prototype-runtime`. Unknown identities fail closed. The v3.1 path validates exact frozen hashes for the model, metadata, feature config, feature-contract artifact, Policy-v2 artifact, PBRSS freeze manifest, PBRSS result manifest, and every file named by the result manifest. It also validates consumption identity and `post_stress_tuning: false`. Model v3.1 cannot enter degraded-rules mode; a missing or unusable artifact fails startup.

## 8. RiskService runtime selection

`RiskService` receives the validated engine class and ordered model-feature tuple from the registry. Initial startup and `rebuild_from_persistence()` instantiate the same selected engine. The commit-time causal snapshot consistency check iterates the selected contract rather than a hard-coded v2 list. Policy execution remains `RiskPolicyV2` using the unchanged Policy-v2 configuration.

## 9. v3.1 SQLite isolation

The active app uses `data/runtime/live_state_v3_1.sqlite3`. Historical `data/runtime/live_state_v2.sqlite3` is not reused or migrated, preventing v2 decisions and feature-state lineage from being replayed as v3.1 state.

## 10. Offline/runtime feature parity

A deterministic non-PBRSS lifecycle fixture is replayed through `replay_events_v3` and directly through `FeatureEngineV3`. Both paths produce the same 44 columns in the same frozen order and exactly equal feature values.

## 11. Model score parity

The frozen artifact natively exposes `score_frame`. The runtime wrapper only converts the already-ordered online vector into a one-row DataFrame with the frozen 44 column names, then returns the artifact result unchanged. A deterministic non-PBRSS test captures the exact frame passed by the wrapper, proves it equals the native input with exact value/order comparison, and proves the native and wrapper scores are equal with zero relative and absolute tolerance. There is no fitting, normalization, second calibration, rounding, or output transformation.

## 12. Policy v2 integrity

Policy remains `validation-selected-v2` / `evidence_gated_v2`. The policy config and artifact have no diff from the starting commit, the frozen artifact hash remains `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c`, registry consistency checks pass, and the historical verifier independently verifies the policy lineage.

## 13. Razorpay ALLOW/REVIEW/BLOCK behavior

- `ALLOW`: creates exactly one server-side test order; an identical retry returns the stored order and does not call order creation again.
- `REVIEW`: order creation returns `payment_order_not_allowed`; the Razorpay client is not called.
- `BLOCK`: order creation returns `payment_order_not_allowed`; the Razorpay client is not called. Deterministic traffic coverage also verifies suppressed authorization creates no outcome or checkout.

No live Razorpay Test Mode transaction was performed.

## 14. Idempotency

Exact precheck retries return the persisted response with `idempotent_replay: true` and do not rescore or duplicate timeline state. Conflicting retries return HTTP 409. Razorpay order retry creates no second order. Outcome and webhook deduplication tests pass.

## 15. Persistence restart/rebuild

The v3.1 SQLite test persists an allowed request, verified approval, and checkout, closes the service, reconstructs state through a new `RiskService`, verifies idempotent response replay, confirms `FeatureEngineV3`, and successfully scores a later request with the reproduced state version.

## 16. Causal lifecycle verification

Causality tests confirm the current request cannot observe its own outcome, card metadata, or checkout; those facts affect only later requests. Device ordering, independent-device interleaving, duplicate outcomes, blocked-request transition rejection, and future scoring after an intervention all pass under the selected runtime contract.

## 17. `/api/system` result

The endpoint reports the active v3.1 runtime, Model v3.1, `hist_gradient_boosting`, `hist_gb_2`, sigmoid calibration, the 44-feature v3.1 contract, Policy v2, consumed PBRSS-v1 evidence, conclusion `MIXED`, runtime stage `evaluated_prototype_candidate`, `synthetic_demonstration: true`, and `production_ready: false`.

## 18. Historical v2 verifier

`.venv/bin/python scripts/verify_release.py` passes with `verified`, `frozen-v2-runtime`, Model v2, 39 features, Policy v2, Blind-v2 verdict `WEAK`, and `post_blind_tuning: false`.

## 19. New v3.1 verifier

`.venv/bin/python scripts/verify_runtime_v3_1.py` passes with `verified`, the active v3.1 runtime, Model v3.1, 44 features, Policy v2, PBRSS-v1 conclusion `MIXED`, stage `evaluated_prototype_candidate`, `production_ready: false`, `pbrss_rescored: false`, and historical-v2 verification included.

## 20. Tests

The targeted Phase 4B command passed **95 tests** with no failures. The required full command `.venv/bin/pytest -q` passed **248 tests**, failed 0, skipped 0, and deselected 262 tests marked `slow` by the repository's configured `-m 'not slow'` default. Generated coverage was **89%**. One non-blocking joblib warning reported that physical-core discovery was unavailable and logical cores would be used; no test behavior or result was affected.

## 21. Limitations and explicit governance statements

PBRSS RESULT REMAINS MIXED.

RUNTIME INTEGRATION DOES NOT IMPROVE THE FROZEN EVALUATION RESULT. It does not change evaluation performance: PR-AUC remains `0.6469762178054731`, ROC-AUC `0.7261889167036668`, Brier `0.15603701503584233`, ECE `0.14067900697104643`, attack REVIEW+ `96.40%`, attack BLOCK `59.12%`, legitimate REVIEW+ `20.72%`, and legitimate BLOCK `0.16%`.

MODEL v3.1 IS AN EVALUATED PROTOTYPE CANDIDATE, NOT PRODUCTION READY.

NO MODEL RETRAINING PERFORMED.

NO RECALIBRATION PERFORMED.

NO POLICY THRESHOLD CHANGES PERFORMED.

PBRSS NOT RESCORED.

The evaluation endpoint is display-only: it reads committed frozen JSON/CSV evidence, does not load or call the model, does not reconstruct predictions, and exposes the `MIXED` conclusion and 20.72% legitimate REVIEW+ result without reinterpretation.
