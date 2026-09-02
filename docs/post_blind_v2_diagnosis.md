# Post-Blind v2 Comprehensive ML/Data/Evaluation Diagnosis

## Executive Summary

On August 31, 2026, Card-Testing Sentinel evaluated its frozen `model-v2` and `validation-selected-v2` policy on the pre-committed, independent `blind-v2` evaluation benchmark (`artifacts/evaluation/blind_v2_metrics.json`). The evaluation was executed with strict freeze verification (`evaluated = true`, `consumed = true`, `post_blind_tuning = false`).

The final verdict was **WEAK synthetic generalization**.
While core attack-review coverage met the 70% threshold (70.50%), legitimate-user friction severely violated pre-declared operating budgets:
- **Legitimate REVIEW+**: **14.91%** (Budget: $\le 6.0\%$, **FAILED**)
- **Legitimate BLOCK**: **5.09%** (Budget: $\le 1.0\%$, **FAILED**)
- **Model PR-AUC**: **0.4871** (Development Validation: 0.7783, $\Delta = -0.2911$)
- **Model ROC-AUC**: **0.7351** (Development Validation: 0.9041, $\Delta = -0.1690$)
- **Brier Score**: **0.1521** (Development: 0.0743, $\Delta = +0.0778$)
- **ECE**: **0.1171** (Development: 0.0181, $\Delta = +0.0990$)

This document performs an exhaustive, evidence-based post-mortem of why Model v2 degraded between development and Blind v2. It provides exact quantitative scenario breakdowns, isolates root causes across data, features, models, calibration, and policy layers, and establishes empirical hypotheses for remediation.

---

## 1. What Worked: Validated Strengths Under Blind v2

Despite the aggregate friction failure, specific architectural mechanisms and scenario detections succeeded decisively.

### 1.1 Strongest Attack Scenario Families

Model v2 and Policy v2 demonstrated high detection on concentrated, single-device velocity attacks and long-horizon single-identity probing:

| Attack Scenario | Devices | Requests | Review+ Rate | Block Rate | Never Detected | Median 1st Review Attempt | Median 1st Block Attempt |
|---|---|---|---|---|---|---|---|
| `variable_cadence_v2` | 29 | 313 | **100.0%** (29/29) | 89.66% (26/29) | 0 | 4.0 | 5.0 |
| `success_camouflage_v2` | 28 | 304 | **100.0%** (28/28) | 67.86% (19/28) | 0 | 5.0 | 9.0 |
| `merchant_normal_amount_attack`| 30 | 275 | **96.67%** (29/30) | 63.33% (19/30) | 1 | 4.0 | 7.0 |
| `fast_burst_v2` | 29 | 330 | **96.55%** (28/29) | 72.41% (21/29) | 1 | 5.0 | 9.0 |
| `burst_pause_burst_v2` | 24 | 284 | **95.83%** (23/24) | 91.67% (22/24) | 1 | 5.0 | 7.0 |
| `session_churn_v2` | 27 | 284 | **92.59%** (25/27) | 74.07% (20/27) | 2 | 4.0 | 7.0 |
| `patient_tester_v2` | 46 | 160 | **89.13%** (41/46) | 28.26% (13/46) | 5 | 2.0 | 3.0 |
| `sparse_multiday_v2` | 69 | 185 | **86.96%** (60/69) | 15.94% (11/69) | 9 | 2.0 | 3.0 |
| `ultra_patient_v2` | 45 | 141 | **86.67%** (39/45) | 8.89% (4/45) | 6 | 2.0 | 5.5 |
| `cross_device_strong` | 184 | 407 | **75.54%** (139/184)| 46.74% (86/184) | 45 | 2.0 | 2.0 |

**Key findings on what worked:**
1. **Camouflage resistance**: Attacks attempting to disguise themselves with realistic order amounts (`merchant_normal_amount_attack`: 96.7% Review+) or interleaved successful payments (`success_camouflage_v2`: 100.0% Review+) were flagged reliably because card diversity and decline counters accumulated regardless of amount.
2. **Patient probe detection**: Patient, ultra-patient, and sparse multiday testers were flagged at Review+ within attempt 2 (median 2.0), showing that multi-day state aggregation in SQLite (`failures_7d`, `active_day_count_7d`) correctly persisted across multi-day gaps.
3. **Strong cross-device tracking**: When attackers operated multiple devices linked by a shared customer identity (`cross_device_strong`), `customer_distinct_devices_7d` triggered rapidly, achieving 75.54% review and 46.74% block.

### 1.2 Legitimate Cohorts with Zero or Controlled Friction

Clean legitimate users without abnormal failure histories experienced zero or near-zero intervention:

| Legitimate Scenario | Devices | Requests | Review+ Rate | Block Rate | Block Target | Result |
|---|---|---|---|---|---|---|
| `new_guest_checkout` | 411 | 605 | **0.0%** (0/411) | **0.0%** (0/411) | $\le 1.0\%$ | Perfect pass |
| `dormant_returning_customer_v2` | 166 | 924 | **0.0%** (0/166) | **0.0%** (0/166) | $\le 1.0\%$ | Perfect pass |
| `returning_long_history` | 287 | 1,982 | **0.35%** (1/287) | **0.0%** (0/287) | $\le 1.0\%$ | Perfect pass |
| `household_shared_ip` | 410 | 527 | **1.22%** (5/410) | **0.0%** (0/410) | $\le 1.0\%$ | Pass |
| `campus_office_shared_network` | 351 | 747 | **2.56%** (9/351) | **0.0%** (0/351) | $\le 1.0\%$ | Pass |
| `multi_device_customer_v2` | 616 | 1,163 | **6.82%** (42/616) | **0.0%** (0/616) | $\le 1.0\%$ | Pass (0 blocks) |
| `campaign_rush_v2` | 153 | 580 | **8.50%** (13/153) | **0.0%** (0/153) | $\le 1.0\%$ | Pass (0 blocks) |

**Key findings on legitimate safety:**
1. **Unpenalized Guest Checkout**: 411 guest checkout devices had zero false flags (0.0%). The missing-customer imputation (`CUSTOMER_MISSING_NEUTRAL = 0.0`) ensured that absence of account identity was not treated as suspicion.
2. **Network sharing tolerance**: Office, campus, and household IP sharing had 0.0% block rate and $\le 2.6\%$ review rate, demonstrating that IP-level features (`devices_per_ip_24h`, `requests_per_ip_5m`) were sufficiently bounded.
3. **Multi-device customer safety**: Genuine customers switching between phone and laptop (`multi_device_customer_v2`) had 0.0% block rate.

---

## 2. What Failed: Detailed Breakdown of Blind v2 Failures

### 2.1 Weak Attack Families (Undetected Card Testing)

The most alarming failure mode on the attack side was distributed, weak-linkage card testing:

| Weak Attack Family | Devices | Requests | Review+ Rate | Block Rate | Never Detected Devices | Never Detected % |
|---|---|---|---|---|---|---|
| `cross_device_weak_guest` | 101 | 274 | **20.79%** (21/101) | **0.99%** (1/101) | 80 | **79.21%** |
| `cross_device_partial` | 133 | 378 | **40.60%** (54/133) | **3.76%** (5/133) | 79 | **59.40%** |
| **Combined Weak/Partial** | **234** | **652** | **32.05%** (75/234) | **2.56%** (6/234) | **159** | **67.95%** |

In `cross_device_weak_guest`:
- 80 out of 101 attack devices were **never detected** (neither review nor block).
- Only 1 device out of 101 reached `block`.
- Median first review was at attempt 4.0 (for the few detected), compared to attempt 2.0 for strong linkage.

**Why it escaped**:
The attacker rotated devices across attempts without authenticating (`customer_id` was absent/guest), while changing IPs or using wide IP distributions. Because FeatureEngineV2 relies heavily on:
1. `customer_distinct_devices_7d` (requires `customer_id`)
2. `customer_failures_7d` (requires `customer_id`)
3. Per-device request/failure counts (each new device starts with zero prior history)
Each new device appeared to the feature engine as a clean, first-time guest checkout.

### 2.2 Catastrophic Legitimate False Friction

The aggregate legitimate-friction violation was driven by three catastrophic failure scenarios:

| Problematic Legitimate Family | Devices | Requests | Reviewed Devices | Blocked Devices | Review+ Rate | Block Rate | Never Detected Rate |
|---|---|---|---|---|---|---|---|
| `subscription_dunning_v2` | 128 | 1,435 | 127 | 93 | **99.22%** | **72.66%** | 0.78% |
| `persistent_card_problem_v2` | 100 | 676 | 86 | 34 | **86.00%** | **34.00%** | 14.00% |
| `network_retry_storm_v2` | 116 | 811 | 88 | 25 | **75.86%** | **21.55%** | 24.14% |
| `high_value_retry_v2` | 120 | 417 | 54 | 8 | **45.00%** | **6.67%** | 55.00% |
| `mobile_network_churn_v2` | 164 | 685 | 30 | 2 | **18.29%** | **1.22%** | 81.71% |

#### Observed Empirical Evidence
1. In `subscription_dunning_v2`, 128 devices generated 1,435 requests; 127 reached Review+ (99.22%) and 93 reached Block (72.66%). 112 of these 128 devices had historical successful checkouts within 30 days.
2. In `persistent_card_problem_v2`, 100 devices generated 676 requests; 86 reached Review+ (86.00%) and 34 reached Block (34.00%).
3. In Model v2's feature contract, multiple failure counts accumulate simultaneously:
   - `failures_7d` (coef: +0.1679)
   - `decline_streak` (coef: +0.1853)
   - `customer_failures_7d` (coef: +0.1776)
   - `failures_per_active_day_7d` (coef: +0.1602)
   - `failure_ratio_24h` (coef: +0.0296)
4. Policy v2's evidence gate required 2 elevated evidence features. In dunning, `failures_7d >= 2` and `decline_streak >= 2` qualified as evidence without requiring multi-card rotation.

#### Leading Hypotheses for Subscription Dunning Friction (To Be Tested by Ablation in Phase 2)
We formulate three leading hypotheses to be tested experimentally. They must not be treated as proven facts prior to controlled ablation:
- **Hypothesis A (Linear Model Additivity)**: The linear model sums positive weights across multiple correlated failure counts (`failures_7d`, `decline_streak`, `customer_failures_7d`). Because it lacks non-linear interaction terms, it cannot distinguish a customer retrying the exact same expired card from an attacker cycling distinct cards.
- **Hypothesis B (Policy Evidence Gate Criteria)**: Policy v2's `evidence_gated_v2` allowed pure decline counts to satisfy the block qualification gate without demanding card-diversity evidence (`distinct_card_last4_7d >= 2`).
- **Hypothesis C (Absence of Trust Suppression)**: Policy v2 was configured with `trust_suppression: "none"`. Genuine accounts with established checkout tenure received no score discount to mitigate failure streaks.

Phase 2 must isolate these hypotheses via controlled ablations (Model v2 vs v3, linear vs tree, Policy v2 vs Policy v2 + moderate trust suppression).

### 2.3 Calibration and Generalization Collapse

Between Dataset v3 validation and Blind v2:
- **ECE increased by 6.5x**: from 0.0181 to 0.1171.
- **Brier score degraded by 2.0x**: from 0.0743 to 0.1521.
- **Log loss increased from 0.2586 to 0.5007**.
- Sigmoid calibration fitted on development validation predictions broke down under shifted feature distributions (device age median shifted from 157k to 7.8k seconds, PSI = 0.9358; amount median shifted from ₹1,125 to ₹4,321, PSI = 0.2887).

---

## 3. Leading Hypotheses for Phase 2 Exploration

The following structured hypotheses represent testable engineering propositions, separated strictly from observed evidence:

### Hypothesis 1: Weak Cross-Device Guest Attack Blindness
- **Layer**: Feature & Dataset Design
- **Observed evidence**: `cross_device_weak_guest` Review+ recall was 20.79% (80 of 101 devices never detected; only 1 device blocked).
- **Leading hypothesis**: FeatureEngineV2 tracks cross-device linkage primarily through `customer_id` (`customer_distinct_devices_7d`). In unauthenticated guest attacks where devices are rotated, entity linkage is absent, causing each device to appear as an isolated, clean first attempt.
- **Dataset issue to test**: Development data (Dataset v3) trained models on `cross_device_campaign` with strong customer/IP linkage, lacking weak-linkage guest testing.
- **Feature hypothesis to test**: Coordinated guest bot attacks exhibit cross-entity signatures: temporal burst coordination, rapid session churn (`sessions_24h` / session age), and subnet-level clustering.
- **Required experiment**: Synthesize weak-guest distributed attacks in Dataset v4; add session-churn and subnet relationship features in FeatureEngineV3; measure recall on held-out distributed attack cohorts.

### Hypothesis 2: Subscription Dunning and Single-Card Retry False Positives
- **Layer**: Feature Contract, Model Architecture & Policy Gate
- **Observed evidence**: 99.22% Review+ and 72.66% Block on `subscription_dunning_v2`; 86% Review+ and 34% Block on `persistent_card_problem_v2`.
- **Leading hypothesis**: A combination of additive failure weights and policy evidence gating without card-diversity requirements causes repeated declines on a single card to trigger high risk and block actions.
- **Dataset issue to test**: Development data lacked deep multi-day dunning episodes with high retry counts paired against long account tenure (12+ months) and identical recurring amounts.
- **Feature/Model hypothesis to test**: Decoupling `failures_7d` when `distinct_card_last4_7d == 1` vs `distinct_card_last4_7d > 2` via interaction terms or decision tree splits, paired with trust discounting for established accounts, will reduce single-card retry friction.
- **Required experiment**: Run controlled ablation matrix: (1) Model v2 baseline, (2) Model v3 with interaction terms, (3) Model v3 tree-based, (4) Policy v2 with unchanged policy vs Policy v2 with moderate trust suppression.

### Hypothesis 3: Linear Calibration Breakdown Under Distribution Shift
- **Layer**: Calibration & Model Layer
- **Observed evidence**: ECE expanded from 0.008 (OOF) / 0.018 (validation) to 0.1171 on Blind v2; Brier score increased from 0.074 to 0.152.
- **Leading hypothesis**: Sigmoid (Platt) scaling fitted on in-distribution validation logits does not generalize when input features undergo significant covariate shift across unseen merchants and temporal regimes.
- **Dataset issue to test**: Dataset v3 lacked merchant-relative normalization, allowing absolute order amounts and velocities to vary drastically across merchant domains.
- **Feature/Model hypothesis to test**: Merchant-relative normalization (amount relative to merchant typical amount, velocity relative to merchant baseline) will stabilize input distributions across merchant archetypes, improving calibration robustness.
- **Required experiment**: Benchmark sigmoid vs isotonic vs temperature calibration across out-of-merchant evaluation splits.

### Hypothesis 4: Policy Evidence Gate Conflation
- **Layer**: Policy Layer
- **Observed evidence**: The `evidence_gated_v2` policy blocked 93 subscription dunning devices because `failures_7d >= 2` and `decline_streak >= 2` were counted as valid "attack evidence".
- **Leading hypothesis**: Policy v2's evidence rules (`evidence_set: v2_full`) allowed pure failure counts to qualify a device for `block`, without requiring multi-card cycling or cross-entity churn.
- **Policy issue to test**: Evidence criteria did not require *card-testing specific proof*. A customer experiencing two declines on the same card satisfied the block gate.
- **Policy hypothesis to test**: Requiring at least one *card-diversity or velocity-fanout indicator* (e.g., `distinct_card_last4_7d >= 2` OR `devices_per_ip_24h >= 2`) before granting `block` action will prevent blocking single-card retry storms.
- **Required experiment**: Re-evaluate Policy v2 evidence definitions; test Policy v2 with moderate trust suppression and card-diversity gating.

---

## 4. Separation of Concerns Matrix

| System Layer | Primary Symptoms in Blind v2 | Necessary Remediation |
|---|---|---|
| **Data / Generator** | Lack of weak-guest distributed attacks; under-representation of legitimate single-card dunning; narrow merchant variety. | **Dataset v4**: Define 6 merchant archetypes, explicit hard-negative single-card retries, weak-linkage distributed campaigns. |
| **Feature Contract** | Inability to separate same-card retries from card cycling; over-reliance on `customer_id`; missing merchant context. | **FeatureEngineV3 (Phase 2)**: Distinct cards per decline, merchant-relative velocity, temporal gap variance. |
| **Model** | Linear additivity forces failure counts to explode risk; cannot represent conjunctions (failures AND new_card). | **Model v3 (Phase 2)**: Evaluate interaction terms, HistGradientBoosting / LightGBM alongside regularized logistic regression. |
| **Calibration** | Sigmoid scaling breaks down when feature medians shift across unseen merchants. | **Phase 2 Calibration**: Evaluate isotonic vs Platt scaling on held-out merchant slices; require ECE $\le 0.03$. |
| **Policy** | Evidence gate allows pure failure counts to trigger blocking; absence of trust discount. | **Policy Remediation**: Block evidence must require multi-card evidence or extreme burst cadence, never single-card declines alone. |
| **Runtime / API** | Fully causal, deterministic, and safe (verified); no leakage found. | Preserve strict `/api/precheck` contract, HMAC integrity, and SQLite WAL persistence. |
