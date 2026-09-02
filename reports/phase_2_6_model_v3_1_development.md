# Phase 2.6 Model v3.1 Development & Validation Report

**Status:** COMPLETE — FROZEN FOR PRE-PBRSS EVALUATION
**Model Version:** `model-v3.1`
**Accepted Candidate:** `hist_gb_2` (HistGradientBoosting)
**Calibration:** Sigmoid (Platt)
**Dataset:** `development-v4.1`
**Feature Contract:** `merchant-visible-causal-3.1` (44 features)
**PBRSS Status:** UNCONSUMED / NOT SCORED

---

## 1. Scope and Lineage

This report documents the finalized development, actor-safe cross-validation, calibration, and synthetic development validation for Model v3.1.

### Frozen Lineage
- **Active Runtime:** `frozen-v2-runtime` (strictly untouched; serves Model v2 with 39 features).
- **Historical Evaluations:** Blind v1.1 and Blind v2 remain immutable historical evidence. The authoritative frozen Blind v2 evaluation recorded an overall verdict of `WEAK` synthetic generalization, with attack REVIEW+ of 70.50%, attack BLOCK of 34.13%, legitimate REVIEW+ of 14.91%, legitimate BLOCK of 5.09%, and weak guest family recall of 20.79% REVIEW+ (21/101) and 0.99% BLOCK (1/101).
- **Release Verifier:** `python scripts/verify_release.py` passes continuously with `post_blind_tuning: false`.

---

## 2. Rejection of Original Model v3

The original Model v3 development evidence was audited in Phase 2.5 and permanently **REJECTED** due to critical methodological flaws:
1. **Invalid Grouped Cross-Validation:** The split grouped on customer-then-device rather than the full correlated synthetic actor or campaign. Of 803 multi-device training actors, 382 crossed CV folds, causing cross-device leakage during candidate evaluation.
2. **Invalid Pseudo-Features:** `merchant_relative_velocity_zscore` was merely `max(0, (requests_5m - 1) / 2)` without any merchant-level baseline, and `merchant_amount_log_ratio` was merely `log(current_amount / 1000)` without merchant grounding.
3. **Flawed Counterfactuals & Generator Bugs:** Counterfactual pairs lacked behavioral parity, household customers were unused, network instability was ignored, and multi-device spread actors allocated idle devices.
4. **Non-Deterministic Manifest:** Embedded wall-clock execution timestamps prevented byte-identical reproducibility.

All original Model v3 headline numbers were discarded. Model v3.1 re-executed the methodology from corrected, actor-safe data construction and sound causal feature definitions.

---

## 3. Dataset v4.1 & Actor-Safe Grouping Summary

Dataset v4.1 (`development-v4.1`) was generated with generator version `dataset-v4.1-generator-1`:
- **Total Lifecycle Events:** 179,283
- **Authorization Requests:** 69,274
- **Total Devices:** 12,000 (18.0% device attack prevalence)
- **Merchants:** 20 across 6 declared archetypes (subscription, micro-payment, guest-heavy, standard e-commerce, flash sale, high ticket).
- **Deterministic Manifest:** No wall-clock timestamp; byte-deterministic across re-runs.

### Actor-Safe Correlation Units (`leakage_group_id`)
To prevent fold leakage, related synthetic actors, multi-device campaigns, households, and counterfactual twins are grouped into a single `leakage_group_id`:
- **Total TRAIN Leakage Groups:** 6,751
- **Multi-Device Groups in TRAIN:** 381 (largest group: 50 devices)
- **Fold-Straddling Groups:** **0** (strict group-level stratified fold allocation)
- **TRAIN/Validation Overlap:** **0** leakage-group overlap, **0** actor overlap, **0** customer overlap.
- **Leakage Invariant:** `leakage_group_id` is evaluation/split metadata only; it is never included in the model feature matrix.

### Critical Scenario Representation
Every critical scenario family exceeded its 250-device quota:
- `cross_device_weak_guest`: 557 devices
- `cross_device_partial`: 504 devices
- `distributed_bot_campaign`: 362 devices
- `subscription_dunning_hard`: 1,218 devices
- `persistent_card_problem_hard`: 1,039 devices
- `network_retry_storm_hard`: 1,043 devices
- `shared_household_device`: 917 devices
- `cgnat_mobile_ip_storm`: 912 devices

---

## 4. Feature Contract v3.1 (`merchant-visible-causal-3.1`)

Feature Contract v3.1 specifies 44 strictly causal features (`SHA-256: af66f693eee5043f0e97dfef1c31b1773ae480e38228f47612575d336abe2ce0`):
- Dropped the two ungrounded pseudo-features from v3 (`merchant_relative_velocity_zscore`, `merchant_amount_log_ratio`).
- Retained 5 verified causal innovations: `card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`, `session_churn_rate_24h`, `gap_coefficient_of_variation_24h`, `median_inter_attempt_gap_seconds_24h`.
- Scoped IP tracking per merchant `(merchant_id, ip_fingerprint)` to prevent cross-merchant history bleed.
- Strict causal boundary: Evaluated at precheck request arrival before authorization result or card fields exist.

---

## 5. Candidate Selection & Weighting Normalization

### Weighting Normalization Correction
Model v3.1 rescales balanced device/class weights so that the total effective sample mass equals the number of devices. This stabilizes regularized optimization across linear and tree models without altering Model v2 weighting code.

### 5-Fold Actor-Safe Grouped Cross-Validation (TRAIN Out-of-Fold)
Evaluated across 13 candidate specifications:

| Candidate | Family | Parameters / Hyperparameters | OOF PR-AUC | OOF ROC-AUC | OOF Brier | OOF ECE | OOF Log-Loss |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **`hist_gb_2`** | **HistGradientBoosting** | **lr=0.08, max_leaf=31, iter=150, l2=2.0** | **0.9384** | **0.9790** | **0.0440** | **0.0554** | **0.1532** |
| `hist_gb_1` | HistGradientBoosting | lr=0.05, max_leaf=15, iter=150, l2=1.0 | 0.9380 | 0.9793 | 0.0468 | 0.0656 | 0.1611 |
| `hist_gb_3` | HistGradientBoosting | lr=0.05, max_leaf=31, iter=200, l2=5.0 | 0.9380 | 0.9790 | 0.0448 | 0.0587 | 0.1564 |
| `logistic_C5.0` | Logistic Regression | C=5.0, max_iter=2000 | 0.8724 | 0.9594 | 0.0880 | 0.1066 | 0.2583 |
| `logistic_C1.0` | Logistic Regression | C=1.0, max_iter=2000 | 0.8721 | 0.9591 | 0.0887 | 0.1089 | 0.2607 |
| `logistic_interactions_C1.0` | Logistic + Interactions | C=1.0, max_iter=2000 | 0.8719 | 0.9591 | 0.0886 | 0.1088 | 0.2604 |
| `logistic_interactions_C0.5` | Logistic + Interactions | C=0.5, max_iter=2000 | 0.8710 | 0.9586 | 0.0891 | 0.1104 | 0.2624 |
| `logistic_C0.5` | Logistic Regression | C=0.5, max_iter=2000 | 0.8707 | 0.9584 | 0.0892 | 0.1106 | 0.2629 |
| `logistic_C0.1` | Logistic Regression | C=0.1, max_iter=2000 | 0.8664 | 0.9565 | 0.0913 | 0.1173 | 0.2722 |
| `logistic_interactions_C0.1` | Logistic + Interactions | C=0.1, max_iter=2000 | 0.8657 | 0.9561 | 0.0911 | 0.1171 | 0.2717 |
| `logistic_interactions_C0.05`| Logistic + Interactions | C=0.05, max_iter=2000 | 0.8631 | 0.9549 | 0.0925 | 0.1216 | 0.2781 |
| `logistic_C0.05` | Logistic Regression | C=0.05, max_iter=2000 | 0.8629 | 0.9549 | 0.0927 | 0.1219 | 0.2787 |
| `logistic_C0.01` | Logistic Regression | C=0.01, max_iter=2000 | 0.8552 | 0.9517 | 0.0980 | 0.1411 | 0.3042 |

**Decision:** `hist_gb_2` won decisively under the pre-registered selection criterion (highest actor-safe TRAIN OOF PR-AUC: 0.9384). Although HGB candidates are clustered within 0.0004 PR-AUC, `hist_gb_2` is frozen to prevent post-hoc switching.

---

## 6. Calibration

Calibration was fitted strictly on `hist_gb_2` out-of-fold predictions:

| Method | PR-AUC | ROC-AUC | Brier Score | ECE | Log-Loss | Decision |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Uncalibrated (`none`)** | 0.9384 | 0.9790 | 0.0440 | 0.0554 | 0.1532 | Baseline raw scores |
| **Sigmoid (Platt)** | **0.9384** | **0.9790** | **0.0357** | **0.0147** | **0.1360** | **SELECTED** (Zero ranking loss; 73% reduction in ECE) |
| **Isotonic** | 0.9310 | 0.9800 | 0.0321 | 0.0000 | 0.1148 | Rejected (Incurs 0.0074 PR-AUC ranking loss) |

---

## 7. Synthetic Development Validation Performance

> [!IMPORTANT]
> These metrics represent **actor-safe synthetic development validation** on held-out Dataset v4.1 data. They are development evidence designed to expose known failure modes, NOT production performance, NOT real Razorpay merchant performance, and NOT proof of real-world generalization.

| Metric | Primary Product Gate | Stretch Target | Model v3.1 Validation Result | Gate Status |
| :--- | :---: | :---: | :---: | :---: |
| **Attack REVIEW+ Recall** | $\ge 70.0\%$ | $\ge 80.0\%$ | **93.49%** (589/630) | **SURPASSED STRETCH** |
| **Legitimate REVIEW+ Friction** | $\le 6.0\%$ | $\le 4.0\%$ | **3.14%** (90/2870) | **SURPASSED STRETCH** |
| **Legitimate BLOCK Rate** | $\le 1.0\%$ | $\le 0.5\%$ | **0.14%** (4/2870) | **SURPASSED STRETCH** |
| **Attack BLOCK Rate** | Diagnostic | Diagnostic | **67.46%** (425/630) | Strong blocking |
| **PR-AUC (Device-Weighted)** | $\ge 0.70$ (stretch) | $\ge 0.70$ | **0.9169** | **SURPASSED STRETCH** |
| **ROC-AUC (Device-Weighted)**| $\ge 0.85$ (stretch) | $\ge 0.85$ | **0.9693** | **SURPASSED STRETCH** |
| **Brier Score** | $\le 0.080$ (stretch) | $\le 0.080$ | **0.0410** | **SURPASSED STRETCH** |
| **ECE** | $\le 0.030$ (stretch) | $\le 0.030$ | **0.0214** | **SURPASSED STRETCH** |
| **Counterfactual Ordering (CPOA)** | $\ge 90.0\%$ (stretch) | $\ge 90.0\%$ | **100.0%** (20/20 pairs) | **PERFECT PAIR ORDERING** |

---

## 8. Policy v2 Evaluation (Unchanged vs. Moderate Trust)

Policy v2 operates under thresholds `review_threshold=0.75`, `block_threshold=0.90`, `block_evidence=2`, `evidence_set=v2_full`.

| Policy Experiment | Attack REVIEW+ | Attack BLOCK | Legitimate REVIEW+ | Legitimate BLOCK |
| :--- | :---: | :---: | :---: | :---: |
| **Experiment A: Unchanged Policy v2 (`trust_suppression: none`)** | **93.49%** | **67.46%** | **3.14%** | **0.14%** |
| **Experiment B: Moderate Trust (`trust_suppression: moderate`)** | **93.49%** | **67.14%** | **3.14%** | **0.14%** |

**Interpretation:** Moderate trust suppression produces no reduction in legitimate false friction (3.14% Review+, 0.14% Block in both experiments) while marginally reducing attack blocking by 0.32 pp. Therefore, **Policy v2 remains unchanged** with zero code modifications.

---

## 9. Critical Scenario Breakdown (Validation Split)

Scored under unchanged Policy v2:

| Scenario Name | Population | Devices | REVIEW+ Rate | BLOCK Rate | Mean Max Score | Operational Assessment |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `subscription_dunning_hard` | Legitimate | 347 | **0.00%** | **0.00%** | 0.0093 | Zero legitimate friction on recurring declines |
| `persistent_card_problem_hard` | Legitimate | 282 | **4.61%** | **0.00%** | 0.1481 | Well below 6% gate; zero blocks |
| `network_retry_storm_hard` | Legitimate | 287 | **2.79%** | **0.00%** | 0.1114 | Low friction during rapid single-card retries |
| `shared_household_device` | Legitimate | 267 | **0.00%** | **0.00%** | 0.0526 | Clean handling of multiple household users |
| `cgnat_mobile_ip_storm` | Legitimate | 292 | **0.68%** | **0.00%** | 0.0217 | Protected against shared carrier IP bursts |
| `cross_device_weak_guest` | Attack | 135 | **96.30%** | **61.48%** | 0.9009 | Substantial detection of unauthenticated attacks |
| `cross_device_partial` | Attack | 150 | **97.33%** | **77.33%** | 0.9134 | High recall on partial identity rotation |
| `distributed_bot_campaign` | Attack | 112 | **76.79%** | **0.00%** | 0.7106 | Flags diffuse bot activity for review |

---

## 10. Counterfactual Benchmark (CPOA)

Model v3.1 correctly ordered all 20 pre-declared Dataset-v4.1 counterfactual twin pairs:
- **Total Twin Pairs Evaluated:** 20
- **Correct Pairs (`Score(Attack) > Score(Legitimate)`):** 20
- **CPOA:** **100.0%**

*(Note: CPOA is synthetic development evidence demonstrating that controlling non-causal surface properties produces consistent directional risk separation. It is not a claim of 100% real-world detection accuracy.)*

---

## 11. Known Limitations

1. **Distributed Botnet Blocking (0.0% Block Rate):** In `distributed_bot_campaign`, where bots distribute single attempts across 50 distinct IPs and devices, REVIEW+ reaches 76.79% but BLOCK remains at 0.00%. Without a global, cross-merchant graph intelligence layer, per-device evidence gates appropriately withhold hard blocks on very low-velocity individual devices.
2. **Synthetic Data Boundaries:** All evaluations reflect synthetic distributions engineered to stress known failure modes. They cannot substitute for independent evaluation on genuine merchant traffic.

---

## 12. Artifact Provenance & SHA-256 Checksums

- `risk_model_v3_1.joblib`: Model v3.1 serialized artifact (`artifacts/model_v3_1/risk_model_v3_1.joblib`)
- `metadata.json`: Full training and evaluation metadata (`artifacts/model_v3_1/metadata.json`)
- `candidate_metrics.csv`: Cross-validation scores across 13 candidates (`artifacts/model_v3_1/candidate_metrics.csv`)
- `calibration_metrics.csv`: Calibration comparison table (`artifacts/model_v3_1/calibration_metrics.csv`)
- `development_validation_scores.csv`: 19,832 request-level validation scores (`artifacts/model_v3_1/development_validation_scores.csv`)
- `targeted_ablations.json`: 10 targeted ablation runs (`artifacts/model_v3_1/targeted_ablations.json`)
- `feature_contract.json`: 44-feature contract definition (`artifacts/model_v3_1/feature_contract.json`)
