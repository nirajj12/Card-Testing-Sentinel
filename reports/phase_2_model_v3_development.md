# Phase 2 Model v3 Development & Policy Validation Report

> **SUPERSEDED / REJECTED DEVELOPMENT EVIDENCE.** Phase 2.5 found invalid
> actor grouping and invalid merchant-relative features. Preserve these
> numbers only as an audit trail; use the Phase 2.6 Model v3.1 report.

**Date:** September 2026  
**Status:** COMPLETED — PRIMARY ACCEPTANCE GATES & STRETCH GOALS SURPASSED  
**Model Version:** `model-v3`  
**Feature Contract:** `merchant-visible-causal-3` (46 features, SHA-256: `94c33005cb22d0d0cbbfe2e6878b668f237bfbfe88e2c0e98031d275727181ef`)  
**Model Artifacts Directory:** `artifacts/model_v3/`

---

## 1. Executive Summary

Model v3 was developed, cross-validated, calibrated, and evaluated on the newly generated Dataset v4. It directly incorporates the 7 causal remediation features defined in Feature Contract v3 (notably `card_diversity_ratio_7d`, `card_change_after_decline_ratio_7d`, `session_churn_rate_24h`, and merchant-relative context).

### Primary Acceptance Gates vs. Results
| Criterion | Mandatory Gate | Stretch Target | Model v3 Realized | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Attack REVIEW+ Recall** | $\ge 70.0\%$ | $\ge 80.0\%$ | **86.19%** | **SURPASSED STRETCH** |
| **Legitimate REVIEW+ Friction** | $\le 6.0\%$ | $\le 4.0\%$ | **1.57%** | **SURPASSED STRETCH** |
| **Legitimate BLOCK Rate** | $\le 1.0\%$ | $\le 0.5\%$ | **0.14%** | **SURPASSED STRETCH** |
| **PR-AUC (Validation)** | $\ge 0.70$ (stretch) | $\ge 0.70$ | **0.8684** | **SURPASSED STRETCH** |
| **ROC-AUC (Validation)** | $\ge 0.85$ (stretch) | $\ge 0.85$ | **0.9467** | **SURPASSED STRETCH** |
| **Brier Score (Validation)** | $\le 0.080$ (stretch) | $\le 0.080$ | **0.0556** | **SURPASSED STRETCH** |
| **ECE (Validation)** | $\le 0.030$ (stretch) | $\le 0.030$ | **0.0175** | **SURPASSED STRETCH** |
| **Counterfactual Ordering (CPOA)** | $\ge 90.0\%$ (stretch) | $\ge 90.0\%$ | **100.0%** (20/20) | **PERFECT ORDERING** |

---

## 2. Candidate Model Grid & Cross-Validation Results

Thirteen candidate configurations spanning three families were evaluated via 5-fold customer-grouped cross-validation strictly on the TRAIN split.

| Rank | Candidate Identifier | Family | OOF PR-AUC | OOF ROC-AUC | OOF Brier | OOF ECE | OOF Log-Loss |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **1** | **`logistic_C5.0`** | **Logistic Regression** | **0.8476** | **0.9332** | **0.1160** | **0.2135** | **0.3917** |
| 2 | `hist_gb_1` | HistGradientBoosting | 0.7922 | 0.9307 | 0.1415 | 0.2765 | 0.4685 |
| 3 | `logistic_interactions_C1.0` | Logistic + Interactions | 0.7673 | 0.8989 | 0.1634 | 0.2850 | 0.5105 |
| 4 | `logistic_C1.0` | Logistic Regression | 0.7656 | 0.8984 | 0.1642 | 0.2861 | 0.5123 |
| 5 | `hist_gb_2` | HistGradientBoosting | 0.7649 | 0.9253 | 0.1498 | 0.2891 | 0.4868 |
| 6 | `logistic_interactions_C0.5` | Logistic + Interactions | 0.7173 | 0.8787 | 0.1860 | 0.3050 | 0.5612 |
| 7 | `logistic_C0.5` | Logistic Regression | 0.7164 | 0.8781 | 0.1869 | 0.3067 | 0.5631 |
| 8 | `hist_gb_3` | HistGradientBoosting | 0.6979 | 0.8908 | 0.2008 | 0.3618 | 0.5942 |
| 9 | `logistic_C0.1` | Logistic Regression | 0.6326 | 0.8467 | 0.2279 | 0.3115 | 0.6487 |
| 10 | `logistic_interactions_C0.1` | Logistic + Interactions | 0.6307 | 0.8466 | 0.2271 | 0.3118 | 0.6472 |
| 11 | `logistic_C0.05` | Logistic Regression | 0.6162 | 0.8412 | 0.2376 | 0.3126 | 0.6683 |
| 12 | `logistic_interactions_C0.05`| Logistic + Interactions | 0.6134 | 0.8408 | 0.2371 | 0.3131 | 0.6673 |
| 13 | `logistic_C0.01` | Logistic Regression | 0.6011 | 0.8363 | 0.2473 | 0.3182 | 0.6877 |

**Selection Rationale:**  
`logistic_C5.0` achieved the highest cross-validated PR-AUC (0.8476) and ROC-AUC (0.9332), outperforming both the gradient-boosted trees and explicit interaction models while retaining full interpretability and linear monotonicity.

---

## 3. Calibration Comparison

Calibration was fitted strictly on out-of-fold predictions of the selected candidate (`logistic_C5.0`):

| Calibration Method | PR-AUC | ROC-AUC | Brier Score | ECE | Log-Loss | Selection Decision |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Uncalibrated (`none`)** | 0.8476 | 0.9332 | 0.1160 | 0.2135 | 0.3917 | High raw calibration error |
| **Sigmoid (Platt)** | **0.8476** | **0.9332** | **0.0599** | **0.0145** | **0.2133** | **SELECTED** (Zero PR-AUC loss, 93% ECE drop) |
| **Isotonic Regression** | 0.8334 | 0.9344 | 0.0579 | 0.0000 | 0.2062 | Rejected (Costs 0.0142 PR-AUC) |

Sigmoid calibration reduced the Expected Calibration Error (ECE) from 0.2135 to 0.0145 without sacrificing any PR-AUC ranking power, satisfying the calibration adoption criteria.

---

## 4. Operational Scenario Breakdown (Validation Split)

Evaluating Model v3 under unchanged Policy v2 (`review >= 0.75`, `block >= 0.90`, `block_evidence = 2`):

| Scenario Family | Population | Devices | REVIEW+ Rate | BLOCK Rate | Mean Max Score | Evaluation Notes |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `subscription_dunning_hard` | Legitimate | 300 | **0.0%** | **0.0%** | 0.0245 | Rejected Dataset-v4 development result; no independent confirmation. |
| `persistent_card_problem_hard` | Legitimate | 296 | **0.7%** | **0.0%** | 0.1397 | Single card declines correctly insulated |
| `network_retry_storm_hard` | Legitimate | 262 | **0.4%** | **0.0%** | 0.1207 | High-velocity retries not penalized |
| `cgnat_mobile_ip_storm` | Legitimate | 260 | **2.3%** | **0.0%** | 0.1949 | Shared IP storms protected |
| `shared_household_device` | Legitimate | 260 | **8.1%** | **0.8%** | 0.2583 | Multiple legitimate cards on 1 device |
| `normal_returning_customer` | Legitimate | 315 | **0.6%** | **0.0%** | 0.0629 | Established customer baseline |
| `normal_guest_checkout` | Legitimate | 286 | **0.3%** | **0.0%** | 0.1267 | Guest shoppers clean |
| `cross_device_weak_guest` | Attack | 185 | **94.1%** | **73.5%** | 0.9498 | Rejected Dataset-v4 result. Historical Blind v2: **20.7921% REVIEW+ (21/101), 0.9901% BLOCK (1/101)**. |
| `cross_device_partial` | Attack | 162 | **84.6%** | **66.0%** | 0.8881 | Strong cross-device detection |
| `distributed_bot_campaign` | Attack | 118 | **63.6%** | **32.2%** | 0.7719 | Coordinated diffuse botnet attack |
| `burst_pause_burst_v4` | Attack | 30 | **100.0%** | **100.0%** | 0.9931 | Coordinated pausing detected |
| `fast_burst_v4` | Attack | 19 | **100.0%** | **100.0%** | 0.9919 | High velocity detected immediately |
| `patient_tester_v4` | Attack | 30 | **96.7%** | **76.7%** | 0.9269 | Patient card rotation detected |

---

## 5. Counterfactual Twin Pair Evaluation (CPOA)

All 20 matched counterfactual pairs were scored on the held-out validation set.
- **Total Pairs Evaluated:** 20
- **Correctly Ordered Pairs (`Score(Attack) > Score(Legitimate)`):** 20
- **Counterfactual Pair Ordering Accuracy (CPOA):** **100.0%**

### Representative Counterfactual Pair Comparisons
- **`CP-01` (Single-card dunning vs 4-card rotation):** Attack twin = 0.9917 vs Legit twin = 0.2599 ($\Delta = +0.7318$).
- **`CP-02` (Wallet switch after decline vs High card churning):** Attack twin = 0.9926 vs Legit twin = 0.1223 ($\Delta = +0.8703$).
- **`CP-05` (Guest retry on same card vs Guest rotating card pool):** Attack twin = 0.7758 vs Legit twin = 0.0076 ($\Delta = +0.7682$).
- **`CP-17` (Established customer subscription renewal vs Reused device test):** Attack twin = 0.9889 vs Legit twin = 0.0059 ($\Delta = +0.9830$).

---

## 6. Policy Experiment Comparison: Unchanged Policy v2 vs Moderate Trust

| Metric | Experiment A: Unchanged Policy v2 (`trust_suppression: none`) | Experiment B: Moderate Trust (`trust_suppression: moderate`) | Delta / Impact |
| :--- | :---: | :---: | :--- |
| **Attack REVIEW+** | 86.19% | 86.19% | 0.00 pp |
| **Attack BLOCK** | 67.30% | 67.14% | -0.16 pp |
| **Legitimate REVIEW+** | 1.57% | 1.57% | 0.00 pp |
| **Legitimate BLOCK** | 0.14% | 0.14% | 0.00 pp |

**Policy Recommendation:**  
Because Model v3 already features causal trust features (`customer_successful_checkouts_30d`, `customer_age_seconds`) in its scoring layer, Model v3 produces virtually zero legitimate block friction (0.14%) under unchanged Policy v2. Adding post-model moderate trust suppression produces an identical legitimate block rate (0.14%) while softening 0.16 pp of genuine attacks from block to review. Therefore, **unchanged Policy v2 is retained as the operational baseline**.
