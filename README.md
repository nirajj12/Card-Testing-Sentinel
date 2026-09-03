<div align="center">

<img src="docs/screenshots/sentinel-logo.png" alt="Card-Testing Sentinel" width="340">

# Card-Testing Sentinel

### Stop automated card testing before a Razorpay payment begins.

**Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager**

<br>

<!-- Navigation buttons. When public demo/video are deployed, update destinations below. -->
<a href="https://card-testing-sentinel-production.up.railway.app/"><img src="https://img.shields.io/badge/Live%20Demo-Railway-0066FF?style=for-the-badge&logo=railway&logoColor=white" alt="Live Demo"></a>
<!-- Final submission: add Demo Video badge here once the public video URL is available. -->
<a href="#how-it-works"><img src="https://img.shields.io/badge/Architecture-How%20It%20Works-00AA55?style=for-the-badge" alt="How It Works"></a>
<a href="#evaluation"><img src="https://img.shields.io/badge/Evaluation-Benchmark%20Results-8A2BE2?style=for-the-badge" alt="Evaluation"></a>
<a href="docs/dataset.md"><img src="https://img.shields.io/badge/Dataset-v4.1%20Story-FFA500?style=for-the-badge" alt="Dataset Story"></a>
<a href="reports/README.md"><img src="https://img.shields.io/badge/Evidence-Technical%20Index-333333?style=for-the-badge" alt="Technical Evidence"></a>

<br>

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Razorpay Test Mode](https://img.shields.io/badge/Razorpay-Standard%20Checkout%20(Test%20Mode)-0C2340?style=flat-square&logo=razorpay&logoColor=white)](https://razorpay.com/docs/)
[![Model v3.1](https://img.shields.io/badge/Model-v3.1%20(HistGB%20%2B%20Sigmoid)-orange?style=flat-square)](reports/phase_2_6_model_v3_1_development.md)
[![Tests Passing](https://img.shields.io/badge/Tests-280%20Python%20%7C%2069%20Frontend%20Passed-brightgreen?style=flat-square)](tests/)

</div>

<div align="center">
  <img src="docs/screenshots/sentinel-ui-hero.png" alt="Card-Testing Sentinel — Pre-Authorization Protection Interface" width="95%">
</div>

---

## Project Snapshot

Card-Testing Sentinel is a behavioral risk layer that evaluates checkout risk **before** a Razorpay payment order is created. Instead of waiting for an authorization failure, Sentinel examines trusted history from earlier attempts on a device, converts that history into 44 causal behavioral signals, and decides whether Razorpay order creation should be permitted.

| Item | Current System |
|---|---|
| **Problem** | Automated card testing |
| **Decision point** | Before Razorpay order creation |
| **Development dataset** | Dataset v4.1 |
| **Features** | 44 causal behavioral features |
| **Model** | Model v3.1 — Histogram Gradient Boosting |
| **Policy** | Policy v2 |
| **Attack `REVIEW+` recall under stress** | **96.40%** |
| **Legitimate `REVIEW+` rate under stress** | **20.72%** |
| **Legitimate `BLOCK` rate under stress** | **0.16%** |
| **Stress PR-AUC** | **0.6470** |
| **Final stress verdict** | **`MIXED`** |
| **Production ready** | **`false`** |

---

## Table of Contents

* [Project Snapshot](#project-snapshot)
* [The Card-Testing Problem](#the-card-testing-problem)
* [What Sentinel Does](#what-sentinel-does)
* [How It Works](#how-it-works)
* [Trust & Causality](#trust--causality)
* [Why Synthetic Sequential Data?](#why-synthetic-sequential-data)
* [How the Project Evolved](#how-the-project-evolved)
* [Risk Signals & Current Model](#risk-signals--current-model)
* [Evaluation](#evaluation)
* [What Worked / What Needs Improvement](#what-worked--what-needs-improvement)
* [Merchant Economics](#merchant-economics)
* [Razorpay Integration](#razorpay-integration)
* [Reliability & Verification](#reliability--verification)
* [Limitations](#limitations)
* [Quick Start](#quick-start)
* [Documentation Directory](#documentation-directory)
* [Project Structure](#project-structure)

---

## The Card-Testing Problem

Card testing is an automated attack where fraudsters test batches of stolen card credentials to find valid cards before making larger fraudulent purchases.

Because legitimate shoppers also mistype CVVs or experience temporary bank declines, a merchant cannot block every customer whose payment fails:

```text
Normal Shopper                             Card-Testing Attacker

Card A  →  Payment fails (mistyped CVV)    Card A  →  Payment fails
Card A  →  Same-card retry                 Card B  →  Payment fails
Card A  →  Payment succeeds                Card C  →  Payment fails
                                           Card D  →  Payment fails …
```

> **One failed payment doesn't look suspicious. The sequence does.**

A single payment decline is normal e-commerce friction. But rapid card switching across consecutive declines, session churning, and coordinated bot probing form distinct behavioral sequences. Sentinel intercepts these multi-attempt patterns before the gateway processes the charge.

---

## What Sentinel Does

Sentinel operates as an intelligent gatekeeper positioned between customer checkout and Razorpay order creation:

```mermaid
flowchart TD
    A[Customer Checkout] --> B[Sentinel Precheck]
    B --> C{Risk Decision}
    C -->|ALLOW| D[Create Razorpay Test Mode Order]
    C -->|REVIEW| E[Suppress Order Creation<br/>HTTP 409 Conflict]
    C -->|BLOCK| F[Suppress Order Creation<br/>HTTP 409 Conflict]
    D --> G[Open Razorpay Standard Checkout Modal]
```

### `ALLOW`
Risk score is below the review gate (`< 0.75`). A persisted decision permits creation of a real Razorpay Test Mode order, allowing the customer to enter payment details in the standard Razorpay checkout modal.

### `REVIEW`
Risk score is elevated (`>= 0.75`). Razorpay order creation is **suppressed** (HTTP 409 `payment_order_not_allowed`).

> **Important Boundary:** In this prototype, `REVIEW` is an automated policy state that stops order creation. It does not represent manual Razorpay merchant review, human review queues, SMS OTP, or 3D Secure step-up.

### `BLOCK`
Risk score is very high (`>= 0.90`) **and** accompanied by at least two qualifying behavioral evidence signals (such as consecutive decline streaks and multiple card changes). Order creation is strictly rejected.

---

## How It Works

Sentinel separates the risk decision from the payment itself:

```mermaid
flowchart TD
    subgraph Decision_Phase ["1. Decision Phase (Pre-Authorization)"]
        A[Customer Initiates Checkout] --> B[Sentinel Precheck API]
        C[(Previously Trusted History)] --> B
        B --> D[Compute 44 Causal Features]
        D --> E[Model v3.1 + Sigmoid Calibration]
        E --> F[Policy v2 Evaluation]
        F --> G{Decision}
    end

    subgraph Gateway_Phase ["2. Gateway Phase (Post-Decision)"]
        G -->|ALLOW| H[Create Razorpay Test Mode Order]
        G -->|REVIEW or BLOCK| I[Suppress Order Creation]
        H --> J[Customer Enters Payment in Razorpay Modal]
    end

    subgraph Outcome_Phase ["3. Outcome Verification (Asynchronous)"]
        J --> K[Signed Razorpay Webhook]
        K --> L[HMAC-SHA256 Verification & Deduplication]
        L --> M[Persist Verified Outcome to SQLite WAL]
        M -. Affects future checkouts only .-> C
    end
```

> **Decision first. Payment later. Verified gateway outcomes affect future attempts only.**

Sentinel scores the transaction using only information visible before the payment order exists. Only `ALLOW` decisions reach the gateway. Payment results become trusted history only after the backend verifies Razorpay's signed webhook.

### Example Attack Journey

To understand sequence detection in practice:

* **Attempt 1:** Fresh device → little trusted history → `ALLOW` → Razorpay receives the payment → signed failure becomes trusted history.
* **Attempt 2:** Another card fails → Sentinel now sees repeated failures and historical card switching.
* **Attempt 3:** Failure history + card diversity + velocity raise risk → `REVIEW/BLOCK` → no Razorpay order is created.

*The current card is never available to Sentinel during its own precheck decision; card information can become historical evidence only after a verified Razorpay webhook. This journey is illustrative; exact decisions depend on the device's full behavioral history.*

---

## Trust & Causality

The model is only allowed to use information that really exists before the decision. This prevents target leakage:

| Available to Sentinel at Decision Time | Strictly Forbidden at Decision Time |
|---|---|
| Request velocity across short and long windows | Current PAN, CVV, or card expiry |
| Prior attempt counts and timing intervals | Current card network, type, or issuing bank |
| Device, customer, and session history | Current authorization outcome |
| Previously verified payment failures | Current gateway decline reason |
| Previously verified successful checkouts | Future webhook metadata |
| Historical card diversity (distinct past last4s) | Client-asserted payment status |
| Historical IP and network movement | Metadata learned after the decision |
| Current transaction amount and merchant context | Ground-truth fraud labels |

> **The current payment cannot influence its own current risk decision.**

In standard checkout flows, the frontend receives callback notifications when a payment completes or fails. Sentinel **never** updates trusted payment history from browser callbacks because client requests can be spoofed or manipulated. Only authoritative, HMAC-SHA256-signed Razorpay webhooks (`payment.failed`, `order.paid`) processed by the backend write to live state, affecting *later* attempts only.

---

## Why Synthetic Sequential Data?

Most public fraud datasets describe completed payments and often contain information learned after authorization. Sentinel must decide before Razorpay creates the payment order, and card testing depends on sequences of attempts across devices, sessions, cards, and time. We therefore generated deterministic multi-attempt development data using only information available at the decision point; this remains synthetic evidence and does not replace validation on real production traffic.

**[Full dataset methodology → docs/dataset.md](docs/dataset.md)**

---

## How the Project Evolved

Sentinel was not built by training one model and reporting the best score. Earlier evaluations exposed weaknesses, one attempted redesign was rejected entirely, and the final system was rebuilt around stricter causal and leakage-safe methodology:

| Stage | What Happened | Why It Mattered |
|---|---|---|
| **Model v2 / Dataset v3** | Blind-v2 evaluation was **WEAK** | The linear system struggled with harder behavior and legitimate-customer friction |
| **Model v3 / Dataset v4** | **REJECTED** during audit | The audit found that related users could appear in different validation folds, some features were not grounded in real merchant information, and generation was not fully reproducible |
| **Model v3.1 / Dataset v4.1** | Methodology corrected | Related users and attack groups were kept together across splits, leakage-prone features were removed, and the model was retrained using 44 causal behavioral features |
| **PBRSS-v1** | Shifted stress result was **MIXED** | Attack coverage remained high (96.40%), but REVIEW friction (20.72%) and calibration degraded |

**The final version is better because the methodology became stricter—not because weaker results were deleted.**

* **[Full dataset evolution → docs/dataset.md](docs/dataset.md)**
* **[Full evaluation journey → reports/README.md](reports/README.md)**

---

## Risk Signals & Current Model

Sentinel uses **44 causal behavioral features** covering velocity, verified failure history, historical card diversity, identity continuity, session behavior, network behavior, timing patterns, and amount behavior:

```text
Trusted History → 44 Causal Features → Model v3.1 (Histogram Gradient Boosting) → Sigmoid Calibration → Policy v2 → ALLOW / REVIEW / BLOCK
```

**13 candidate models were evaluated using 5-fold actor-safe grouped cross-validation on 8,500 training devices.** Related users and attack groups were kept in the same fold so the model could not appear better by seeing similar actors during both training and validation. scikit-learn Histogram Gradient Boosting (`hist_gb_2`) won with out-of-fold PR-AUC of **0.9384** and ROC-AUC of **0.9790**. Sigmoid calibration (Platt scaling) reduced Expected Calibration Error from 0.0554 to 0.0147 with zero PR-AUC ranking loss.

**[Feature contract specification → configs/features_v3_1.yaml](configs/features_v3_1.yaml)**

---

## Evaluation

Sentinel was evaluated first on a held-out development validation split, and then on a frozen, deliberately shifted stress benchmark.

> **Definition:** `REVIEW+` indicates total intervention coverage: the proportion of devices that received either a `REVIEW` or a `BLOCK` decision.

### Development Validation vs. Shifted Stress Benchmark

| Metric | Held-Out Development (v4.1) | Shifted Stress Benchmark (PBRSS-v1) |
|---|---:|---:|
| **Evaluation Population** | 3,500 devices (630 attack / 2,870 legitimate) | 5,000 devices (1,250 attack / 3,750 legitimate) |
| **Benchmark Attack Prevalence** | 18.0% | 25.0% |
| **Attack `REVIEW+` Recall** | **93.49%** (589 / 630) | **96.40%** (1,205 / 1,250) |
| **Attack `BLOCK` Recall** | **67.46%** (425 / 630) | **59.12%** (739 / 1,250) |
| **Legitimate `REVIEW+` Friction** | **3.14%** (90 / 2,870) | **20.72%** (777 / 3,750) |
| **Legitimate `BLOCK` Rate** | **0.14%** (4 / 2,870) | **0.16%** (6 / 3,750) |
| **Ordinary Checkout Review Rate** | ~3.0% | **25.30%** (759 / 3,000) |
| **PR-AUC (Device-Weighted)** | **0.9169** | **0.6470** |
| **Expected Calibration Error (ECE)** | **0.0214** | **0.1407** |
| **Benchmark Precision (`REVIEW+`)** | — | **60.80%** (1,205 / 1,982) |
| **Benchmark Precision (`BLOCK`)** | — | **99.19%** (739 / 745) |
| **Counterfactual Pair Ordering (CPOA)** | **100.0% (20 / 20 pairs)** | — |

> **Benchmark Precision Note:** The 99.19% BLOCK precision and 60.80% REVIEW+ precision are device-level, policy-level, and conditional on the synthetic benchmark's 25% attack prevalence. They are not expected production precision or a production guarantee.

> **Evaluation Discipline:** Model v3.1, the 44-feature contract, calibration, and Policy v2 were frozen before PBRSS-v1. The shifted benchmark was scored once, and no post-stress model, feature, calibration, or policy tuning was performed.

### Evaluation Charts

<div align="center">
  <table>
    <tr>
      <td align="center" width="50%">
        <img src="docs/figures/policy_outcomes_model_v3_1.png" alt="Policy Outcomes Under Model v3.1" width="100%"><br>
        <b>Figure 1: Policy v2 Outcomes on Development Validation</b><br>
        <i>Strong separation in development: 93.49% attack recall vs. 3.14% legitimate review friction.</i>
      </td>
      <td align="center" width="50%">
        <img src="artifacts/figures/pbrss_detection_delay.png" alt="Detection Delay Across Attempts" width="100%"><br>
        <b>Figure 2: Cumulative Detection Across Sequential Attempts (PBRSS-v1)</b><br>
        <i>Attack detection accumulates rapidly: 92.16% of attack devices received REVIEW/BLOCK by attempt 3.</i>
      </td>
    </tr>
  </table>
</div>

---

## What Worked / What Needs Improvement

Sentinel's final evaluation verdict is **`MIXED`**. Disclosing both strengths and operational limitations is essential:

### What Worked
* **Attack coverage survived distribution shift.**
* **Most multi-attempt attacks were detected by the third attempt.**
* **Very few legitimate shoppers were hard-blocked.**
* **Counterfactual tests provide evidence that risk moves in the intended direction when declared behavioral factors change.**
* **The pre-order Razorpay boundary worked end-to-end.**

### What Needs Improvement
* **Excessive Review Friction Under Shift:** Legitimate customer review rate rose from 3.14% in development to 20.72% under stress (and 25.30% in ordinary checkout). This represents substantial customer friction and is too high for direct production checkout without automated step-up mechanisms.
* **Calibration Degradation:** ECE rose from 0.0214 to 0.1407 under distribution shift as predicted probabilities drifted upward.
* **Distributed Single-Attempt Botnets:** Attackers rotating distinct devices on every attempt avoided the multi-failure history required for hard blocks.
* **No Live Production Traffic:** The detector was evaluated on synthetic distributions; it has not been validated on live Razorpay production gateway traffic.
* **No Step-Up Challenge Flow:** The prototype suppresses order creation on `REVIEW`; an automated step-up workflow (such as SMS OTP or 3DS) is not currently implemented.

> **Final Shifted-Stress Verdict:** **`MIXED`**<br>
> **Production Ready:** **`false`**

---

## Merchant Economics

High fraud recall alone is insufficient: **a fraud detector is economically harmful if legitimate-customer friction costs more than the fraud losses it prevents**.

| Operating Scenario | Assumed Attack Prevalence | Modeled Result |
|---|:---:|---|
| **Quiet Traffic** | 0.10% | **Negative modeled value:** 20.56% review friction costs more than prevented fraud |
| **Active Campaign** | 2.00% | **Positive modeled value:** Fraud prevention savings absorb review friction costs |
| **Higher-Loss Merchant** | 0.50% | **Positive modeled value:** High fraud severity lowers break-even prevalence to 0.24% |

> **High attack recall can still be economically harmful if legitimate-customer friction costs more than the fraud losses prevented.**

*Disclaimer: All financial figures are hypothetical merchant scenario parameters designed to evaluate economic trade-offs. They are not Razorpay financial data, observed merchant savings, or guarantees.*

**[Full economic formulas and derivations → reports/phase_4d_economic_scenario_analysis.md](reports/phase_4d_economic_scenario_analysis.md)**

---

## Razorpay Integration

Sentinel integrates directly with the Razorpay API:

- [x] **Pre-Authorization Gating:** Only an `ALLOW` decision permits the backend to call `POST https://api.razorpay.com/v1/orders`.
- [x] **Order Suppression:** `REVIEW` and `BLOCK` decisions suppress order creation and return HTTP 409 (`payment_order_not_allowed`).
- [x] **Standard Checkout Modal:** Allowed orders pass `order_id` to the frontend, which launches the standard Razorpay checkout modal.
- [x] **HMAC-SHA256 Signature Verification:** Webhooks delivered to `/api/webhooks/razorpay` are verified over the raw request payload using constant-time comparison (`hmac.compare_digest`).
- [x] **Correlation & Deduplication:** Payments are linked to orders and original Sentinel precheck requests. Exact duplicate webhooks are processed idempotently.
- [x] **Lifecycle Monotonicity:** Stale gateway events cannot move a terminal payment status backward.
- [x] **Authoritative Gateway Boundary:** Browser callbacks are treated as non-authoritative; only signed webhooks update trusted history.

*Tested strictly in Razorpay Test Mode; no real payment cards were charged.*

**[Verified lifecycle evidence → reports/phase_5b_1_real_razorpay_failure_lifecycle.md](reports/phase_5b_1_real_razorpay_failure_lifecycle.md)**

---

## Reliability & Verification

### Test Suite & Cryptographic Verifiers
* **280 default Python tests passed.**
* **262 expensive deterministic dataset-regeneration tests are maintained separately.**
* **69 frontend tests passed.**
* Both release and runtime v3.1 verifiers passed.

### Local HTTP Benchmark Latency
Sequential benchmarking across 500 local loopback `/api/precheck` HTTP requests (FastAPI + Pydantic + FeatureEngineV3 + Model v3.1 + SQLite WAL):
* **Median (p50):** **33.83 ms** · **p95:** **110.73 ms** · **p99:** **183.19 ms** · **Errors:** **0 / 500 (0.0%)**<br>
*(Local benchmark measurement; not a production SLA guarantee).*

### Security & Architecture Safeguards
* **Trusted History Boundary:** Unsigned direct history-injection routes were removed; live payment history can only be updated through verified gateway events.
* **Constant-Time Verification:** Webhook signatures checked with `hmac.compare_digest` to prevent timing attacks.
* **Restart Persistence:** Persisted counters and state versions reconstruct correctly from SQLite WAL after server restarts.

---

## Limitations

Card-Testing Sentinel is an **evaluated Buildathon prototype**, not a certified production fraud platform:

1. **Synthetic Evidence Only:** All machine learning performance metrics are derived from synthetic datasets and benchmarks; no live Razorpay production gateway traffic was evaluated.
2. **Elevated Review Friction Under Distribution Shift:** Legitimate customer review friction reached 20.72% under shifted stress (25.30% in ordinary checkout).
3. **Probability Calibration Drift:** Expected Calibration Error increased from 0.0214 to 0.1407 under distribution shift.
4. **No Step-Up Challenge Flow:** The prototype suppresses order creation on `REVIEW`; an automated challenge mechanism (such as 3DS or SMS OTP) is not implemented.
5. **Gateway Scope:** Razorpay integration is verified in **Test Mode** only; no real payment cards were processed.
6. **Prototype Concurrency Architecture:** Persistence uses local SQLite WAL mode and an in-memory transition lock, suitable for single-instance evaluation but not distributed horizontal scaling.
7. **No Production Multi-Tenancy:** Production authentication, merchant tenant isolation, distributed rate-limiting, and drift monitoring are not implemented.
8. **Final System Status:** **`production_ready=false`** under declared evaluation governance.

---

## Quick Start

> **Live Deployment:** Explore the active demo at **[card-testing-sentinel-production.up.railway.app](https://card-testing-sentinel-production.up.railway.app/)**.

### Prerequisites
* Python 3.11+
* Node.js 22.13.1+ (or LTS)
* npm 10+

### Local Setup

```bash
# 1. Clone repository
git clone https://github.com/nirajj12/Card-Testing-Sentinel.git
cd Card-Testing-Sentinel

# 2. Set up Python virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install pinned Python dependencies
python -m pip install --upgrade pip==26.2.1 setuptools==84.0.0
python -m pip install --no-deps -r requirements-runtime.lock
python -m pip install --no-deps -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .

# 4. Install frontend dependencies and build React bundle
npm ci
npm run build

# 5. Set local secret and start server
export CTS_HMAC_SECRET='change-this-to-a-long-random-secret-for-local-use'
python scripts/run_app.py
```

Open **`http://127.0.0.1:8000`** in your browser to explore the interactive Sentinel interface.

*(Optional)* For real Razorpay Test Mode checkout, provide your test credentials:
```bash
export RAZORPAY_KEY_ID='rzp_test_...'
export RAZORPAY_KEY_SECRET='...'
export RAZORPAY_WEBHOOK_SECRET='...'
```

<details>
<summary><strong>Docker setup</strong></summary>

```bash
docker build -t card-testing-sentinel .
docker run --rm -p 8000:8000 \
  -e CTS_HMAC_SECRET='change-this-to-a-long-random-secret-for-local-use' \
  -v card_testing_state:/app/data/runtime \
  card-testing-sentinel
```

</details>

### Run Tests & Verifiers

```bash
# Run unit and integration test suite
pytest

# Run frontend tests
npm test

# Run cryptographic verifiers
python scripts/verify_release.py
python scripts/verify_runtime_v3_1.py
```

---

## Documentation Directory

| Document | Purpose |
|---|---|
| **[Dataset & Feature Methodology](docs/dataset.md)** | Why synthetic data was necessary, Dataset v4.1 design, `leakage_group_id` partition safety, and 44 causal feature families. |
| **[Evaluation & Technical Evidence](reports/README.md)** | The complete evaluation narrative: Model v2 Blind failure, rejected Model v3, Model v3.1 results, PBRSS stress benchmark, and full report index. |
| **[System Architecture](docs/architecture.md)** | Pre-authorization decision boundary, payment state machine, and webhook verification. |
| **[API Specification](docs/api.md)** | Detailed endpoint request/response contracts, status codes, and error formats. |
| **[External Dataset Assessment](docs/external_card_testing_dataset_assessment.md)** | Analysis of why common public fraud datasets are poorly suited to pre-authorization card testing. |

---

## Project Structure

```text
Card-Testing-Sentinel/
├── frontend/                     React 18 TypeScript application
├── src/card_testing_sentinel/    Core runtime (FastAPI, feature engine, ML, policy)
│   ├── api/                      REST endpoints and webhook routes
│   ├── features/                 Causal feature extractors (v3.1)
│   ├── ml/                       Model inference and calibration
│   ├── policy/                   Policy v2 decision logic
│   └── service.py                RiskService orchestration & persistence
├── configs/                      Versioned contracts (features, datasets, runtime)
├── artifacts/                    Committed frozen models, figures, and manifests
├── pipelines/                    Deterministic dataset and training generators
├── scripts/                      Release verifiers, audits, and latency benchmarks
├── tests/                        Python unit, integration, and security test suites
├── docs/                         Tier-2 architecture, dataset, and API documentation
│   ├── dataset.md                Authoritative Final Dataset Story
│   ├── architecture.md           Decision boundary and state model
│   └── api.md                    REST API specifications
├── reports/                      Tier-2 Final Evaluation Story and Technical Evidence Index
│   └── README.md                 Evaluation journey and complete report directory
└── archive/                      Quarantined historical experiments (rejected Model v3)
```

---

## Conclusion

Card-Testing Sentinel demonstrates a straightforward payment-risk principle:

> **Make the risk decision before Razorpay order creation, learn only from authoritative gateway outcomes after payment lifecycle completion, and evaluate both fraud detection and legitimate-customer cost under distribution shift.**

---

## Author

**Niraj Kumar**<br>
[GitHub](https://github.com/nirajj12) · [LinkedIn](https://www.linkedin.com/in/niraj-kumar-8255111b8/)
