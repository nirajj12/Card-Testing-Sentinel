# External Card-Testing & Fraud Datasets Assessment

This document provides a rigorous architectural evaluation of two prominent external machine learning fraud datasets:
1. The 2025 Mendeley Data synthetic banking dataset with explicit card-testing labels.
2. The IEEE-CIS Fraud Detection benchmark.

The goal is to determine whether either dataset can be integrated directly into Card-Testing Sentinel's training pipeline or evaluation suite, or if their structural assumptions are incompatible with Sentinel's pre-authorization defense layer.

---

## 1. Mendeley Data: "Synthetic Banking Transaction Dataset with Multi-Pattern Fraud Labels" (2025)

### 1.1 Provenance & Dataset Specifications
- **Title**: *Synthetic Banking Transaction Dataset with Multi-Pattern Fraud Labels for Machine Learning Research*
- **Authors**: Md Mehedi Hasan and Maria Rashid
- **Platform / Repository**: Mendeley Data (Version 2, published 2025/2026)
- **Persistent DOI**: `10.17632/ktbthg777x.2`
- **License**: Creative Commons Attribution 4.0 International (`CC BY 4.0`)
- **Volume**: 1,000,000 transaction records
- **Entities**: 100,000 unique synthetic customer accounts, 20,000 merchant profiles
- **Denomination**: United States Dollar (USD)
- **Fraud Prevalence**: Approximately 0.5% (5,000 fraudulent transactions)
- **Target Labels**: Multi-class categorization:
  1. `card_testing` (Rapid micro-transactions probing card validity)
  2. `account_takeover` (Compromised account credential abuse)
  3. `money_laundering_rings` (Structured funds dispersal)
  4. `geographic_anomalies` (Physically improbable transaction velocity)

---

### 1.2 Structural & Schema Audit vs Card-Testing Sentinel

| Dimension | Mendeley Banking Dataset (2025) | Card-Testing Sentinel (CTS) Architecture | Compatibility Assessment |
|---|---|---|---|
| **System Perspective** | **Core Banking / Card Issuer Ledger** (internal account balance debits & transfers) | **Merchant Pre-Checkout Gateway** (`POST /api/precheck` before order creation) | **Fundamental Mismatch**: Bank sees settled debit/credit flows; Sentinel sees pre-authorization attempts. |
| **Decision Timing** | **Post-Authorization Ledger Event** (recorded after bank host processes transaction) | **Pre-Authorization Decision** (strictly before Razorpay order is opened) | **Fatal Leakage Risk**: Banking records incorporate balance shifts and settlement state. |
| **Card Metadata** | Account / card ID linked to known bank customer profile | Hashed card token (`card_last4`, network) **observable only on past outcomes**, not current attempt | Banking dataset assumes card identity is known upfront by issuer; CTS cannot observe card on current precheck. |
| **Device & Session Identity**| Geolocation lat/long; IP address; no browser fingerprint | Client-provided HMAC-protected `device_id`, `session_id`, `ip_reference` | Lacks browser session churn, client device fingerprints, and local device timelines. |
| **Guest Checkout Support** | Zero. All transactions map to a registered bank account (`customer_id`). | **35% – 75% Guest Checkouts** across e-commerce merchants. | Missing unauthenticated guest checkout dynamics (the exact blind spot exposed in Blind v2). |
| **Currency & Market** | USD | INR (Razorpay Test Mode standard) | Amounts cannot be mapped without arbitrary FX adjustments. |

### 1.3 Exact Meaning of the "Card Testing" Label in Mendeley
In the Mendeley dataset, card testing is modeled as an account-level anomaly: a customer account generates rapid micro-transactions ($< \$5.00$) in rapid sequence.
While this captures the velocity aspect, it reflects an **issuer's view of an attacked card**, not a **merchant's view of an attacking bot**. An e-commerce merchant does not observe multiple attempts on the same card from one user; rather, the merchant observes **multiple different cards being tried by one bot or across rotating guest sessions**.

### 1.4 Formal Classification & Usage Decision

The current schemas and decision boundaries do not support a defensible direct Model-v3 benchmark without additional compatibility analysis. Therefore its initial role is Category C: scenario/distribution reference.

- **Direct Model v3 Evaluation**: Not feasible under the current feature contract without extensive imputation and schema projection.
- **Direct Training Corpus**: Not recommended; issuer ledger dynamics differ from merchant-visible pre-checkout causality.
- **Approved Role**: Scenario and distribution reference for realistic banking decline ratios, micro-amount distributions, and multi-pattern attack characterization.

---

## 2. IEEE-CIS Fraud Detection Benchmark (Vesta Corporation)

### 2.1 Problem Formulation & Fraud Label Semantics
The IEEE-CIS dataset (Kaggle / Vesta Corporation, 2019) is the standard benchmark in academic fraud detection (590,540 e-commerce transactions).
However, its target variable `isFraud` has a very specific definition:
$$\text{isFraud} = 1 \iff \text{The transaction was authorized, settled, and subsequently resulted in a reported chargeback/fraud loss.}$$

### 2.2 Why IEEE-CIS Does NOT Represent Card Testing
1. **Card Testing Rarely Produces Chargebacks**:
   Card testing consists of automated scripts probing thousands of card numbers against merchant checkout forms. Over 85% of card-testing attempts **fail authorization** (declined for invalid CVV, expired date, or inactive card). The few that approve are usually for ₹1 or ₹50 and are quickly abandoned by the attacker. They almost never materialize as formal issuer chargebacks.
2. **Survival Bias**:
   Because IEEE-CIS records primarily completed, authorized payments, all the card-testing attempts that were successfully blocked or declined by gateway risk engines were filtered out before dataset creation.
3. **Anonymized Features vs Causal Engine**:
   IEEE-CIS masks features behind proprietary transformations (`V1` – `V339`, `C1` – `C14`, `D1` – `D15`). It provides relative time deltas rather than calendar timestamps, preventing the reconstruction of real-world diurnal rhythms, 7-day failure decay, or exact SQLite WAL replay.

### 2.3 Formal Usage Decision

We classify IEEE-CIS under **Category D: Feature-Research Reference Only**.

- **Primary Training Data**: **REJECTED**. CTS is not a generic CNP chargeback prevention model; it is a specialized card-testing sentinel operating before order creation.
- **External Benchmark**: **REJECTED**. Contract and feature incompatibility make direct inference mathematically impossible without fabricating synthetic mappings.
- **Approved Role**: Literature reference for entity-matching techniques (e.g., how Vesta engineered `D` timedelta features and `C` counting features).

---

## 3. Comparative Summary & Architectural Boundary

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Payment Lifecycle                                      │
├──────────────────────────┬─────────────────────────────┬───────────────────────────────┤
│    1. Pre-Authorization  │     2. Gateway Auth         │    3. Settlement & Dispute    │
│    (Merchant Checkout)   │     (Razorpay / Issuer)     │    (Banks & Card Networks)    │
├──────────────────────────┼─────────────────────────────┼───────────────────────────────┤
│ Card-Testing Sentinel    │ Card testing declines,      │ IEEE-CIS: Chargebacks & CNP   │
│ Scope: Precheck decision │ issuer CVV/3DS checks.      │ fraud losses.                 │
│ before order creation.   │                             │ Mendeley: Core banking ledger │
│                          │                             │ balance adjustments.          │
└──────────────────────────┴─────────────────────────────┴───────────────────────────────┘
```

**Final Conclusion**:
Card-Testing Sentinel maintains its specialized, defense-only niche. External datasets confirm our design intuitions regarding velocity and multi-pattern fraud, but cannot replace our causal, merchant-visible data contracts.
