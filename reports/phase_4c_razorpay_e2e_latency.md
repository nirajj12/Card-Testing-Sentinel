# Razorpay Integration & Runtime Latency Report

## Goal

Verify end-to-end integration between Card-Testing Sentinel and Razorpay Standard Checkout in Test Mode, validate order creation gating, test webhook lifecycle persistence, and benchmark local `/api/precheck` HTTP latency.

## Setup

- **Gateway Environment:** Razorpay Standard Checkout (Test Mode)
- **Active Runtime:** `postblind-v3.1-prototype-runtime` (Model v3.1, 44 features, Policy v2)
- **Host System:** macOS arm64, Python 3.11.13
- **Database:** SQLite WAL mode with durable state persistence
- **Verification Constraints:** Real Test Mode credentials; zero secrets logged or committed.

## What I Tested

- **ALLOW Path Order Creation:** Verified that an ALLOW decision creates a real Razorpay Test Mode order.
- **REVIEW and BLOCK Order Suppression:** Verified that REVIEW and BLOCK decisions suppress order creation and return HTTP 409 `payment_order_not_allowed`.
- **Order Idempotency:** Re-executed an identical accepted precheck to verify that the existing Razorpay order ID is returned with `idempotent_replay: true`.
- **Payment Signature Verification:** Tested HMAC-SHA256 signature verification on payment outcomes using the configured key secret.
- **Webhook Processing & Lifecycle Monotonicity:** Tested local delivery of signed `payment.authorized`, `payment.captured`, and `order.paid` events, verifying that stale events cannot regress payment status.
- **Persistence Across Restart:** Stopped and restarted the backend service to verify that SQLite WAL recovers state versions and historical feature context.
- **Local Precheck HTTP Latency:** Benchmarked sequential `/api/precheck` request latency across 500 requests on a local HTTP client.

## Results

### 1. Gateway Decision Gating

| Decision | Test Request ID | Model Score | Rule Score | Razorpay Order Outcome |
| :--- | :--- | ---:| ---:| :--- |
| **ALLOW** | `phase4c-allow-876897ec7ac6` | 0.014738 | 0 | Created `order_TXSnhygTpmSIoK` (10000 INR) |
| **REVIEW** | `phase4c-review-7d6fef6fc0-r1` | 0.824146 | 0 | Suppressed (HTTP 409 `payment_order_not_allowed`) |
| **BLOCK** | `phase4c-block-7d6fde765f-r3` | 0.925972 | 3 | Suppressed (HTTP 409 `payment_order_not_allowed`) |

In the multi-attempt attack probe, attempts 1 and 2 returned `allow` (scores 0.008649 and 0.009206), while attempt 3 hit behavioral review thresholds and returned `block` with rule score 3.

### 2. Signature and Webhook Verification

- **Payment Signature:** Valid HMAC signatures returned HTTP 200 (`verified: true`); invalid signatures returned HTTP 400 (`invalid_payment_signature`). Duplicate valid submissions returned idempotent 200 responses.
- **Webhook Delivery:** Signed `payment.captured` and `order.paid` events were authenticated and processed. Duplicate webhook deliveries were acknowledged with `duplicate: true`.
- **Monotonic Progression:** Stored state transitioned sequentially (`signature_verified` → `authorized` → `captured` → `paid`). Stale `authorized` events received after `captured` were ignored.

### 3. Persistence and State Reconstruction

After stopping and restarting the server:
- `/api/system` reported healthy SQLite WAL mode with 5 stored requests and 4 events.
- Subsequent request `phase4c-postrestart-876897ec7ac6` observed state version 4.
- Reconstructed feature context correctly retained `successful_checkouts_30d = 1.0`, `requests_5m = 2`, and `sessions_24h = 2`.

### 4. Local Precheck Latency Benchmark (500 Requests)

The measured path includes HTTP serialization, Pydantic validation, HMAC tokenization, state loading, 44-feature computation, model scoring, policy evaluation, and SQLite WAL persistence.

| Metric | Latency |
| :--- | ---:|
| **Mean** | 45.92 ms |
| **Median (p50)** | **33.83 ms** |
| **p90** | 87.78 ms |
| **p95** | **110.73 ms** |
| **p99** | 183.19 ms |
| **Minimum** | 7.91 ms |
| **Maximum** | 467.01 ms |
| **Standard Deviation** | 43.64 ms |
| **Errors / Failures** | 0 / 500 |

*Data recorded in `artifacts/runtime/phase_4c_precheck_latency.json`.*

### 5. Automated Tests and Verifiers

- **Targeted Integration Tests:** 24 passed, 0 failed.
- **Full Python Test Suite:** 249 passed, 262 slow deselected, 0 failed, 89% coverage.
- **Release Verifier (`verify_release.py`):** Passed.
- **Runtime Verifier (`verify_runtime_v3_1.py`):** Passed.

## What the Results Mean

1. **Robust Gating:** Order creation is strictly conditioned on ALLOW decisions. Fraudulent or suspicious sessions cannot obtain Razorpay orders.
2. **Safe Idempotency:** Duplicate checkout clicks do not create duplicate Razorpay orders or corrupt backend behavioral counters.
3. **Sub-100ms Decision Speed:** Median local response time of 33.83 ms demonstrates that causal feature computation and tree-model scoring add minimal latency to checkout.

## Limitations

- **Local Host Benchmark:** Latency figures reflect a single local process on macOS arm64 without network hops or database contention. They do not constitute production SLA guarantees.
- **Razorpay Test Mode:** Real card networks were not charged; all gateway interactions used test keys.
- **Prototype Status:** High attack detection is accompanied by the known 20.72% legitimate review friction from PBRSS-v1; `production_ready` remains `false`.

## Reproducibility

- **Benchmark Script:**
  ```bash
  python scripts/benchmark_precheck_latency.py
  ```
- **Benchmark Artifact:** `artifacts/runtime/phase_4c_precheck_latency.json`
- **Verification Commands:**
  ```bash
  python scripts/verify_release.py
  python scripts/verify_runtime_v3_1.py
  ```
