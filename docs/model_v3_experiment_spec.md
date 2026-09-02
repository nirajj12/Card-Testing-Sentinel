# Model v3 Experiment Specification, Evaluation Metrics & Phase 2 Feature Hypotheses

## 1. Evaluation Metric Specification (Defined Before Training)

Metrics must be formally declared and locked prior to any Phase 2 model exploration. In card-testing defense, optimizing purely for ROC-AUC is dangerous because a model can achieve 0.90 ROC-AUC while simultaneously inflicting intolerable 15% friction on genuine customers.

### 1.1 Development & Stretch Discrimination/Calibration Objectives
The following discrimination and calibration targets represent development and stretch objectives for model iteration; they are diagnostic goals, not newly invented hard acceptance gates:
| Metric | Development / Stretch Objective | Role in Card Testing |
|---|---|---|
| **PR-AUC** | $\ge 0.70$ (Stretch: $\ge 0.75$) | Precision-recall tradeoff on class-imbalanced transaction traffic. |
| **ROC-AUC** | $\ge 0.85$ (Stretch: $\ge 0.90$) | Global rank ordering across true positive vs false positive rates. |
| **Brier Score** | $\le 0.080$ (Stretch: $\le 0.070$) | Probabilistic forecast accuracy; critical for risk tiering. |
| **Expected Calibration Error (ECE)** | $\le 0.030$ (Stretch: $\le 0.015$, 10 bins) | Reliability of probabilities to prevent overconfident false blocks. |
| **Counterfactual Pair Ordering Accuracy (CPOA)** | $\ge 90.0\%$ (Stretch: $\ge 95.0\%$) | Domain-specific causal benchmark across 20 predeclared twin pairs. |

### 1.2 Primary Product Acceptance Gates vs Stretch Targets

To maintain strict continuity with established project constraints, the **primary mandatory acceptance gates** are preserved exactly from the pre-Blind Policy v2 budget (`configs/policy_v2.yaml`). Tighter goals are designated strictly as stretch targets:

| Policy Metric | Primary Mandatory Gate (Pre-Blind v2 Standard) | Development Stretch Target | Product Rationale |
|---|---|---|---|
| **Attack REVIEW+ Recall** | **$\ge 70.0\%$** | $\ge 80.0\%$ | Core attack detection ceiling required for operational deployment. |
| **Legitimate REVIEW+ Rate** | **$\le 6.0\%$** | $\le 4.0\%$ | Upper bound on customer challenge friction (step-up/OTP verification). |
| **Legitimate BLOCK Rate** | **$\le 1.0\%$** | $\le 0.5\%$ | Strict ceiling on catastrophic false blocks of genuine paying customers. |
| **Attack BLOCK Recall** | Reporting ($\ge 35.0\%$ diagnostic) | $\ge 45.0\%$ | Definitive suppression of gateway authorization fees. |

### 1.3 Early-Detection Velocity Objectives
- **Recall by Attempt 2**: Stretch $\ge 30\%$ (attackers challenged on their second attempt).
- **Recall by Attempt 3**: Stretch $\ge 50\%$.
- **Recall by Attempt 5**: Stretch $\ge 75\%$.
- **Median First Detection Attempt**: Target $\le 3.0$ attempts.
- **P90 First Detection Attempt**: Target $\le 6.0$ attempts.

### 1.4 Hard-Scenario Remediation Objectives
- **`cross_device_weak_guest` REVIEW+**: Objective $\ge 60.0\%$ (was 20.79% in Blind v2).
- **`cross_device_partial` REVIEW+**: Objective $\ge 70.0\%$ (was 40.60% in Blind v2).
- **`subscription_dunning` Legitimate BLOCK**: Objective $\le 1.0\%$ (was 72.66% in Blind v2).
- **`persistent_card_problem` Legitimate BLOCK**: Objective $\le 2.0\%$ (was 34.00% in Blind v2).
- **`network_retry_storm` Legitimate BLOCK**: Objective $\le 2.0\%$ (was 21.55% in Blind v2).

### 1.5 Runtime Latency SLA
- **p50 Latency**: $\le 2.0\text{ ms}$
- **p95 Latency**: $\le 8.0\text{ ms}$
- **p99 Latency**: $\le 15.0\text{ ms}$
Enforced at the `/api/precheck` endpoint under local SQLite WAL concurrency.

---

## 2. Model v3 Candidate Architecture & Selection Protocol

We do not presuppose a winning model architecture. In Phase 2, four model families will be systematically trained on Dataset v4 using 5-fold cross-validation grouped by customer and device:

### 2.1 Model Candidates Under Consideration
1. **Regularized Logistic Regression ($L_2$, Ridge)**:
   - *Pros*: Extremely fast ($< 0.1\text{ ms}$), monotonic, highly explainable, provably causal weights.
   - *Cons*: Cannot capture non-linear conjunctions (e.g., failure count high *AND* card count == 1 vs $> 1$).
2. **Logistic Regression with Domain-Engineered Interaction Terms**:
   - Explicit pairwise interaction terms:
     - `failures_7d` $\times$ `distinct_card_last4_7d`
     - `requests_5m` $\times$ `merchant_velocity_zscore`
     - `customer_id_present` $\times$ `customer_distinct_devices_7d`
     - `decline_streak` $\times$ `card_change_after_decline_7d`
   - *Pros*: Maintains linear model speed and calibration while resolving the dunning failure.
3. **Histogram-Based Gradient Boosting (`HistGradientBoostingClassifier`)**:
   - *Pros*: Native binning, non-linear feature splits, automatically decouples single-card retries from multi-card cycling, fast inference ($< 1.0\text{ ms}$).
   - *Cons*: Requires careful tree depth regularization (e.g., `max_depth=4`, `min_samples_leaf=50`) to prevent overfitting synthetic boundaries.
4. **LightGBM (Optional Candidate)**:
   - Gradient boosted trees with leaf-wise expansion, tested if `HistGradientBoosting` demonstrates superior discrimination.

### 2.2 Controlled Experimentation Matrix & Policy Ablation

To maintain rigorous scientific attribution, model and policy changes must never be entangled without an ablation:

| Experiment ID | Model Architecture | Feature Engine | Policy Version | Purpose / Attribution |
|---|---|---|---|---|
| **EXP-00 (Baseline)** | Model v2 (Frozen) | FeatureEngineV2 (39 feat) | Policy v2 (Frozen, trust: none) | Reference baseline on Dataset v4. |
| **EXP-01** | Model v2 (Retrained) | FeatureEngineV2 (39 feat) | Policy v2 (trust: none) | Measures impact of Dataset v4 alone. |
| **EXP-02** | Logistic + Interactions | FeatureEngineV3 | Policy v2 (trust: none) | Isolates benefit of FeatureEngineV3 under linear model. |
| **EXP-03** | HistGradientBoosting | FeatureEngineV3 | Policy v2 (trust: none) | Isolates tree-based non-linear capability. |
| **EXP-04** | Winning Model from 02/03 | FeatureEngineV3 | Policy v2 (Unchanged, trust: none)| Freezes best Model v3 under frozen Policy v2. |
| **EXP-05A (Policy Ablation)**| Winning Model from 04 | FeatureEngineV3 | Policy v2 + moderate trust suppression | Tests trust suppression effect in isolation. |
| **EXP-05B (Policy Remediated)**| Winning Model from 04 | FeatureEngineV3 | Policy v3 (Card-diversity evidence gated)| Tests card-diversity evidence gate requirement. |

#### Explicit Policy Experiment: Unchanged Policy v2 vs Moderate Trust Suppression
An explicit controlled comparison will evaluate:
1. **Model v3 + unchanged Policy v2 (`trust_suppression: none`)**
2. **Model v3 + Policy v2 with `trust_suppression: moderate`**

> [!IMPORTANT]
> Trust suppression is **not** automatically enabled. It is treated strictly as an experimental hypothesis. The motivation is to test whether established customer history (`customer_age_seconds`, `successful_checkouts_30d`) can suppress legitimate dunning and persistent card failure friction without materially degrading attack detection recall. The ablation in EXP-05A directly isolates this effect before any new Policy v3 is considered.

---

## 3. Deliverable I: Future Feature Hypotheses for Phase 2 (FeatureEngineV3)

The following feature families are proposed to resolve the diagnostic root causes identified in Phase 1. Every feature is audited for causal availability, implementation complexity, and runtime cost.

### 3.1 Temporal Cadence & Inter-Attempt Gap Shape
*Targeting: Fast burst, burst-pause-burst, variable cadence, and human vs bot discrimination.*

1. **`median_inter_attempt_gap_seconds_24h`**
   - *Definition*: Median time delta between consecutive requests on this entity over 24h.
   - *Raw fields*: Entity request timestamps. Window: 24 hours.
   - *Causal availability*: Yes. Computed from stored past request timestamps.
   - *Expected value*: Scripted bots show rigid low gaps ($< 2.0\text{s}$) or uniform synthetic delays; genuine users show human dwell times ($> 30\text{s}$).
   - *DB Sufficiency*: Sufficient from SQLite `requests` table. Runtime cost: Low ($O(K \log K)$, $K \le 30$).

2. **`gap_coefficient_of_variation_24h`**
   - *Definition*: Ratio of standard deviation of gaps to mean gap: $\sigma_{\Delta t} / \mu_{\Delta t}$.
   - *Expected value*: Human checkouts navigating UI show moderate variance ($\text{CV} \approx 0.8 – 1.5$); automated loops show near-zero variance ($\text{CV} < 0.1$); burst-pause attacks show extreme bimodal variance ($\text{CV} > 2.5$).

### 3.2 Card Diversity & Failure Conjunction Features
*Targeting: Decoupling legitimate dunning / network retry storms from actual card testing.*

3. **`card_diversity_ratio_7d`**
   - *Definition*: $\frac{\text{distinct\_card\_last4\_7d}}{\max(1, \text{requests\_7d})}$.
   - *Expected value*: Legitimate dunning retries = $1 / 6 = 0.16$. Card-testing attack = $5 / 6 = 0.83$.
   - *Causal availability*: Yes. Past card hashes arrive via `OutcomeRequest`.
   - *Impact*: Directly neutralizes the subscription dunning failure.

4. **`card_change_after_decline_ratio_7d`**
   - *Definition*: Fraction of declines that were immediately followed by a new card on the next attempt.
   - *Expected value*: Genuine user retry = 0.0 (retries same card). Attacker testing list = 1.0 (discards declined card instantly).

### 3.3 Relationship, Session Churn & Network Fan-Out
*Targeting: `cross_device_weak_guest` and distributed proxy attacks.*

5. **`devices_per_session_24h` & `session_churn_rate_24h`**
   - *Definition*: Number of distinct session IDs created on this device / IP within 24 hours divided by total requests.
   - *Expected value*: Elevated ($> 0.8$) when headless bots drop cookies on every attempt.

6. **`subnet_device_fanout_5m`**
   - *Definition*: Number of distinct active devices observed on the `/24` IPv4 (or `/64` IPv6) subnet in the last 5 minutes.
   - *Expected value*: Captures coordinated distributed bot runs targeting a merchant from a concentrated proxy provider.

### 3.4 Merchant-Relative Normalization Features
*Targeting: Multi-merchant robustness and calibration drift across archetypes.*

7. **`merchant_amount_log_ratio`**
   - *Definition*: $\log\left(\frac{\text{current\_amount}}{\text{merchant\_typical\_amount}}\right)$.
   - *Causal availability*: Yes. Merchant baseline parameters are pre-configured in merchant table.
   - *Expected value*: Center-scales order amounts across a ₹20 micro-merchant and a ₹45,000 electronics merchant into a single invariant distribution.

8. **`merchant_relative_velocity_zscore`**
   - *Definition*: $\frac{\text{requests\_5m} - \mu_{\text{merchant, 5m}}}{\sigma_{\text{merchant, 5m}}}$.
   - *Expected value*: 6 requests in 5m during a flash sale produces $z \approx +0.5$ (normal); 6 requests on a bespoke subscription store produces $z \approx +4.2$ (highly anomalous).

---

## 4. Rejection of Infeasible / Unsound Features

The following candidate features were evaluated and **formally rejected**:

1. **`gateway_decline_code_distribution`**:
   - *Rejection Reason*: The current authorization decline code is unknown at precheck time. While historical decline codes exist, relying heavily on specific decline strings risks gateway-specific overfitting and Razorpay schema dependencies.
2. **`ip_geolocation_country_match`**:
   - *Rejection Reason*: Requires external MaxMind GeoIP database lookup at runtime, introducing external network I/O, binary dependency bloat, and maintenance overhead violating the standalone Buildathon runtime SLA.
3. **`client_canvas_fingerprint_hash`**:
   - *Rejection Reason*: Highly fragile; easily spoofed by modern bot frameworks; introduces brittle frontend-to-backend coupling.
