# Dataset v4 Specification (Post-Blind Development Corpus)

## 1. Overview and Design Purpose

**Dataset v4** is the foundational development corpus designed to train and validate **Model v3** and **Policy v3**.
It is **not** simply "Dataset v3 with more rows." Dataset v4 is engineered specifically to eliminate the vulnerabilities, shortcuts, and failure modes exposed by the `blind-v2` evaluation:

1. **Elimination of the "Failure = Card Testing" Shortcut**: Single-card retries, network storms, CVV mistakes, and dunning failures are heavily represented in legitimate traffic to force models to rely on *card diversity* and *cross-entity coordination*, rather than simple failure accumulation.
2. **Dense Representation of Distributed / Weak-Guest Attacks**: Weak-linkage attacks (`cross_device_weak_guest`, `cross_device_partial`) where attackers operate without persistent customer accounts across rotated sessions/devices are first-class attack cohorts.
3. **Deep Merchant Heterogeneity**: Introducing 6 distinct merchant archetypes with wildly divergent ticket sizes, login affinities, and base failure rates, preventing the model from using raw monetary amounts or raw attempt frequencies as global shortcuts.
4. **Causal Precheck Purity**: Absolute enforcement that only facts observable prior to authorization can enter feature computation.

---

## 2. Technical Specification & Governance

| Attribute | Specification |
|---|---|
| **Dataset Version** | `development-v4` |
| **Generator Version** | `dataset-v4-generator-1` |
| **Spec Version** | `v4-postblind-draft` |
| **Primary Random Seed** | `918273645` |
| **Merchant Generation Seed** | `102938475` |
| **Currency** | `INR` |
| **Temporal Window** | 180 simulated calendar days (6 months of activity) |
| **Total Simulated Requests** | **45,000 – 60,000 requests** |
| **Total Simulated Devices** | **10,000 – 14,000 unique devices** |
| **Unique Customer Accounts** | **6,000 – 8,000 registered customer identities** |
| **Guest Checkout Devices** | **4,000 – 6,000 unauthenticated devices** |
| **Target Device Prevalence** | 18.0% attack devices (enriched for sensitivity; non-production) |
| **Coverage Principle** | **Device/Entity-Centric Coverage**: Statistical power is anchored on device counts per critical scenario, not merely aggregate request counts. |
| **Split Strategy** | 60% Train, 20% Out-of-fold/Calibration, 20% Validation (grouped by customer identity, then device) |

### 2.1 Critical Scenario Device Allocation Targets (250–300 Devices Minimum)
To ensure device-level metrics (Review+, Block, First Detection Attempt) have narrow confidence intervals and do not suffer from small-sample noise, high-priority attack and hard-negative families have explicit device allocation minimums:

| Priority Class | Scenario Family | Minimum Target Devices | Primary Diagnostic Purpose |
|---|---|---|---|
| **Attack (High Priority)** | `cross_device_weak_guest` | **250 – 300 devices** | Solves 80% miss rate from Blind v2; tests unauthenticated bot-farm recall. |
| **Attack (High Priority)** | `cross_device_partial` | **250 – 300 devices** | Tests multi-device campaigns with partial proxy / session linkage. |
| **Attack (High Priority)** | `distributed_bot_campaign` | **250 – 300 devices** | Evaluates multi-device single-attempt coordinated bot runs. |
| **Legitimate (Hard Negative)**| `subscription_dunning_hard` | **250 – 300 devices** | Solves 72.7% false-block failure; validates single-card retry safety. |
| **Legitimate (Hard Negative)**| `persistent_card_problem_hard` | **250 – 300 devices** | Solves 34.0% false-block failure; tests CVV / limit decline retry safety. |
| **Legitimate (Hard Negative)**| `network_retry_storm_hard` | **250 – 300 devices** | Solves 21.6% false-block failure; tests automated client network bursts. |
| **Legitimate (Hard Negative)**| `shared_household_device` | **250 – 300 devices** | Tests multi-identity / multi-card sharing on aged hardware. |
| **Legitimate (Hard Negative)**| `cgnat_mobile_ip_storm` | **250 – 300 devices** | Tests cellular IP multiplexing without customer penalty. |

---

## 3. Deliberate Incorporation of Blind-v2 Covariate Shifts

In Blind v2, several features underwent severe distribution shifts (e.g. `device_age_seconds` PSI = 0.9358; `customer_age_seconds` PSI = 0.5285; `active_day_count_7d` PSI = 0.4269; `gap_variability` PSI = 0.3542; `session_age_seconds` PSI = 0.3271; `current_amount` PSI = 0.2887).

Dataset v4 directly incorporates these shifts into the synthetic DGP (data generating process) by deliberately crossing orthogonal behavioral axes:

| Covariate Shift Dimension | Deliberate Bivariate / Factorial Combinations in Dataset v4 | Engineering Purpose |
|---|---|---|
| **Device Age $\times$ Customer Age** | 1. **Old customer / new device** (e.g. 2-year customer buying on newly purchased phone).<br>2. **New customer / aged device** (e.g. second-hand laptop or family member signing up).<br>3. **Old customer / aged device** (steady established baseline).<br>4. **New customer / new device** (clean first-time sign-up). | Breaks the false assumption that new devices imply fraud, or that old devices imply accounts. |
| **Session Age $\times$ Attempt Cadence** | 1. **Short session / regular cadence** (quick checkout flow).<br>2. **Long session / regular cadence** (deliberate shopper with multiple tabs).<br>3. **Short session / highly irregular cadence** (network disconnects, browser tab restores).<br>4. **Rapid session churn / fixed cadence** (automated headless bot resetting storage). | Teaches models to separate browser instability from adversarial session rotation. |
| **Customer History $\times$ Behavior Drift**| 1. **Long-established customer behaving unusually** (e.g., sudden burst of 4 attempts after 180 days dormancy due to expired card replacement).<br>2. **New guest behaving with perfectly steady cadence**. | Prevents models from over-relying on customer age as an unconditional pass or newness as a penalty. |
| **Amount Distribution Shift** | 1. Shifted amount distribution ranges across all 6 archetypes.<br>2. Micro-amounts occurring in legitimate gaming/digital goods alongside attacks.<br>3. Typical merchant-normal amounts tested by sophisticated attackers. | Forces model to use merchant-relative amount anomaly rather than absolute ticket size. |
| **Gap Variability ($\sigma_{\Delta t} / \mu_{\Delta t}$)**| 1. **Regular cadence** ($\text{CV} < 0.2$, automated retry loops).<br>2. **Human variable cadence** ($0.6 < \text{CV} < 1.6$, normal browsing).<br>3. **Bimodal burst-pause** ($\text{CV} > 2.5$, rapid retries then multi-hour pause). | Gives models explicit training examples on both human and bot gap distributions. |

---

## 4. Merchant Archetype Distribution

Dataset v4 instantiates **20 distinct merchants** drawn from 6 structural business archetypes. Each merchant archetype imposes different baseline behavior:

| Merchant Archetype | Instance Count | Typical Amount Range (INR) | Amount Spread (CV) | Account Login Affinity | Base Gateway Failure Rate | Burst / Flash Tolerance |
|---|---|---|---|---|---|---|
| **Standard Retail / E-commerce** | 5 | ₹800 – ₹3,500 | 0.60 – 0.90 | 0.70 – 0.85 | 3% – 6% | Low |
| **Guest-Heavy Direct-to-Consumer** | 4 | ₹400 – ₹2,200 | 0.50 – 0.80 | **0.15 – 0.35** | 4% – 8% | Moderate |
| **Subscription & SaaS Billing** | 3 | ₹299 – ₹1,999 | **0.10 – 0.30** | **0.95 – 1.00** | 8% – 16% (dunning) | Low |
| **Micro-Payment / Digital Goods** | 3 | ₹19 – ₹299 | 0.80 – 1.40 | 0.40 – 0.70 | 5% – 10% | High velocity |
| **Flash-Sale / Ticket Drop Platform** | 3 | ₹499 – ₹4,999 | 0.40 – 0.70 | 0.30 – 0.60 | 10% – 22% (concurrency) | **Very High** |
| **High-Ticket Electronics & Travel** | 2 | ₹8,000 – ₹75,000 | 0.70 – 1.30 | 0.65 – 0.85 | 6% – 12% (limit declines)| Low |

**Critical Architectural Principle**:
The same raw behavior (e.g., 6 attempts in 3 minutes) represents normal customer behavior during a flash sale drop or subscription billing retry wave, but is highly abnormal for a luxury travel site. Dataset v4 ensures models cannot use absolute thresholds that overfit one merchant type at the expense of another.

---

## 5. Customer Identity & Guest Modeling

Blind v2 proved that `customer_id_present` must **never** be a proxy for risk or legitimacy.

1. **Configurable Login Affinity**:
   - Subscription merchants enforce 95–100% customer account presence.
   - Guest-heavy D2C merchants enforce only 15–35% customer account presence.
   - Attackers vary: some test cards under compromised accounts (`customer_id` present), while others test via guest checkout (`customer_id` absent).
2. **Strict Missing-Value Semantics**:
   When `customer_id` is null (guest checkout), customer features must be imputed with exact neutral values:
   - `customer_id_present = 0.0`
   - `customer_distinct_devices_7d = 0.0`
   - `customer_failures_7d = 0.0`
   - `customer_successful_checkouts_30d = 0.0`
   - `customer_age_seconds = 0.0`
3. **No Target Leakage via Guest Status**:
   In Dataset v4, the correlation between `customer_id_present` and `is_card_testing` is constrained to $|\rho| < 0.08$. Both legitimate users and attackers checkout frequently as guests.

---

## 5. Ground Truth Labelling Rules

Every record in Dataset v4 has a single ground-truth binary label:
- `label = 1` (`is_card_testing = True`): The attempt is generated by a card-testing actor or campaign seeking to validate, probe, or cycle through payment credentials.
- `label = 0` (`is_card_testing = False`): The attempt is generated by a genuine customer actor experiencing normal shopping, card friction, retry behavior, or system issues.

### Scenario Metadata (Non-Model Fields)
To facilitate rigorous slice-level evaluation and diagnostic audits, the raw dataset records auxiliary metadata fields:
- `scenario_id`: Unique identifier of the specific scenario simulation.
- `scenario_family`: E.g., `subscription_dunning`, `cross_device_weak_guest`.
- `actor_id`: Global synthetic actor identifier.
- `merchant_archetype`: E.g., `subscription`, `flash_sale`.
- `linkage_strength`: E.g., `none`, `weak`, `partial`, `strong`.

> [!IMPORTANT]
> **Strict Isolation**: Scenario metadata fields are strictly partitioned into training evaluation tables and **must never** be ingested by `FeatureEngineV3` or passed into model training pipelines.

---

## 6. Forbidden Leakage & Temporal Causality Rules

Dataset v4 strictly enforces the **Merchant-Visible Pre-Authorization Boundary**.
Any event that occurs during or after authorization is strictly forbidden from the precheck record:

| Forbidden Field | Why It Is Forbidden | Decision Time State |
|---|---|---|
| `authorization_result` | Outcome is determined by issuing bank/network *after* precheck | Unknown |
| `failure_reason` | Decline code (insufficient funds, CVV mismatch) returned by Razorpay after auth | Unknown |
| `razorpay_payment_id` | Created only if attempt is allowed and payment initiated | Unknown |
| `razorpay_order_id` | Created by Sentinel only after `allow` verdict | Unknown |
| `checkout_completed` | Occurs minutes after precheck approval | Unknown |
| `chargeback_dispute` | Reported 30–90 days post-transaction | Unknown |
| `scenario_name` / `family` | Synthetic ground-truth artifact | Prohibited |

### Event Ordering and Causality
- All timeline events are sorted deterministically by `(timestamp, event_sequence, event_id)`.
- For attempt $N$, the feature state snapshot is computed strictly from events $\{1, \dots, N-1\}$. Event $N$'s own outcome is not recorded until an `OutcomeRequest` arrives at a later timestamp $t_{\text{outcome}} > t_{\text{precheck}}$.

---

## 7. Determinism and Cryptographic Provenance

To satisfy the buildathon's release-integrity standards, Dataset v4 generation must be 100% reproducible across machines and operating systems:

1. **Fixed PRNG Streams**:
   - Master seed: `918273645`
   - Independent sub-generators for Merchant parameters, Actor timelines, Network delays, and Card credential pools using standard Mersenne Twister (`numpy.random.Generator` with explicit Philox/PCG64 bit generator).
2. **Artifact Manifest and Fingerprints**:
   Upon completion, the dataset generator computes and writes:
   - `configs/dataset_v4.yaml.sha256`
   - `data/generated/dataset_v4_raw.csv.sha256`
   - `data/generated/dataset_v4_features.csv.sha256`
   - `data/generated/dataset_v4_labels.csv.sha256`
   - `data/generated/dataset_v4_manifest.json`
3. **No In-Place Modification**:
   Dataset v4 scripts will write only to `data/generated/v4/` and `artifacts/v4/`. The frozen historical files `dataset_v3.*`, `model_v2.*`, and `blind_v2.*` remain 100% untouched.
