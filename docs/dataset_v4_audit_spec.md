# Dataset v4 Shortcut & Leakage Audit Specification

This specification establishes the mandatory statistical audits, shortcut tests, and causal leakage verification that any generated Dataset v4 corpus must pass before model training.

---

## 1. Forbidden Leakage & Decision-Time Availability Table

Card-Testing Sentinel enforces a strict, verifiable causal boundary. In production, `/api/precheck` is invoked by the merchant frontend/backend **before** a Razorpay order is placed or payment details are collected.

The table below audits every field in the repository's API schemas (`card_testing_sentinel/api/contracts.py`) against decision-time availability:

| Field Name | Request Contract | Available at `/api/precheck`? | Allowed in Feature Engine? | Causality Status & Enforcement |
|---|---|---|---|---|
| `request_id` | `PrecheckRequest` | **Yes** | **No** (Identifier only) | Cryptographic request nonce; forbidden from model inputs. |
| `event_id` | `PrecheckRequest` | **Yes** | **No** (Identifier only) | Event identifier for idempotency; forbidden from model inputs. |
| `merchant_id` | `PrecheckRequest` | **Yes** | **Yes** (Contextual lookup) | Used only for tenant lookup & merchant-relative baseline mapping. |
| `customer_id` | `PrecheckRequest` | **Yes** (Optional) | **Indirectly** (Hashed) | HMAC-hashed to link prior customer history; raw ID forbidden. |
| `device_id` | `PrecheckRequest` | **Yes** | **Indirectly** (Hashed) | HMAC-hashed to link prior device history; raw ID forbidden. |
| `session_id` | `PrecheckRequest` | **Yes** | **Indirectly** (Hashed) | Used for session age & session churn velocity; raw ID forbidden. |
| `ip_reference` | `PrecheckRequest` | **Yes** | **Indirectly** (Hashed) | Subnet/IP reference used for IP velocity; raw IP forbidden. |
| `amount` | `PrecheckRequest` | **Yes** | **Yes** | Current checkout order total. |
| `currency` | `PrecheckRequest` | **Yes** | **Yes** (Metadata) | INR / USD. |
| `campaign_active` | `PrecheckRequest` | **Yes** | **Yes** | Merchant-declared promotional period flag. |
| `timestamp` | `PrecheckRequest` | **Yes** | **Yes** | Event timestamp; establishes strict causal cutoff. |
| `event_sequence` | `PrecheckRequest` | **Yes** | **Yes** | Monotonic counter enforcing deterministic tie-breaking. |
| `authorization_result` | `OutcomeRequest` | **NO** | **PROHIBITED** | Gateway authorization outcome; arrives only in later outcome event. |
| `failure_reason` | `OutcomeRequest` | **NO** | **PROHIBITED** | Bank decline code; known only after payment attempt completes. |
| `card_last4` | `OutcomeRequest` | **NO** | **PROHIBITED at precheck**| Card details are only captured by Razorpay Checkout; recorded for *future* history only. |
| `card_network` | `OutcomeRequest` | **NO** | **PROHIBITED at precheck**| Network (Visa/Mastercard) known only post-card entry. |
| `card_issuer` | `OutcomeRequest` | **NO** | **PROHIBITED at precheck**| Issuing bank known only post-card entry. |
| `razorpay_payment_id` | `Razorpay webhook`| **NO** | **PROHIBITED** | Razorpay payment identifier; does not exist at precheck. |
| `razorpay_order_id` | Internal Sentinel | **NO** | **PROHIBITED** | Created by Sentinel *only if* precheck returns `allow`. |
| `checkout_completed` | `CheckoutRequest` | **NO** | **PROHIBITED** | Post-purchase fulfillment signal; arrives minutes later. |
| `is_card_testing` | Ground truth | **NO** | **PROHIBITED** | Synthetic simulation label; forbidden from features. |
| `scenario_id` / `family`| Synthetic metadata | **NO** | **PROHIBITED** | Simulation archetype; forbidden from features. |

---

## 2. Dataset Balance Audits

Before training, the dataset generation script must produce an automated audit report validating distribution health:

1. **Device-Level Prevalence**:
   - Attack device fraction: $18.0\% \pm 2.0\%$ (enriched benchmark prevalence).
   - Attempt-level positive prevalence: $15.0\% – 22.0\%$.
2. **Merchant Representation**:
   - Minimum 20 merchants across 6 archetypes.
   - No single merchant may represent $> 15\%$ of total attempts.
   - Every archetype must represent at least $8\%$ of total attempts.
3. **Identity Representation**:
   - Customer-present requests: $50\% – 65\%$ across aggregate corpus.
   - Guest requests: $35\% – 50\%$ across aggregate corpus.
   - Attack guest requests: $30\% – 60\%$ (ensures attacks test both guest and account paths).
   - Legitimate guest requests: $30\% – 50\%$ (ensures clean guests are abundant).

---

## 3. Single-Feature Shortcut & Leakage Audit

A notorious failure mode of synthetic fraud benchmarks is **shortcut learning**: an unintended artifact of generation (such as an ID format, rounding in amounts, or a binary flag) perfectly predicts fraud, preventing the model from learning genuine behavioral signatures.

### 3.1 Audit Methodology
For every candidate feature $X_j \in \mathcal{F}$, train an isolated univariate diagnostic classifier (a shallow Decision Tree of depth 2 or a single-variable Logistic Regression) to predict `is_card_testing` on a held-out evaluation slice.

### 3.2 Diagnostic Guardrails vs Hard Failure Rules

Fixed single-feature PR-AUC thresholds are treated as **diagnostic guardrails**, not automatic hard PASS/FAIL gates. 
- **Hard Failure**: Strictly reserved for **unambiguous causal leakage**, including:
  - Synthetic scenario ID, campaign name, or generator archetype strings.
  - Simulation ground-truth attack labels.
  - Future authorization outcomes (`approved`, `declined`).
  - Gateway decline codes or Razorpay payment identifiers.
  - Post-authorization settlement, chargeback, or fulfillment data.
  - Any impossible precheck feature.
- **Diagnostic Guardrails**: Flags single features that exhibit suspicious discriminative power for engineering review:

| Feature Category | Diagnostic Review Guardrail | Diagnostic Purpose |
|---|---|---|
| **Metadata / Non-Behavioral**<br>(`customer_id_present`, `amount`, `is_new_device`, `customer_age_seconds`, `hour_of_day`) | **PR-AUC $\ge 0.35$**<br>(Prevalence $\approx 0.18$) | If metadata alone predicts attack intent, inspect for synthetic artifacts (e.g. imbalanced login ratios or un-overlapped amounts). |
| **Traffic Velocity**<br>(`requests_10s`, `requests_60s`, `requests_5m`, `requests_24h`, `sessions_24h`) | **PR-AUC $\ge 0.65$** | Guardrail to ensure burst attacks are sufficiently balanced against legitimate flash sales and retry storms. |
| **Domain Behavioral Signals**<br>(`distinct_card_last4_7d`, `card_change_after_decline_7d`, `failures_7d`) | **PR-AUC $\ge 0.80$** | High predictive power is expected, but values approaching 0.85 warrant inspection to ensure legitimate wallet cycling is represented. |

### 3.3 Comprehensive Audit Reporting Requirements

The audit script `scripts/audit_dataset_v4.py` must compute and report the following metrics for every candidate feature:
1. **Single-Feature PR-AUC**: Univariate precision-recall AUC.
2. **Lift over Prevalence**: $\frac{\text{PR-AUC}}{\text{Base Positive Prevalence}}$ (measures relative signal concentration).
3. **Train / Stress Stability**: Difference in single-feature PR-AUC between development train and shifted stress splits ($|\Delta \text{PR-AUC}| \le 0.15$ target).
4. **Scenario Dependence**: Variance in feature prediction accuracy across attack scenario families.
5. **Legitimate-Family Dependence**: False-positive concentration across legitimate scenario families (e.g., dunning vs guest).
6. **Manual Diagnostic Verdict**: Structured output (`PASS_UNRESTRICTED`, `REVIEW_ELEVATED_SIGNAL`, `HARD_FAIL_LEAKAGE`).

#### Audit Table Schema

| Feature Name | Category Tier | Single-Feature PR-AUC | Lift over Prev | Train/Stress Stability | Scenario Dependence | Legit-Family Dependence | Diagnostic Verdict |
|---|---|---|---|---|---|---|---|
| `customer_id_present` | Metadata | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `current_amount` | Metadata | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `is_new_device` | Metadata | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `customer_age_seconds` | Metadata | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `requests_60s` | Velocity | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `requests_5m` | Velocity | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `devices_per_ip_24h` | Velocity | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `failures_7d` | Domain | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `distinct_card_last4_7d`| Domain | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| `card_change_after_decline_7d`| Domain | *Reported* | *Reported* | *Reported* | *Reported* | *Reported* | PASS / REVIEW |
| *Future outcome / metadata* | Leakage | N/A | N/A | N/A | N/A | N/A | **HARD FAIL (PROHIBITED)** |

---

## 4. Synthetic ID & Ordering Integrity Checks

To prevent models from exploiting synthetic generator IDs:
1. **No Lexical Clues in Identifiers**:
   - `request_id`, `event_id`, `customer_id`, `device_id`, `session_id`, and `ip_reference` must be generated via cryptographically secure pseudo-random hex tokens (`secrets.token_hex(16)` or UUIDv4).
   - Identifiers must **never** contain substrings indicating their scenario (e.g., `dev_attack_01` or `cust_legit_dunning` are strictly illegal; must be `c_7f8a9b2c...`).
2. **Timestamp Monotonicity**:
   - All events must be sorted chronologically. Event sequence numbers must start at 0 per device and increment monotonically.
   - Any event with negative time delta or future-dated timestamp triggers immediate pipeline halt.
