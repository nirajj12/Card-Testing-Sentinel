# Fraud-decision path benchmark

> **Historical benchmark snapshot.** This 2026-08-26 run is retained as
> development evidence but is not the current evaluator-facing latency result.
> The current full-HTTP benchmark is `phase_4c_razorpay_e2e_latency.md`: 500
> sequential prechecks, p50 33.83 ms, p95 110.73 ms, p99 183.19 ms, 0 errors.

Run date: 2026-08-26. Python: CPython 3.11.13. The benchmark is implemented in `scripts/benchmark.py` and uses the real `POST /api/precheck` path with unique deterministic request identifiers and a file-backed temporary SQLite database. It does not use `/api/system`, blind-evaluation rows, or idempotent replay for the headline results.

## Model-only components

Warm-up: 2,000 combined iterations. Measurement: 20,000 iterations per component. Failures: 0.

| Component | p50 ms | p95 ms | p99 ms | Maximum ms | Mean ms | Throughput/s |
|---|---:|---:|---:|---:|---:|---:|
| Prepared 44-feature array → raw model output | 0.001458 | 0.001542 | 0.001625 | 0.066667 | 0.001478 | 676,781.96 |
| Calibration | 0.001167 | 0.001250 | 0.001333 | 0.025834 | 0.001186 | 843,492.25 |
| Frozen policy decision | 0.030625 | 0.033500 | 0.052500 | 33.551292 | 0.034706 | 28,813.64 |
| Combined raw model + calibration + policy | 0.037208 | 0.041041 | 0.062500 | 41.992916 | 0.040913 | 24,442.29 |

## End-to-end live decision path

The measured path includes HTTP/Pydantic validation, HMAC-protected identifiers, state loading, causal feature computation, frozen model and calibration, policy, SQLite persistence, and HTTP serialization. Each traffic class used 20 warm-up requests. Cold application start plus first request was **342.914 ms**.

| Traffic | Measured requests | p50 ms | p95 ms | p99 ms | Maximum ms | Mean ms | Throughput/s | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Normal customer | 250 | 2.642980 | 4.404375 | 4.838084 | 5.878833 | 3.053780 | 327.46 | 0 |
| Burst attack | 320 | 2.957060 | 4.851667 | 5.442625 | 34.638541 | 3.455530 | 289.39 | 0 |
| Mixed | 250 | 2.965500 | 4.904584 | 5.043458 | 5.165250 | 3.412831 | 293.01 | 0 |

All 40 burst sequences reached a real block. Their 160 post-block attempts were independently scored.

## Idempotent retry, labeled separately

500 identical retries of one committed request: p50 **1.527021 ms**, p95 **2.519083 ms**, p99 **2.701709 ms**, maximum **3.392000 ms**, mean **1.703556 ms**, throughput **587.01/s**, failures **0**. Every retry preserved the original decision and state version and caused zero fresh scores.

## Runtime instrumentation

- Artifact-load count: **1**
- Blind-row load count: **0**
- Per-request DataFrame construction count: **0**
- SQLite journal mode: **WAL**
- SQLite `quick_check`: **ok**
- Persisted benchmark requests/events before temporary cleanup: **841 / 675**

The figures describe a single local process on the verification host; they are not production capacity guarantees.
