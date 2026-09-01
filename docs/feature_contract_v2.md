# Feature Contract v2 — `merchant-visible-causal-2`

**39 features. Contract hash `51bfa6604ed0486447ee16a43270f2092f0cac96b3ab0c2f0bad2748e8c28a38`.**

Contract v1 (`configs/features.yaml`, 28 features, hash `84060751…`) is
**unchanged** and still serves the frozen Model v1. v2 is a parallel file with
its own version string and therefore its own hash, so a 39-feature vector can
never be handed to the 28-feature model — `RiskModel.load` refuses on a
contract mismatch, and a test asserts the two hashes differ.

---

## 1. Product boundary

Sentinel is merchant-side, pre-authorization abuse detection: it answers
*before* a Razorpay order is created. Every feature is therefore computable
from what the merchant already has at that moment.

**Allowed:** the current request's own facts (device, session, IP, amount,
optional customer id); this device's earlier committed requests; this device's
earlier **verified** outcomes and completed checkouts; this customer's earlier
behaviour across their devices.

**Forbidden, and structurally impossible here:** the current PAN, CVV or
expiry; the current attempt's issuer, network, authorization result or decline
reason; any future event. The current request sits in `pending` until its own
verified outcome arrives, so it cannot enter its own snapshot.

---

## 2. Preprocessing contract for Phase 10

Feature families and how a trainer should treat them:

| Family | Members | Scale | Notes |
|---|---|---|---|
| Counts | `requests_*`, `failures_*`, `sessions_24h`, `prior_payments_24h`, `recent_failures_24h`, `devices_per_ip_24h`, `active_day_count_7d`, `distinct_card_*`, `card_change_after_decline_7d`, `successful_checkouts_30d`, `customer_distinct_devices_7d`, `customer_failures_7d`, `customer_successful_checkouts_30d` | Standardize | Small integers with long right tails |
| Ratios | `failure_ratio_24h`, `low_amount_ratio_24h`, `ip_rotation_ratio_24h`, `retry_after_decline_ratio_24h`, `failures_per_active_day_7d`, `gap_variability` | Standardize | Already bounded or near-bounded |
| Recency (seconds) | `seconds_since_last_request`, `seconds_since_last_payment`, `seconds_since_last_success`, `session_age_seconds`, `median_gap_between_attempts` | Standardize | Heavy-tailed; a log transform is a reasonable Phase-10 candidate but is **not** applied here |
| Tenure | `device_age_seconds`, `customer_age_seconds` | Standardize | Same tail caveat |
| Amount | `current_amount`, `amount_delta`, `amount_variation_24h` | Standardize | Merchant-dependent scale |
| Binary | `is_new_device`, `customer_id_present` | Leave as 0/1 | Do not standardize the availability flag away |

The v1 pipeline standardizes LR inputs with `StandardScaler`; v2 keeps that
unchanged. **No transformation is applied inside the engine** — the engine
emits raw quantities and every transform belongs to the model pipeline, so
the same numbers serve a tree model and a linear one.

---

## 3. The 39 features

### Carried over from v1, unchanged (27)

| Feature | Entity | Window | Definition |
|---|---|---|---|
| `requests_10s` / `requests_60s` / `requests_5m` / `requests_24h` | device | 10s / 60s / 5m / 24h | Prior committed requests in the window, **plus the current one** |
| `requests_per_ip_5m` | IP | 5m | Prior requests from this IP, plus the current one |
| `devices_per_ip_24h` | IP | 24h | Distinct devices seen on this IP, including the current device |
| `seconds_since_last_request` | device | — | Seconds since this device's previous request; `0` if none |
| `ip_changes_24h` | device | 24h | Distinct IPs seen (including current) minus one |
| `device_age_seconds` | device | lifetime | Seconds since this device's first request; `0` on the first |
| `is_new_device` | device | — | `1` if the device has no prior request |
| `session_age_seconds` | session | — | Seconds since this session's first request |
| `sessions_24h` | device | 24h | Distinct sessions started in the window, including the current |
| `ip_rotation_ratio_24h` | device | 24h | Distinct IPs ÷ requests |
| `prior_payments_24h` | device | 24h | Verified outcomes in the window |
| `recent_failures_24h` | device | 24h | Verified declines in the window |
| `failure_ratio_24h` | device | 24h | Declines ÷ verified outcomes; `0` when none |
| `decline_streak` | device | lifetime | Consecutive verified declines; resets on approval |
| `seconds_since_last_payment` | device | — | Seconds since the last verified outcome |
| `seconds_since_last_success` | device | — | Seconds since the last completed checkout |
| `retry_after_decline_ratio_24h` | device | 24h | Share of declines followed by another attempt within 120s |
| `current_amount` | request | — | The amount on this request |
| `amount_delta` | device | — | Current amount minus the previous request's amount |
| `amount_variation_24h` | device | 24h | Population standard deviation of amounts, including the current |
| `low_amount_ratio_24h` | device | 24h | Share of amounts at or below the near-floor value (5.0) |
| `distinct_card_last4_7d` | device | 7d | Distinct card `last4` across **verified outcomes** |
| `distinct_card_networks_7d` | device | 7d | Distinct card networks across verified outcomes |
| `card_change_after_decline_7d` | device | 7d | Consecutive verified outcomes where a decline is followed by a different `last4` |

### Modified (1)

| v1 | v2 | Why |
|---|---|---|
| `successful_checkouts` (unbounded lifetime) | **`successful_checkouts_30d`** | Blind v1.1 showed `long_warm_up` attackers accumulating a median of 4 completed checkouts and using them to buy their score down permanently — the feature carries coefficient −0.155. Aging the credit to 30 days means a warm-up phase decays instead of paying forever. |

### New in v2 — long-horizon device behaviour (6)

| Feature | Window | Definition | Neutral value |
|---|---|---|---|
| `requests_7d` | 7d | Prior committed requests in the window, plus the current one | — (always ≥ 1) |
| `failures_7d` | 7d | Verified declines in the window | 0 (genuinely none) |
| `active_day_count_7d` | 7d | Distinct UTC calendar days with at least one request, **including today** | — (always ≥ 1) |
| `failures_per_active_day_7d` | 7d | `failures_7d ÷ active_day_count_7d` | 0 |
| `median_gap_between_attempts` | 30d | Median of the inter-arrival gaps across prior requests in the window **plus the current timestamp**. Requires **≥ 2 prior requests** (≥ 2 gaps). | **0.0** |
| `gap_variability` | 30d | Coefficient of variation (population σ ÷ mean) of the same gaps. Requires **≥ 3 gaps**. | **0.0** |

**Why these windows.** Every v1 count capped at 24 hours, so an attacker with
a one-day gap reset every counter — in Blind v1.1 `ultra_patient_tester` had a
median maximum `requests_24h` of **1**. Blind patient gaps ran 1–4 days and
sparse gaps 0.5–2 days, so **7 days covers both**; a full 30-day count suite
would quadruple retention for near-duplicates. 30 days is used only where the
quantity is genuinely about tenure or long-run cadence.

**On the neutral value 0.0 for gap statistics.** A gap of zero is also a
legitimate observation (instant retries), so the neutral value is *not*
self-identifying. It does not need to be: `requests_7d ≤ 2` identifies the
insufficient-history state exactly, and the model has that feature. A distinct
sentinel such as `-1` would have been a stronger signal than the thing it
encodes.

### New in v2 — customer context (5)

| Feature | Entity | Window | Definition | Neutral when absent |
|---|---|---|---|---|
| `customer_id_present` | request | — | `1` if this request carries a customer identity, else `0` | — (it *is* the indicator) |
| `customer_distinct_devices_7d` | customer | 7d | Distinct devices this account used, including the current one | **0.0** |
| `customer_failures_7d` | customer | 7d | Verified declines across all of this account's devices | **0.0** |
| `customer_successful_checkouts_30d` | customer | 30d | Completed checkouts across all of this account's devices | **0.0** |
| `customer_age_seconds` | customer | lifetime | Seconds since this account's first observed request | **0.0** |

---

## 4. Customer-identity missingness

`customer_id` is optional — guest checkout is normal, and roughly 41% of
Dataset v3 requests carry no identity. The encoding must let a model learn
*"information unavailable"*, never *"absent identity is risky"*.

The design: every customer feature takes **0.0** when the identity is absent,
**paired with `customer_id_present = 0`**. That is the standard
missing-indicator encoding — a linear model can fit a compensating offset for
the whole absent segment through the indicator, and a tree model can split on
it. A validation gate asserts both halves: the flag alone must not reach
F1 > 0.65, and every customer feature must be exactly neutral wherever the
flag is 0.

**Honest limitation.** `customer_distinct_devices_7d` is `0` exactly when the
identity is absent and `≥ 1` otherwise, so it is nearly collinear with the
indicator (Spearman 0.972). That is redundancy, not leakage, and it is
reported to Phase 10 rather than hidden.

---

## 5. State, ordering and retention

**Entities.** `DeviceStateV2` (requests, verified outcomes, session starts,
checkout times, decline streak) and `CustomerState` (device digests, failure
timestamps, checkout timestamps, first-seen). A customer is keyed by a one-way
`blake2s` digest — the raw identifier is never stored.

**Ordering.** v1 enforced ordering per device. Customer state spans devices, so
v2 enforces it **per device AND per customer**: an event older than its own
account's committed state is rejected exactly as a device-late event is. Batch
replay feeds events in one global `(timestamp, event_sequence)` order and
sorts on it explicitly rather than trusting row order.

**Retention.** Device history is pruned to 30 days and capped at 512 requests
and 512 payments; customer history is pruned to 30 days and capped at 512
entries; IP history is pruned to 24 hours on write and capped at 4,096 marks;
the request→customer index used to attribute checkouts is FIFO-capped at
50,000. A customer's `first_seen` is retained after its history is pruned —
one timestamp per account — because tenure is the point of the feature.

---

## 6. Explaining a decision without exposing identity

Every feature above can be stated to a reviewer in one sentence that names no
customer, device or IP: *"this account has used six different devices this
week"*, *"this device has failed nine times across four separate days"*,
*"there is no signed-in account for this attempt"*. The engine holds digests
and timestamps, so nothing in an explanation can leak an identity.

---

## 7. Revision history

| Version | Date | Change |
|---|---|---|
| `merchant-visible-causal-1` | earlier phases | 28 features. Unchanged, still serves frozen Model v1. |
| `merchant-visible-causal-2` | 2026-08-31 | 39 features: 27 carried over, `successful_checkouts` → `successful_checkouts_30d`, 6 long-horizon device features, 5 customer-context features. |
