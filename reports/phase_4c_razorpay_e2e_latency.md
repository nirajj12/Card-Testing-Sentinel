# Phase 4C — Razorpay Test Mode E2E and Runtime Latency Verification

## 1. Status

Phase 4C is complete. The frozen Model v3.1 runtime was exercised through the live local HTTP API, including a real Razorpay Test Mode order creation, local payment-signature verification, signed webhook lifecycle simulation, restart persistence, and a 500-request local latency benchmark.

## 2. Starting point

- Starting commit: `b9407af4f1f0ff30c4416445d6de9e35bcba0c8f`
- Initial working tree: clean
- Application endpoint: local `http://127.0.0.1:8000`
- Storage: SQLite in WAL mode; integrity check reported `ok`

## 3. Active runtime identity

The live `/api/system` response and both repository verifiers agreed on the active system:

- Runtime: `postblind-v3.1-prototype-runtime`
- Model: `model-v3.1`
- Feature count: `44`
- Policy: `validation-selected-v2` / Policy v2
- PBRSS version: `pbrss-v1`
- PBRSS result: `MIXED`
- Stage: `evaluated_prototype_candidate`
- `pbrss_rescored`: `false`
- `production_ready`: `false`

## 4. Razorpay environment and credential audit

The integration used Razorpay Test Mode. `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` were present. The key ID had the required `rzp_test_` prefix. No credential value was printed, written to an artifact, or committed.

## 5. ALLOW path — real Razorpay Test Mode order

Request `phase4c-allow-876897ec7ac6` produced:

- Decision: `allow`
- Risk score: `0.014738376885245848`
- Rule score: `0`
- Rule-reason count: `0`
- Razorpay Test Mode order: `order_TXSnhygTpmSIoK`
- Amount: `10000` minor units
- Currency: `INR`
- `test_mode`: `true`

The order was created through Razorpay's Test Mode API. No live-money transaction and no real captured payment occurred.

## 6. REVIEW suppression

Request `phase4c-review-7d6fef6fc0-r1` produced `review` with risk score `0.824146163249112`. An exact precheck retry remained `review` and was reported as idempotent. The order endpoint returned HTTP `409` with `payment_order_not_allowed`, so no Razorpay order was created.

## 7. BLOCK suppression

A deterministic, non-PBRSS sequence reached `block` on request `phase4c-block-7d6fde765f-r3`:

- Attempt 1: `allow`, risk `0.008649243582492533`, rule score `0`
- Attempt 2: `allow`, risk `0.009206199704521927`, rule score `0`
- Attempt 3: `block`, risk `0.9259715769692496`, rule score `3`

An exact retry remained `block` and was idempotent. The order endpoint returned HTTP `409` with `payment_order_not_allowed`, preventing remote order creation.

## 8. Order idempotency

Repeating the accepted ALLOW order request returned the same Razorpay order ID, `order_TXSnhygTpmSIoK`, with `idempotent_replay: true`. This demonstrates that the local repository prevents duplicate remote order creation for an identical accepted request.

## 9. Payment-signature verification

Using the real Test Mode order ID and the configured Test Mode secret, a deterministic local HMAC fixture was submitted to the verification endpoint:

- Valid signature: HTTP `200`, `verified: true`, state `signature_verified`
- Duplicate valid submission: HTTP `200`, idempotent response
- Invalid signature: HTTP `400`, `invalid_payment_signature`

This verifies the signature mechanism. It does not claim that Razorpay captured a real payment.

## 10. Webhook verification and delivery idempotency

Signed Test Mode webhook fixtures were generated locally using the configured webhook secret. These were not externally delivered by Razorpay.

- Invalid webhook signature: HTTP `400`
- `payment.authorized`: accepted
- `payment.captured`: accepted; approved history recorded
- `order.paid`: accepted
- Duplicate `order.paid` delivery: accepted with `duplicate: true`

The raw request body is authenticated with HMAC and delivery IDs are deduplicated.

## 11. Lifecycle monotonicity

The exercised state progression was `signature_verified` → `authorized` → `captured` → `paid`. A stale `authorized` event submitted after `captured` did not regress the stored state. The `captured` event recorded an approved historical outcome for subsequent feature calculation.

## 12. Restart persistence

The backend was stopped and restarted. After restart, `/api/system` again reported the frozen v3.1 runtime, a healthy SQLite WAL database, 5 stored requests, and 4 stored events before a new call.

Request `phase4c-postrestart-876897ec7ac6` remained `allow`, observed state version `4`, and saw four timeline events. Read-only SQLite evidence for this request included `successful_checkouts_30d: 1.0`, `requests_5m: 2`, and `sessions_24h: 2`, confirming that previously approved checkout context was rebuilt from persisted state.

## 13. Latency benchmark methodology

The benchmark called the real local `/api/precheck` HTTP endpoint. It first checked `/api/system` and refused to run unless the active runtime was Model v3.1 with 44 features, Policy v2, and `production_ready: false`.

Timing used client-side `time.perf_counter_ns()` around sequential HTTP round trips. Every request used a unique, deterministic, synthetic non-PBRSS device/customer fixture. The measurement therefore includes local HTTP handling, framework work, feature construction, model inference, policy evaluation, and the local SQLite path. It excludes frontend rendering and Razorpay order/webhook network calls.

## 14. Benchmark environment

- OS: `macOS-26.5.2-arm64-arm-64bit`
- CPU architecture: `arm`
- Python: `3.11.13`
- Mode: `local_non_production`
- Warm-up requests: `50`
- Measured requests: `500`
- Successful measurements: `500`
- Errors: `0`

## 15. Benchmark results

| Statistic | Latency (ms) |
|---|---:|
| Mean | 45.91956508 |
| Median / p50 | 33.83089600 |
| p90 | 87.77998690 |
| p95 | 110.73206905 |
| p99 | 183.18813250 |
| Minimum | 7.91300000 |
| Maximum | 467.01175000 |
| Standard deviation | 43.64273742 |

Machine-readable evidence is stored in `artifacts/runtime/phase_4c_precheck_latency.json`.

## 16. Verification and test evidence

- Historical frozen-release verifier: passed
- Model v3.1 runtime verifier: passed
- Targeted Phase 4C suite: `24 passed`, `0 failed`
- Targeted scope: active v3.1 runtime and parity, restart behavior, Razorpay ALLOW/REVIEW/BLOCK controls, idempotency, signatures, webhook authentication and monotonic state, plus the benchmark helper
- Full repository suite: `249 passed`, `262 deselected`, `1 warning`, `89%` coverage
- Non-blocking warning: joblib could not discover physical-core count and used logical cores
- New-code lint check: passed

## 17. Limitations and interpretation

- RAZORPAY TEST MODE ONLY
- MODEL v3.1 REMAINS FROZEN
- NO PBRSS RESCORING
- NO RETRAINING
- NO RECALIBRATION
- NO POLICY CHANGES
- LOCAL LATENCY IS NOT PRODUCTION LATENCY
- `production_ready` remains `false`

The benchmark is reproducible local engineering evidence, not an availability, throughput, tail-latency, or production SLO claim. Webhook events were correctly signed local simulations, not proof of external Razorpay delivery. This phase validates integration mechanics and runtime behavior without changing the model, features, policy, evaluation evidence, or readiness classification.
