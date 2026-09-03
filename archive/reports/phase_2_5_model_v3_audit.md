# Phase 2.5 Independent Model v3 Audit

**Status:** BLOCKED — ORIGINAL MODEL v3 REJECTED  
**Commit inspected:** `b422c86`  
**Scope:** Dataset v4, Feature Contract v3, Model v3 development methodology  

## Frozen-state verification

The release verifier passed before changes: active runtime `frozen-v2-runtime`,
Model v2, 39 features, Policy v2, consumed Blind v2 verdict `WEAK`, and
`post_blind_tuning: false`. No PBRSS-v1 output or consumption artifact existed.

## Blocking findings

1. The CV unit was customer-then-device rather than the largest correlated
   synthetic actor. Of 803 multi-device training actors, 382 crossed folds.
2. `merchant_relative_velocity_zscore` was only
   `max(0, (requests_5m - 1) / 2)` and used no merchant baseline.
3. `merchant_amount_log_ratio` was only `log(current_amount / 1000)` and used
   no merchant baseline.
4. The 20 counterfactual pairs cycled four scenario combinations and shared
   little beyond merchant identity, making the reported 100% CPOA too easy.
5. Generator declarations did not match emitted behavior: household customers
   were unused, network instability was unused, repeated amounts were redrawn,
   established history was a single token success, and spread actors allocated
   devices that never transacted.
6. Canonical manifests contained a wall-clock timestamp and were not byte
   deterministic.

The mandatory grouped-CV stop condition was invoked. No ablations or retraining
were accepted in Phase 2.5.

## Historical metric correction

The authoritative frozen Blind-v2 family artifact records
`cross_device_weak_guest` REVIEW+ **0.207921 (21/101)** and BLOCK
**0.009901 (1/101)**. Phase 2's “0% Blind-v2 recall” wording was false.

## Decision

The original Model v3 artifact and its Dataset-v4 validation metrics are
rejected development evidence. They must not be compared as an accepted
baseline or used to claim remediation. Phase 2.6 starts again from corrected
data construction, causal features, and actor-safe TRAIN cross-validation.
