# Policy v2 Selection Report

## Goal

Document the deterministic grid search and selection of Policy v2 (`validation-selected-v2` / `evidence_gated_v2`) on validation data without inspecting subsequent blind benchmarks.

## Setup

- **Policy Version:** `validation-selected-v2`
- **Policy Family:** `evidence_gated_v2`
- **Development Dataset:** Dataset v3 (validation split)
- **Model Pairing:** Selected on Model v2 out-of-fold validation; retained as the active operational policy for Model v3.1
- **Grid Space:** 864 candidate policy configurations evaluated

## What I Tested

- **Threshold Grid Search:** Evaluated combinations of review thresholds (0.50–0.75 in 0.05 steps), block thresholds (0.75, 0.80, 0.85, 0.90), evidence counts (1, 2, 3), and evidence feature sets (`v1_like`, `v2_long_horizon`, `v2_full`).
- **Constraint Boundaries:** Enforced strict guardrails: maximum 1.0% legitimate hard blocks, maximum 6.0% legitimate review friction, minimum 70.0% attack review recall, and a 5:1 ratio of review to block headroom.
- **Family Stress Guardrails:** Evaluated performance across 10 attack families and 9 legitimate cohorts to avoid catastrophic concentration in specific transaction types.
- **Degraded Fallback:** Verified rule-only fallback logic when ML scores are unavailable.
- **Config & Artifact Lifecycle:** Tested deterministic serialization, hashing, and independent verification of config and artifact bytes.

## Results

### 1. Selected Policy v2 Operating Parameters

- **Review Threshold:** **0.75**
- **Block Threshold:** **0.90**
- **Block Evidence Gate:** $\ge 2$ signals from `v2_full`
- **Trust Suppression:** `none`
- **Block TTL:** 3,600 seconds (60 minutes)
- **Campaign Increments:** 0.00 review / 0.00 block
- **Degraded Rule-Only Thresholds:** Review at rule score 4, block at rule score 6

### 2. Review Threshold Sweep (Validation Attempts)

| Review Cut | Attack REVIEW+ | Legit REVIEW+ | Precision | Total Attempts | Attempt Rate |
|---:|---:|---:|---:|---:|---:|
| 0.40 | 95.51% | 14.58% | 78.27% | 4,790 | 38.57% |
| 0.45 | 95.30% | 12.52% | 79.66% | 4,581 | 36.88% |
| 0.50 | 94.23% | 10.92% | 80.98% | 4,374 | 35.22% |
| 0.55 | 94.23% | 9.33% | 82.32% | 4,190 | 33.74% |
| 0.60 | 93.38% | 8.16% | 83.20% | 4,030 | 32.45% |
| 0.65 | 91.67% | 7.27% | 83.89% | 3,824 | 30.79% |
| 0.70 | 89.96% | 6.14% | 84.93% | 3,583 | 28.85% |
| **0.75** | **87.39%** | **5.30%** | **86.08%** | **3,334** | **26.84%** |
| 0.80 | 83.55% | 4.31% | 87.76% | 2,999 | 24.15% |

### 3. Block Threshold Sweep (Selected Evidence Gate $\ge 2$)

| Block Cut | Attack BLOCK | Legit BLOCK | Score-Only Attempts | Evidence-Qualified | Suppressed |
|---:|---:|---:|---:|---:|---:|
| 0.75 | 86.11% | 5.25% | 3,334 | 3,298 | 36 |
| 0.80 | 82.69% | 4.27% | 2,999 | 2,976 | 23 |
| 0.85 | 77.99% | 2.58% | 2,471 | 2,463 | 8 |
| **0.90** | **59.19%** | **0.89%** | **1,409** | **1,409** | **0** |

*Cuts below 0.90 exceeded the 1.0% legitimate hard-block ceiling. 0.90 was selected.*

### 4. Aggregate Validation Outcome (468 Attack, 2,133 Legitimate Devices)

- **Attack REVIEW+:** **87.39%** (409 devices)
- **Attack BLOCK:** **59.19%** (277 devices)
- **Legitimate REVIEW+:** **5.30%** (113 devices)
- **Legitimate BLOCK:** **0.89%** (19 devices)
- **Median / p90 First Review:** **4 / 6.2 attempts**
- **Median / p90 First Block:** **7 / 12 attempts**

### 5. Detection Delay Progression

| By Attempt | REVIEW+ | BLOCK |
|---:|---:|---:|
| 1 | 4.49% | 0.64% |
| 2 | 19.87% | 4.70% |
| 3 | 29.27% | 9.62% |
| 5 | 72.44% | 16.03% |

### 6. Family Breakdown Performance

#### Attack Families
| Family | Devices | REVIEW+ | BLOCK |
|---|---:|---:|---:|
| `fast_burst` | 28 | 85.71% | 67.86% |
| `slow_drip` | 50 | 92.00% | 66.00% |
| `patient_tester_weeks` | 37 | 89.19% | 45.95% |
| `sparse_multiday_tester` | 42 | 92.86% | 66.67% |
| `cross_device_campaign` | 164 | 82.32% | 46.95% |
| `session_churn` | 33 | 90.91% | 78.79% |
| `successful_card_camouflage` | 30 | 90.00% | 73.33% |
| `warm_up_then_test` | 24 | 79.17% | 45.83% |
| `flash_sale_camouflage` | 34 | 88.24% | 64.71% |
| `merchant_typical_amounts` | 26 | 100.00% | 84.62% |

#### Legitimate Families
| Family | Devices | REVIEW+ | BLOCK |
|---|---:|---:|---:|
| `subscription_dunning` | 71 | 29.58% | 4.23% |
| `network_retry_storm` | 63 | 15.87% | 4.76% |
| `persistent_card_problem_customer` | 75 | 12.00% | 5.33% |
| `household_shared_device` | 107 | 8.41% | 0.00% |
| `mobile_network_churn` | 93 | 6.45% | 0.00% |
| `shared_network_customer` | 166 | 4.22% | 1.81% |
| `returning_customer_multi_episode` | 370 | 4.86% | 0.27% |
| `multi_device_customer` | 353 | 3.97% | 0.57% |
| `cold_start_guest` | 402 | 0.00% | 0.00% |

### 7. Customer Identity Segments

| Segment | Attack REVIEW+ | Attack BLOCK | Legit REVIEW+ | Legit BLOCK |
|---|---:|---:|---:|---:|
| Customer ID Absent | 81.90% | 52.38% | 1.21% | 0.00% |
| Customer ID Present | 88.98% | 61.16% | 7.12% | 1.29% |

Missing customer identity is treated as neutral rather than suspicious, ensuring guests are not disproportionately blocked (0.00% legitimate block rate).

### 8. Artifact SHA-256 Checksums

- `operational_policy_v2.json`: `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c`
- `configs/policy_v2.yaml`: `92b0173e0ba073a9a20b7f09e5d0d82c9d40a52598cb9140ede36714a03c0052`

## What the Results Mean

1. **Balanced Threshold Selection:** The selected cuts (0.75 review, 0.90 block) met all predefined business gates on the validation set, keeping overall legitimate hard blocking under 1% (0.89%) while achieving 87.39% attack review recall.
2. **Neutral Identity Philosophy:** Unauthenticated guests are not flagged simply for lacking customer IDs, keeping false positive rates low for guest checkout flows.
3. **Early Identification of Dunning Friction:** The grid search surfaced high false friction in subscription dunning (29.58% review+) and lower block rates on patient testing (45.95%) long before subsequent stress testing.

## Limitations

- **Synthetic Validation Data:** Evaluated on Dataset v3 synthetic splits, not live production merchant transactions.
- **Dunning Sensitivity:** Repeated recurring billing declines with changing error codes triggered high review friction in this validation population.

## Reproducibility

- **Selection Script:**
  ```bash
  python pipelines/select_policy_v2.py
  ```
- **Policy Configuration:** `configs/policy_v2.yaml`
- **Operational Policy Artifact:** `artifacts/policy_v2/operational_policy_v2.json`
