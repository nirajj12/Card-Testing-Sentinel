# Runtime v3.1 Integration Report

## Goal

Integrate the frozen Model v3.1 stack into the live application runtime, ensuring exact feature parity, isolated persistence, and backward compatibility with historical verifiers.

## Setup

- **Active Runtime:** `postblind-v3.1-prototype-runtime`
- **Runtime Stage:** `evaluated_prototype_candidate` (`production_ready: false`)
- **Active Model:** `model-v3.1` (`hist_gradient_boosting`, candidate `hist_gb_2`, sigmoid calibration)
- **Feature Contract:** `merchant-visible-causal-3.1` (44 features)
- **Policy:** `validation-selected-v2` (`evidence_gated_v2`)
- **Database:** `data/runtime/live_state_v3_1.sqlite3` (isolated from historical v2 state)
- **Evaluation Status:** PBRSS-v1 consumed, conclusion `MIXED`

## What I Tested

- **Artifact Registry Dispatch:** Verified that `ArtifactRegistry` correctly resolves both active `postblind-v3.1-prototype-runtime` and historical `frozen-v2-runtime`, failing closed on unknown configs.
- **Offline / Online Parity:** Compared online `FeatureEngineV3` computations against offline batch replay (`replay_events_v3`) across a deterministic lifecycle fixture.
- **Model Score Parity:** Verified that the runtime wrapper passes exact 44-feature column vectors to native `score_frame`, yielding identical floating-point scores with zero tolerance.
- **State Isolation & Restart:** Confirmed that v3.1 uses an isolated SQLite database and correctly recovers state and event versions across service restarts.
- **Razorpay Order Gating:** Tested that ALLOW requests create exactly one Test Mode order, while REVIEW and BLOCK requests return `payment_order_not_allowed` without invoking order creation.
- **Idempotency & Monotonicity:** Tested deduplication of precheck requests, order creation, and out-of-order webhook events.

## Results

### 1. Cryptographic and Artifact Lineage

| Artifact | Path | SHA-256 |
| :--- | :--- | :--- |
| **Model Binary** | `artifacts/model_v3_1/risk_model_v3_1.joblib` | `093254b63674f50b62caf5eddeaeba47d79f9327902e2567ffed75418a59b1e4` |
| **Feature Contract** | `artifacts/model_v3_1/feature_contract.json` | `522aa6327617bfed687bd2f0955405b5f63f6595fb0c86da9077b4442af554a8` |
| **Policy Artifact** | `artifacts/policy_v2/operational_policy_v2.json` | `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c` |
| **Semantic Feature Hash** | `configs/features_v3_1.yaml` | `af66f693eee5043f0e97dfef1c31b1773ae480e38228f47612575d336abe2ce0` |

### 2. Runtime Behavior & Order Enforcement

| Decision | Gateway Handling | Verification Outcome |
| :--- | :--- | :--- |
| **ALLOW** | Calls Razorpay Test Mode order API | Exactly 1 order created; repeated requests return idempotent cached order. |
| **REVIEW** | Order creation suppressed | HTTP 409 `payment_order_not_allowed`; 0 orders created. |
| **BLOCK** | Order creation suppressed | HTTP 409 `payment_order_not_allowed`; 0 orders created. |

### 3. Automated Validation

- **Targeted Integration Tests:** 95 passed, 0 failed.
- **Full Python Test Suite:** 248 passed, 262 slow deselected, 0 failed, 89% line coverage.
- **Historical Release Verifier (`verify_release.py`):** Passed (status: verified, `frozen-v2-runtime`, 39 features, Blind v2 verdict `WEAK`).
- **Active Runtime Verifier (`verify_runtime_v3_1.py`):** Passed (status: verified, `postblind-v3.1-prototype-runtime`, 44 features, PBRSS conclusion `MIXED`, `historical_v2_verified: true`).

## What the Results Mean

1. **Seamless Architecture Transition:** Model v3.1 and Feature Engine v3 run cleanly within the live FastAPI backend with zero score drift from training.
2. **Strict Verification Chain:** The application will fail startup if any frozen artifact, manifest, or feature order drifts from its verified cryptographic hash.
3. **Preserved Historical Evidence:** Active v3.1 integration preserves the historical v2 runtime and release verifier without modification.

## Limitations

- **Evaluation Conclusion Remains MIXED:** Engineering integration does not improve underlying model generalization. The frozen PBRSS-v1 metrics (PR-AUC 0.6470, ROC-AUC 0.7262, Legit REVIEW+ 20.72%) remain active and unadjusted.
- **Not Production Ready:** The active runtime is an evaluated prototype candidate. `production_ready` remains `false`.

## Reproducibility

- **Runtime Configuration:** `configs/runtime_v3_1.yaml`
- **Application Config:** `configs/app.yaml`
- **Verification Commands:**
  ```bash
  python scripts/verify_release.py
  python scripts/verify_runtime_v3_1.py
  ```
