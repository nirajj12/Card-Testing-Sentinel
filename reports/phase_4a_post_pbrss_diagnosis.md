# Post-PBRSS Shift Diagnosis Report

## Goal

Investigate why Model v3.1 encountered elevated legitimate review friction (20.72% overall, 25.30% in ordinary checkout) under the Post-Blind Remediation Stress Suite (PBRSS-v1), using descriptive distribution shift analysis without rescoring or retuning the model.

## Setup

- **Model:** `model-v3.1` (Histogram Gradient Boosting `hist_gb_2`, frozen)
- **Feature Contract:** `merchant-visible-causal-3.1` (44 causal features)
- **Policy:** Policy v2 (`review_threshold=0.75`, `block_threshold=0.90`)
- **Evaluation Status:** PBRSS-v1 is consumed; this diagnostic analysis is read-only. No model, feature, policy, or threshold changes were made.
- **Reference Baseline:** 16,325 legitimate validation rows from Dataset v4.1
- **Target Population:** 12,082 ordinary-checkout rows from PBRSS-v1

## What I Tested

- **Friction Concentration:** Identified which legitimate scenarios drove the 20.72% legitimate review rate.
- **Covariate Shift Analysis:** Computed Population Stability Index (PSI) and Kolmogorov-Smirnov (KS) statistics across all 44 features between Dataset v4.1 and PBRSS-v1 ordinary checkout.
- **Outcome and Velocity Patterns:** Analyzed decline streak, retry speed, and failure ratios.
- **Identity and Trust Metrics:** Examined customer presence, device age, and historical successful checkout distributions.
- **Calibration Drift:** Analyzed reliability bin distributions to assess probability calibration transfer under stress.

## Results

### 1. Friction Distribution Across Scenarios

| PBRSS Legitimate Scenario | Devices | REVIEW+ Rate | BLOCK Rate | Observation |
| :--- | ---:| ---:| ---:| :--- |
| `ordinary_checkout` | 3,000 | **25.30%** | **0.13%** | Primary source of false friction |
| `charity_micro_donation_spike` | 500 | **0.00%** | **0.00%** | Clean handling of high-velocity shared IPs |
| `b2b_multi_corporate_card` | 250 | **7.20%** | **0.80%** | Moderate review rate on corporate multi-card flows |

False friction was heavily concentrated in ordinary checkout (1 in 4 devices reviewed), while charity micro-donations had 0.00% review and block rates.

### 2. Top 15 Shifted Features (Dataset v4.1 vs. PBRSS Ordinary Checkout)

| Feature | Family | Dev v4.1 Mean / Median | PBRSS Ordinary Mean / Median | PSI | KS | Direction |
| :--- | :--- | ---:| ---:| ---:| ---:| :--- |
| `device_age_seconds` | Identity / Trust | 8,703,738 / 2,592,000 | 45,620 / 7.53 | **6.854** | 0.585 | Lower |
| `seconds_since_last_payment` | Outcome History | 1,071,890 / 143,509 | 30,772 / 4.46 | **6.820** | 0.535 | Lower |
| `customer_age_seconds` | Identity / Trust | 8,382,688 / 2,592,000 | 18,277 / 0.00 | **6.375** | 0.555 | Lower |
| `seconds_since_last_success` | Identity / Trust | 1,073,631 / 145,928 | 31,241 / 3.81 | **6.073** | 0.533 | Lower |
| `seconds_since_last_request` | Velocity / Timing | 946,141 / 77,701 | 30,772 / 4.46 | **5.131** | 0.486 | Lower |
| `sessions_24h` | Session Dynamics | 1.256 / 1.000 | 1.000 / 1.000 | **2.204** | 0.181 | Lower |
| `median_gap_between_attempts` | Temporal Shape | 276,226 / 0.00 | 222.36 / 3.43 | **2.057** | 0.239 | Lower |
| `ip_changes_24h` | Network | 0.158 / 0.000 | 0.000 / 0.000 | **1.462** | 0.129 | Lower |
| `session_churn_rate_24h` | Session Dynamics | 0.872 / 1.000 | 0.544 / 0.500 | **1.400** | 0.523 | Lower |
| `amount_variation_24h` | Amount | 2,354.39 / 0.00 | 8,356.07 / 173.82 | **1.175** | 0.516 | Higher |
| `prior_payments_24h` | Outcome History | 0.687 / 0.000 | 1.448 / 1.000 | **1.125** | 0.461 | Higher |
| `ip_rotation_ratio_24h` | Network | 0.847 / 1.000 | 0.544 / 0.500 | **1.043** | 0.484 | Lower |
| `customer_successful_checkouts_30d` | Identity / Trust | 0.672 / 1.000 | 0.206 / 0.000 | **1.038** | 0.435 | Lower |
| `requests_24h` | Velocity / Timing | 1.785 / 1.000 | 2.448 / 2.000 | **0.850** | 0.388 | Higher |
| `distinct_card_last4_7d` | Card History | 0.415 / 0.000 | 0.719 / 1.000 | **0.801** | 0.335 | Higher |

### 3. Key Behavioral Shifts Identified

- **Identity and Age Collapse:** Median `device_age_seconds` fell from 30 days to 7.5 seconds. `customer_id_present` fell from 79.06% to 39.26%. Legitimate shoppers had virtually no established device or account history.
- **Thinner Successful Checkout Context:** Device `successful_checkouts_30d` zero-fraction rose from 40.48% to 75.14%. Customer `successful_checkouts_30d` zero-fraction rose from 46.62% to 90.13%.
- **Denser Retries with More Exposed Failures:** Mean `requests_10s` increased from 1.160 to 1.648; median time between requests dropped from 21.6 hours to 4.5 seconds. While mean failure counts remained similar (0.587 vs 0.609), failures were spread over more rows (zero-fraction fell from 78.74% to 60.06%), and mean `failure_ratio_24h` increased from 0.204 to 0.293.
- **Calibration Transfer Error:** Sigmoid calibration underperformed on the shifted distribution (ECE = 0.1407, Brier = 0.1560). In the lowest risk bin `[0.0, 0.1)`, mean predicted risk was 0.0158 but the observed attack rate was 0.1454, while higher bins overestimated risk.

## What the Results Mean

1. **Multivariate Distribution Shift:** Ordinary-checkout review friction did not stem from a single broken feature or simple decline-count spikes. It was caused by a compound shift: unestablished device age, absent customer identity, dense same-session retries, and thinner successful checkout history.
2. **Context Matters:** In charity traffic, high request velocity and shared IPs produced 0.00% review friction because other attack signatures were absent. In ordinary checkout, the lack of positive trust history caused legitimate retries to trigger review thresholds.
3. **No Rescoring Permitted:** Because PBRSS-v1 was a consumed evaluation suite, these insights were not used to retune Model v3.1 or adjust Policy v2 thresholds.

## Limitations

- **Descriptive, Not Causal:** PSI and KS measure distribution divergence; they do not quantify the exact attribution of individual features to specific decisions.
- **Prototype Readiness:** High attack detection (96.40% REVIEW+, 59.12% BLOCK) combined with 0.16% legitimate BLOCK is technically promising, but 20.72% legitimate review friction prevents claiming production readiness.
- **Synthetic Benchmark:** PBRSS-v1 is an independent synthetic stress suite, not real production merchant traffic.

## Reproducibility

- **Analysis Dataset:** `artifacts/analysis/phase_4a_ordinary_checkout_feature_shift.csv`
- **Plot:** `artifacts/figures/phase_4a_feature_shift.png`
