# Model v3.1 Development & Validation Report

## Goal

Document the development, actor-safe cross-validation, calibration, and synthetic validation of Model v3.1 to establish a robust pre-stress candidate.

## Setup

- **Model Version:** `model-v3.1`
- **Selected Candidate:** `hist_gb_2` (Histogram Gradient Boosting)
- **Hyperparameters:** `learning_rate=0.08`, `max_leaf_nodes=31`, `max_iter=150`, `l2_regularization=2.0`
- **Calibration:** Sigmoid (Platt scaling)
- **Dataset:** `development-v4.1` (12,000 devices, 69,274 auth requests)
- **Feature Contract:** `merchant-visible-causal-3.1` (44 strictly causal features)
- **Active Policy:** Policy v2 (`review_threshold=0.75`, `block_threshold=0.90`, `block_evidence=2`, `evidence_set=v2_full`)

## What I Tested

- **Candidate Selection:** Evaluated 13 model candidates across tree-based and regularized linear families using 5-fold actor-safe grouped cross-validation on TRAIN.
- **Probability Calibration:** Compared uncalibrated scores against Sigmoid (Platt) and Isotonic calibration to minimize Expected Calibration Error (ECE) without losing ranking quality.
- **Synthetic Development Validation:** Evaluated the selected calibrated model on the held-out 3,500-device validation split (630 attack, 2,870 legitimate) against predefined product gates.
- **Scenario Breakdown:** Checked performance across 8 critical fraud and legitimate scenario cohorts.
- **Counterfactual Ordering (CPOA):** Evaluated risk scores on 20 synthetic counterfactual twin pairs sharing identical surface attributes.

## Results

### 1. Candidate Benchmarking (5-Fold Grouped Cross-Validation on TRAIN)

| Candidate | Family | Key Hyperparameters | OOF PR-AUC | OOF ROC-AUC | OOF Brier | OOF ECE | OOF Log-Loss |
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

`hist_gb_2` achieved the highest cross-validation PR-AUC (0.9384) and lowest log-loss (0.1532), winning selection over regularized logistic baselines.

### 2. Probability Calibration

| Method | PR-AUC | ROC-AUC | Brier Score | ECE | Log-Loss | Decision |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Uncalibrated (`none`)** | 0.9384 | 0.9790 | 0.0440 | 0.0554 | 0.1532 | Baseline raw scores |
| **Sigmoid (Platt)** | **0.9384** | **0.9790** | **0.0357** | **0.0147** | **0.1360** | **Selected** (Preserves exact ranking; reduces ECE by 73%) |
| **Isotonic** | 0.9310 | 0.9800 | 0.0321 | 0.0000 | 0.1148 | Rejected (Incurs 0.0074 PR-AUC ranking loss) |

Sigmoid calibration preserved exact score ranking while reducing ECE from 0.0554 to 0.0147.

### 3. Held-Out Development Validation Performance

| Metric | Target Gate | Stretch Target | Model v3.1 Result | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Attack REVIEW+ Recall** | $\ge 70.0\%$ | $\ge 80.0\%$ | **93.49%** (589/630) | Met stretch |
| **Legitimate REVIEW+ Friction** | $\le 6.0\%$ | $\le 4.0\%$ | **3.14%** (90/2870) | Met stretch |
| **Legitimate BLOCK Rate** | $\le 1.0\%$ | $\le 0.5\%$ | **0.14%** (4/2870) | Met stretch |
| **Attack BLOCK Rate** | Diagnostic | Diagnostic | **67.46%** (425/630) | Strong blocking |
| **PR-AUC (Device-Weighted)** | $\ge 0.70$ | $\ge 0.70$ | **0.9169** | Met stretch |
| **ROC-AUC (Device-Weighted)**| $\ge 0.85$ | $\ge 0.85$ | **0.9693** | Met stretch |
| **Brier Score** | $\le 0.080$ | $\le 0.080$ | **0.0410** | Met stretch |
| **ECE** | $\le 0.030$ | $\le 0.030$ | **0.0214** | Met stretch |
| **Counterfactual Ordering (CPOA)** | $\ge 90.0\%$ | $\ge 90.0\%$ | **100.0%** (20/20 pairs) | Perfect pair ranking |

### 4. Critical Scenario Breakdown (Validation Split)

| Scenario Name | Population | Devices | REVIEW+ Rate | BLOCK Rate | Mean Max Score | Finding |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `subscription_dunning_hard` | Legitimate | 347 | **0.00%** | **0.00%** | 0.0093 | Zero false friction on repeated declines |
| `persistent_card_problem_hard` | Legitimate | 282 | **4.61%** | **0.00%** | 0.1481 | Low friction; zero false blocks |
| `network_retry_storm_hard` | Legitimate | 287 | **2.79%** | **0.00%** | 0.1114 | Low friction during rapid single-card retries |
| `shared_household_device` | Legitimate | 267 | **0.00%** | **0.00%** | 0.0526 | Clean handling of multiple cardholders on one device |
| `cgnat_mobile_ip_storm` | Legitimate | 292 | **0.68%** | **0.00%** | 0.0217 | Resilient to shared carrier IP bursts |
| `cross_device_weak_guest` | Attack | 135 | **96.30%** | **61.48%** | 0.9009 | High detection on unauthenticated card probes |
| `cross_device_partial` | Attack | 150 | **97.33%** | **77.33%** | 0.9134 | High recall on partial identity rotation |
| `distributed_bot_campaign` | Attack | 112 | **76.79%** | **0.00%** | 0.7106 | Flags diffuse activity for review; zero hard blocks |

### 5. Policy v2 Stability Check

Testing Policy v2 with unchanged settings versus moderate trust suppression showed identical friction (3.14% REVIEW+, 0.14% BLOCK in both) and slightly lower attack blocking (67.14% vs 67.46%). Policy v2 was therefore retained without modification.

## What the Results Mean

1. **Effective Behavioral Learning:** On development validation, Model v3.1 separated card testing from legitimate checkout failures (0.00% dunning friction, 93.49% attack recall).
2. **Clean Historical Decoupling:** Model v3 was discarded earlier due to CV grouping leakage and ungrounded pseudo-features. Model v3.1 was built cleanly with actor-safe grouping and strictly causal merchant-visible features.
3. **CPOA Verification:** Achieving 100% CPOA across 20 twin pairs confirms that the model responds to causal behavioral changes rather than non-causal surface noise.

## Limitations

- **Synthetic Development Evidence:** These results reflect simulated development data. They do not prove real-world generalization or production readiness.
- **Distributed Botnet Weakness:** When attackers spread single attempts across 50 independent devices (`distributed_bot_campaign`), REVIEW+ was 76.79%, but BLOCK was 0.00%. Without cross-merchant network intelligence, single-attempt devices lack sufficient local evidence for hard blocking.
- **Historical Context:** Blind v2 evaluation of Model v2 previously yielded a `WEAK` verdict. While Model v3.1 performed well on development data, subsequent evaluation on the shifted stress suite (PBRSS-v1) showed material calibration and friction degradation.

## Reproducibility

- **Model Training Pipeline:**
  ```bash
  python pipelines/train_model_v3.py
  ```
- **Training Configuration:** `configs/training_v3_1.yaml`
- **Saved Model Artifact:** `artifacts/model_v3_1/risk_model_v3_1.joblib`
- **Metadata:** `artifacts/model_v3_1/metadata.json`
