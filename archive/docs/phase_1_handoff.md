# Card-Testing Sentinel — Phase 1 Handoff Document
**Author**: Antigravity (ML & Evaluation Architect)  
**Target Recipient**: Codex (Implementation Engineer for Phase 2)  
**Date**: September 2, 2026  
**Status**: Phase 1 Audit & Design Complete; Ready for Phase 2 Implementation  

---

## 1. Current Frozen System Inventory

The active system is locked under `frozen-v2-runtime`. Every component, path, version, and cryptographic hash below was verified directly against repository code and passes `python scripts/verify_release.py`:

| Component | Path in Repository | Version / Spec | SHA-256 Digest |
|---|---|---|---|
| **Runtime Config** | `configs/runtime.yaml` | `frozen-v2-runtime` | Committed configuration |
| **Feature Contract** | `artifacts/model_v2/feature_contract.json` | `merchant-visible-causal-2` (39 features) | `51bfa6604ed0486447ee16a43270f2092f0cac96b3ab0c2f0bad2748e8c28a38` |
| **Feature Spec** | `src/card_testing_sentinel/features/specification_v2.py` | `merchant-visible-causal-2` | Matches contract |
| **Feature Engine** | `src/card_testing_sentinel/features/engine_v2.py` | `FeatureEngineV2` | `6aa29b5953bb4f6d875bd51848e81dbeece6d0a1939816cd8bc031b59b6901c0` |
| **Model Artifact** | `artifacts/model_v2/risk_model_v2.joblib` | `model-v2` (LogisticRegression C=10.0, Sigmoid) | `0317cef5d310bc5d5d2ed55e755d995a34c54ad28df5ea780a36cb1e6fea2e3c` |
| **Model Metadata** | `artifacts/model_v2/metadata.json` | `model-v2` metadata | Verified |
| **Policy Config** | `configs/policy_v2.yaml` | `validation-selected-v2` (`evidence_gated_v2`) | `92b0173e0ba073a9a20b7f09e5d0d82c9d40a52598cb9140ede36714a03c0052` |
| **Policy Artifact** | `artifacts/policy_v2/operational_policy_v2.json` | `validation-selected-v2` | `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c` |
| **Evaluation Record**| `artifacts/evaluation/blind_v2_consumption.json` | `blind-v2` (Consumed) | `96b6265657c9c2273d2b25938a0377a47a36a2f0487174c01f514b439aae8903` |
| **Evaluation Metrics**| `artifacts/evaluation/blind_v2_metrics.json` | `blind-v2` final metrics | `8624f6f3f1755b26bfc7e732857ced4b8d8ee33e9cf217d79ad6fba63f4331b1` |
| **Runtime Database** | `data/runtime/live_state_v2.sqlite3` | SQLite WAL state store | Local runtime state |

---

## 2. Blind v2 Diagnosis Summary

The frozen Blind v2 evaluation yielded a verdict of **WEAK synthetic generalization**:
- **What Worked**:
  - Concentrated attack velocity and single-device card cycling (`variable_cadence_v2`: 100% Review+, 89.7% Block; `burst_pause_burst_v2`: 95.8% Review+, 91.7% Block; `fast_burst_v2`: 96.6% Review+, 72.4% Block).
  - Camouflage resistance (`merchant_normal_amount_attack`: 96.7% Review+; `success_camouflage_v2`: 100% Review+).
  - Pure guest checkout without decline history was completely unpenalized (`new_guest_checkout`: 0.0% Review+, 0.0% Block across 411 devices).
- **What Failed**:
  - **Weak Cross-Device Guest Attacks**: `cross_device_weak_guest` achieved only **20.79%** Review+ and **0.99%** Block (80 of 101 devices completely missed). The engine relied on `customer_id` for linkage; without it, each guest device appeared completely clean.
  - **Catastrophic Legitimate False Friction**:
    - `subscription_dunning_v2`: **99.22%** Review+, **72.66%** Block (93/128 subscribers blocked!).
    - `persistent_card_problem_v2`: **86.00%** Review+, **34.00%** Block.
    - `network_retry_storm_v2`: **75.86%** Review+, **21.55%** Block.
  - **Calibration Collapse**: ECE worsened by 6.5x from 0.0181 to 0.1171; Brier score doubled from 0.0743 to 0.1521.
- **Leading Hypotheses (To Be Tested via Ablation in Phase 2)**:
  - *Model Additivity Hypothesis*: The linear model sums positive weights across multiple correlated failure counts (`failures_7d`, `decline_streak`, `customer_failures_7d`). Lacking non-linear interaction terms, it treats repeated declines on the same card similarly to cycling multiple stolen cards.
  - *Policy Evidence Gate Hypothesis*: Policy v2's evidence gate accepted raw decline counts as sufficient proof of card testing without requiring card-diversity evidence (`distinct_card_last4_7d >= 2`).
  - *Trust Discounting Hypothesis*: Absence of trust suppression in Policy v2 prevented established subscribers with months of clean billing from discounting transient decline streaks.
  These are treated as testable hypotheses, not proven root causes, and will be isolated via ablation in Phase 2.

---

## 3. Dataset v4 Plan Summary

Dataset v4 is engineered around **device/entity coverage** and deliberate distribution shifts:
- **Scope**: ~50,000 requests, ~12,000 devices, 20 merchants across 6 archetypes.
- **Device-Centric Minimums**: Explicit allocation of **250–300 devices minimum** per high-priority attack (`cross_device_weak_guest`, `cross_device_partial`, `distributed_bot_campaign`) and hard-negative family (`subscription_dunning_hard`, `network_retry_storm_hard`, `persistent_card_problem_hard`, `shared_household_device`, `cgnat_mobile_ip_storm`).
- **Blind-v2 Covariate Shifts**: Directly crosses orthogonal behavioral axes:
  - Old customer / new device vs new customer / old device.
  - Short vs long sessions; regular vs irregular retry cadence.
  - Long-established customer temporarily behaving unusually vs clean new guest.
  - Shifted amount distributions across archetypes and micro-purchases.
- **Identity Balance**: Decouples `customer_id_present` from risk (balanced across both classes; $|\rho| < 0.08$).

---

## 4. Scenario Matrix & Merchant Archetypes Summary

Detailed in `docs/dataset_v4_scenario_matrix.md`:
- **6 Merchant Archetypes**: Standard E-commerce, Guest-Heavy D2C, Subscription/SaaS, Micro-Payment & Digital, Flash-Sale, High-Ticket Travel/Tech.
- **Hard Legitimate Scenarios**: `subscription_dunning_hard`, `network_retry_storm_hard`, `cvv_and_expiry_mistakes`, `genuine_wallet_cycling`, `shared_household_device`, `cgnat_mobile_ip_storm`, `session_recreation_flaky_net`, `dormant_account_spike`.
- **Target Attack Scenarios**: `cross_device_weak_guest`, `cross_device_partial`, `distributed_bot_campaign`, `patient_tester_v4`, `burst_pause_burst_v4`, `success_camouflage_v4`.

---

## 5. Paired Counterfactual Benchmark Summary

Detailed in `docs/dataset_v4_scenario_matrix.md`:
- 20 pre-declared identical-surface pairs (Attack Twin vs Legitimate Twin).
- Measures **Counterfactual Pair Ordering Accuracy (CPOA)**:
  $$\text{CPOA} = \frac{1}{20} \sum_{k=1}^{20} \mathbb{I}(S(\text{Attack}_k) > S(\text{Legit}_k))$$
- Target objective: $\ge 90.0\%$ (Stretch: $\ge 95.0\%$).
- Directly tests causal understanding: models must score the multi-card cycling attack higher than the single-card dunning twin with identical attempt velocity.

---

## 6. Dataset Audit & Leakage Checks Summary

Detailed in `docs/dataset_v4_audit_spec.md`:
- **Diagnostic Guardrails vs Hard Failure**: Fixed single-feature PR-AUC thresholds (Metadata $\ge 0.35$, Velocity $\ge 0.65$, Behavioral Domain $\ge 0.80$) serve as diagnostic review guardrails. Hard failure is strictly reserved for unambiguous causal leakage (scenario ID, attack label, future payment outcome, post-auth data, generator metadata).
- **Mandatory Audit Metrics Reported**:
  1. Single-feature PR-AUC
  2. Lift over prevalence
  3. Train / stress stability
  4. Scenario dependence
  5. Legitimate-family dependence
  6. Manual diagnostic verdict
- Absolute verification of the Decision-Time Availability table (no future gateway results or decline codes).

---

## 7. Stress-Suite Design Summary

Detailed in `docs/post_blind_stress_v1_spec.md`:
- **Post-Blind Remediation Stress Suite v1 (PBRSS-v1)** replaces any concept of "Blind v3".
- Incorporates deliberate distribution shifts: 2 completely unseen merchant archetypes (B2B Wholesale, Charity/Donation), bursty Pareto delays, asymmetric 48-hour pauses.
- Governed by the **One-Score Evaluation Policy**: frozen before scoring, evaluated exactly once, no post-stress tuning permitted.

---

## 8. External Dataset Decision Summary

Detailed in `docs/external_card_testing_dataset_assessment.md`:
1. **Mendeley Data Synthetic Banking (2025)**: The current schemas and decision boundaries do not support a defensible direct Model-v3 benchmark without additional compatibility analysis. Therefore its initial role is Category C: scenario/distribution reference.
2. **IEEE-CIS Fraud Detection**: Class **D (Research Reference Only)**. Generic CNP post-settlement chargebacks differ fundamentally from pre-checkout card testing; anonymized features cannot map to Sentinel's causal contract.

---

## 9. Proposed Phase 2 Features (Ranked by Expected Value)

| Rank | Proposed Feature Name | Category | Expected Value | Implementation Risk | Justification |
|---|---|---|---|---|---|
| **1** | `card_diversity_ratio_7d` | Card History | **Critical** | Low | $\frac{\text{distinct\_cards}}{\max(1, \text{requests})}$. Immediately differentiates single-card dunning ($0.16$) from card testing ($0.83$). |
| **2** | `card_change_after_decline_ratio_7d`| Card History | **Critical** | Low | Directly identifies fraudster discarding declined card vs legitimate customer retrying. |
| **3** | `session_churn_rate_24h` | Session / Bot | **High** | Low | Flags headless guest bots cycling session cookies (`cross_device_weak_guest`). |
| **4** | `merchant_relative_velocity_zscore` | Merchant Relative | **High** | Medium | Normalizes attempt bursts against merchant baseline, protecting flash-sale shoppers. |
| **5** | `median_inter_attempt_gap_seconds_24h`| Temporal Shape| **High** | Low | Distinguishes automated loop ($< 2\text{s}$) from human dwell time ($> 30\text{s}$). |
| **6** | `merchant_amount_log_ratio` | Merchant Relative | **Medium** | Low | Stabilizes amount distributions across disparate merchant ticket sizes. |
| **7** | `subnet_device_fanout_5m` | Network / IP | **Medium** | Medium | Captures proxy farm bursts across shared `/24` subnets. |
| **8** | `gap_coefficient_of_variation_24h` | Temporal Shape | **Medium** | Low | Identifies bimodal burst-pause attack structures. |

---

## 10. Proposed Model v3 Acceptance Criteria & Experiment Matrix

### 10.1 Primary Acceptance Gates vs Stretch Targets
- **Primary Acceptance Gates (Pre-Blind Policy v2 Standards)**:
  - Attack REVIEW+ Recall: $\ge 70.0\%$
  - Legitimate REVIEW+ Rate: $\le 6.0\%$
  - Legitimate BLOCK Rate: $\le 1.0\%$
- **Development Stretch Targets**:
  - Attack REVIEW+ Recall: $\ge 80.0\%$
  - Legitimate REVIEW+ Rate: $\le 4.0\%$
  - Legitimate BLOCK Rate: $\le 0.5\%$
- **Development & Diagnostic Objectives** (Not hard gates):
  - PR-AUC $\ge 0.70$, ROC-AUC $\ge 0.85$, Brier $\le 0.080$, ECE $\le 0.030$, CPOA $\ge 90.0\%$.

### 10.2 Experiment Matrix & Controlled Policy Ablation
1. **EXP-00**: Frozen Model v2 + Policy v2 on Dataset v4 (Reference baseline).
2. **EXP-01**: Model v2 re-trained on Dataset v4 + Policy v2 (Measures data effect alone).
3. **EXP-02**: Logistic Regression + Domain Interaction Terms on FeatureEngineV3 + Policy v2.
4. **EXP-03**: HistGradientBoosting on FeatureEngineV3 + Policy v2.
5. **EXP-04**: Model Selection Gate (compare EXP-02 vs EXP-03 on CPOA, ECE, and friction under unchanged Policy v2).
6. **EXP-05A (Policy Ablation)**: Model v3 + Policy v2 with `trust_suppression: moderate` (Tests whether customer history reduces dunning friction without degrading attack recall; treated strictly as an experiment, not automatically enabled).
7. **EXP-05B (Remediated Policy)**: Model v3 + Policy v3 (Card-diversity evidence gate).

---

## 11. Files Codex Should Implement in Phase 2

Codex should create and modify the following specific files in Phase 2:

```bash
# Dataset v4 Generator & Configuration
configs/dataset_v4.yaml
src/card_testing_sentinel/services/generator_v4.py
pipelines/generate_dataset_v4.py
pipelines/validate_dataset_v4.py
scripts/audit_dataset_v4.py

# Feature Engine v3 & Specification
configs/features_v3.yaml
src/card_testing_sentinel/features/specification_v3.py
src/card_testing_sentinel/features/engine_v3.py
src/card_testing_sentinel/features/state_v3.py
pipelines/build_features_v3.py

# Model v3 Training & Selection Pipelines
configs/training_v3.yaml
pipelines/train_model_v3.py
pipelines/evaluate_model_v3.py

# Policy v3 Configuration & Selection
configs/policy_v3.yaml
pipelines/select_policy_v3.py

# Post-Blind Remediation Stress Suite v1
configs/post_blind_stress_v1.yaml
pipelines/generate_post_blind_stress_v1.py
pipelines/evaluate_pbrss_v1_once.py
scripts/freeze_pbrss_v1.py

# Unit & Integration Tests
tests/unit/test_dataset_v4.py
tests/unit/test_feature_engine_v3.py
tests/integration/test_model_v3.py
tests/integration/test_counterfactual_pairs.py
```

---

## 12. Frozen Files Codex MUST NOT Touch

The following files are historical evidence and runtime foundations. **Under no circumstances should Codex modify, overwrite, or delete them:**

1. `configs/runtime.yaml` (until Phase 3 migration)
2. `artifacts/model_v2/*` (`risk_model_v2.joblib`, `metadata.json`, `feature_contract.json`)
3. `artifacts/policy_v2/*` (`operational_policy_v2.json`, `operational_policy_v2.sha256`)
4. `artifacts/evaluation/blind_v2_*` (`blind_v2_metrics.json`, `blind_v2_consumption.json`, etc.)
5. `src/card_testing_sentinel/features/engine_v2.py`
6. `src/card_testing_sentinel/features/specification_v2.py`
7. `configs/dataset_v3.yaml`, `configs/training_v2.yaml`, `configs/policy_v2.yaml`, `configs/blind_v2.yaml`
8. `reports/phase_11_*`, `reports/phase_12_*`, `reports/phase_13_*`
9. `scripts/verify_release.py`

---

## 13. Top Remaining Technical Risks

1. **Synthetic Overfitting to Counterfactual Pairs**: Models might learn subtle mathematical artifacts of how twins are paired rather than general causal relationships. Guarded by the univariate shortcut audit.
2. **HistGradientBoosting Latency Overhead**: While fast, tree traversal must stay strictly within the $\le 8\text{ ms}$ p95 SLA in Python runtime.
3. **Cold-Start Guest False Positives**: Ensuring that new features like `session_churn_rate_24h` do not penalize users with private/incognito browsing or aggressive cookie clearers.
4. **Evidence Gate Coupling**: Ensuring Policy v3 does not create a deadlock where an attack cannot be blocked because card hashes arrive only on outcomes. (Resolved by allowing extreme velocity or session churn to substitute for card diversity if confidence is overwhelming).

---

## 14. Recommended Order of Operations for Codex (Phase 2)

```text
Step 1: Implement configs/dataset_v4.yaml and src/card_testing_sentinel/services/generator_v4.py
Step 2: Generate Dataset v4 and run scripts/audit_dataset_v4.py (evaluate diagnostic guardrails, ensure no hard leakage)
Step 3: Implement FeatureEngineV3 and verify causality tests in tests/unit/test_feature_engine_v3.py
Step 4: Execute pipelines/train_model_v3.py comparing Logistic+Interactions vs HistGradientBoosting
Step 5: Score Counterfactual Pairs (verify CPOA >= 90.0% developmental objective)
Step 6: Run controlled Policy evaluation (EXP-05A: Policy v2 with moderate trust suppression ablation; EXP-05B: Policy v3 with card-diversity evidence gate)
Step 7: Freeze and score Post-Blind Remediation Stress Suite v1 (PBRSS-v1) ONCE
Step 8: Generate comprehensive walkthrough and verification reports
```
