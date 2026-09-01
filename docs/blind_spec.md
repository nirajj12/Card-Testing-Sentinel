# Blind Benchmark Specification — v1.1

**Status: frozen before generation. No blind performance number has been observed.**

> **Revision v1.1 (pre-evaluation).** v1.0 was frozen, generated, and then
> failed its own pre-evaluation validation. It was corrected for objective
> generation defects and re-frozen. **No model score, policy decision, recall,
> precision, PR-AUC, FPR or any other blind performance result was observed
> before v1.1 was frozen.** v1.0 was never evaluated and was never consumed.
> See §13.

This document is written *first*, on purpose. Everything about the blind
benchmark — its population, its shifts, its gates and the metrics that will be
reported — is fixed here before the dataset exists and before the frozen model
or policy is ever pointed at it. If any of this were decided after seeing a
result, the benchmark would measure how well I can tune, not how well the
system generalises.

---

## 1. Purpose

Development (Dataset V2) answered *"can this system learn card-testing
behaviour, and at what cost to genuine customers?"* on a benchmark whose
train and validation splits share a generator, a scenario table and a merchant
population.

The blind benchmark answers a different question:

> Does the frozen model and the validation-selected policy still work on
> merchant traffic that was generated from a different specification, in a
> later time window, on merchants and devices they have never seen —
> including merchant archetypes that did not exist during development?

It is deliberately **harder** than validation. It is not designed to be
impossible, and it is explicitly not designed around the system's known
weaknesses (see §4).

---

## 2. What is frozen

Pinned in `artifacts/evaluation/blind_freeze_manifest.json` before this
document was written:

| Artifact | Path |
|---|---|
| Model | `artifacts/model/risk_model.joblib` |
| Model metadata | `artifacts/model/metadata.json` |
| Feature contract | `artifacts/model/feature_contract.json` |
| Policy | `artifacts/policy/operational_policy.json` |
| Training/dataset config | `configs/training.yaml` |
| Policy config | `configs/policy.yaml` |
| Feature config | `configs/features.yaml` |
| Development dataset manifest | `data/generated/development/manifest.json` |

`scripts/freeze_blind_benchmark.py --verify` fails if any of these bytes
change, and a test asserts the same. The model is Logistic Regression C=10
with sigmoid calibration; the policy is evidence-gated with review 0.60 /
block 0.78. **Neither may be modified for the rest of this benchmark's life.**

A second freeze stage pins this specification, `configs/blind.yaml` and the
blind generator source before generation.

---

## 3. Independence rules

The blind generator **may** read:

- the feature contract (`configs/features.yaml`, `features/specification.py`)
- `configs/blind.yaml`
- neutral generation primitives (`ml/primitives.py`, `ml/merchants.py`,
  `ml/scenarios.py`) — merchant profiles, payment instruments, amount and
  outcome mechanics, event writing
- the runtime `FeatureEngine`, for replay only

The blind generator **must not** read:

- the model artifact, its coefficients, or any prediction
- feature importance or the ablation study
- training metrics, validation metrics or threshold sweeps
- policy thresholds, the policy engine, or any policy evaluation
- per-scenario detection or false-positive results from development
- results from any previous blind run

This is enforced two ways: an import-graph test walks the transitive imports
of the blind generator modules and fails if `modeling`, `policy` or the
training/evaluation modules appear; and no threshold constant from the policy
appears anywhere in `configs/blind.yaml`.

**Design consequence.** The shifts in §7 are justified by general threat
reasoning and general merchant behaviour, not by inspecting where the model
underperforms. I already know from Phase 5 that patient testing and device
rotation are the system's weak spots. The blind set includes harder variants
of both — not because they are weak spots, but because a *realistic* adaptive
attacker slows down and spreads out, and that would have been in this
specification regardless. No scenario parameter was chosen by measuring the
model's response to it.

---

## 4. What this benchmark deliberately does NOT do

- It does not target `review_threshold = 0.60` or `block_threshold = 0.78`.
  No cadence, amount or count in `configs/blind.yaml` is derived from a
  threshold, a rule constant, or a feature weight.
- It does not invent implausible merchant archetypes to force failure. The
  three unseen kinds (§6) are ordinary Indian online businesses.
- It does not require the blind distribution to *match* development. Shift is
  the point.
- It sets **no target metric.** There is no pass mark (§11).

---

## 5. Population composition

| Property | Value |
|---|---|
| Blind version | `v1.1` |
| Seed | `90210007` (unrelated to train `20260101`, validation `771103`, merchants `4242001`, training `20260401`) |
| Devices | ~3,000 |
| Splits | one; the blind set is never split |
| Benchmark attack device fraction | 0.20 (`benchmark_attack_device_fraction`) |

**v1.1:** the target is applied at **device** level, because the evaluation is
device level. In v1.0 it was applied when drawing an *actor*; blind attack
actors own 4–9 devices each, so the realized device prevalence came out at
0.291 against a configured 0.20. The manifest now reports the configured
device fraction and the realized device, request and actor fractions
separately, because an actor owns several devices and makes a variable number
of requests — the three genuinely differ and only the device figure is the
target.

**The 0.20 attack fraction is a sampling choice, not a prevalence estimate.**
It exists so all ten attack families carry enough devices to report per-family
recall. Real card testing is a far smaller share of a merchant's traffic. Any
aggregate precision computed on this benchmark is conditional on this
sampling and must be labelled `benchmark_precision`, exactly as in
development. Recall, FPR and the per-scenario breakdowns are the figures that
carry the argument.

---

## 6. Merchant composition

Blind merchants are **all new instances** — no development merchant id or
profile is reused.

- **Known kinds (7), new instances:** `small_ecommerce`, `digital_goods`,
  `subscription`, `electronics`, `education`, `flash_sale`, `travel`, drawn
  with new parameter values from their declared ranges.
- **Unseen kinds (3):** `ticketing_events`, `food_delivery`, `gaming_topups`.

Ten kinds are declared and `count: 11` merchant **instances** are built.
**v1.1: every declared kind is realized** — each kind receives one instance
and the remaining slot is drawn by weight. v1.0 drew all eleven slots by
weight *with replacement*, which left `flash_sale`, `travel` and the unseen
`ticketing_events` with zero merchants and zero devices, and the composition
gate — which only asked for "at least two unseen kinds" — passed anyway.

A scenario that declares `merchant_kinds` is now generated **only** on those
kinds. In v1.0 an empty pool silently fell back to the entire merchant
population, which put `campaign_rush` and `campaign_shadow` on merchants with
ordinary campaign schedules; the campaign-aware analysis would have measured
the wrong thing. Generation now raises `BlindBenchmarkError` instead.

The unseen kinds were chosen because they produce genuinely different
observable behaviour, not because they are exotic:

| Kind | Why it is different |
|---|---|
| `ticketing_events` | Extreme, short campaign bursts (on-sale moments); heavy shared-IP pressure from venue and office networks; mid-to-high tickets |
| `food_delivery` | Very high repeat frequency, small baskets, mobile-heavy so frequent IP churn, low campaign activity |
| `gaming_topups` | Micro-payments in rapid succession, very high returning rate, high session churn — legitimate behaviour that looks structurally like testing |

`merchant_kind` is **not a model feature** (the contract has 28 features and
none of them is categorical merchant identity), so an unseen kind tests
*behavioural* generalisation rather than a missing lookup key. `gaming_topups`
is the sharpest test in the set: it is legitimate traffic whose velocity and
amount profile resembles card testing.

---

## 7. Declared shifts (development → blind)

Fixed before generation. None may be re-tuned after results are seen.

| Axis | Development | Blind | Reason |
|---|---|---|---|
| **Time** | train Jan–Mar 2026, validation Mar–Jun 2026 | **actors start 2026-09-01 + 60 days**; long-horizon families run on past it | Strictly later, with a ~2-month gap after the last validation event |
| **Merchants** | 14 instances, 7 kinds | 11 new instances, 7 known kinds + **3 unseen kinds** | Tests generalisation to new businesses |
| **Amounts** | merchant medians as configured | medians shifted, **variance widened**, new `high` amount style | Real merchant mixes drift; high-ticket genuine retries were absent from development |
| **Timing** | attackers 3s–48h | attackers **slower and more variable**, up to ~4 days; legitimate campaign traffic **burstier** | An adaptive attacker slows down; sale traffic spikes harder |
| **Device history** | 17% attack devices, moderate cold start | **more cold-start legitimate users**, **more device-rotation attackers**, weaker per-device history overall | Both directions reduce available evidence |
| **Outcomes** | merchant approval 0.87–0.98 for a good instrument | **slightly wider and lower** approval bands | Gateway conditions differ across time and merchant mix |
| **Identity** | private + shared IP pools | **more shared-IP legitimate traffic** (venue, campus, office, mobile CGNAT) | Shared egress is the hardest false-positive source |
| **Attack shape** | mostly single-mode families | **alternating, camouflaged and cross-device** families | Adaptive attackers mix modes rather than repeating one |

---

## 8. Legitimate population — harder by design

Ten families. Names differ from development because the behaviour differs;
several share a conceptual ancestor but **no parameter ranges are copied**.

| Family | What it is | Harder than development because |
|---|---|---|
| `cold_start_wave` | First-time buyers, no history | Larger share of the population; a new device has almost no evidence either way |
| `persistent_genuine_failures` | A shopper whose card genuinely keeps failing | Longer, more irregular gaps than development's `repeated_genuine_failures` |
| `unstable_connection_retries` | Retries caused by a flaky connection | Different retry cadence; more session churn |
| `event_venue_burst` | Many genuine buyers behind one venue/office egress | Extreme `devices_per_ip`, concentrated in minutes |
| `campaign_rush` | Genuine sale traffic | Shorter, sharper campaign windows than development |
| `high_value_retry` | Genuine high-ticket purchase retried several times | New: high amounts plus repeated failure, a combination absent from development |
| `dormant_returning_customer` | Established customer returning after a long gap | New: real history, but stale — device age is large while recent activity is nil |
| `multi_session_comparison_shopper` | Genuine comparison shopping across sessions | High `sessions_24h` with genuine intent |
| `mobile_network_churn` | Mobile connectivity causing repeated IP changes | More IP changes than development's `network_switch_customer` |
| `dunning_variant` | Subscription retry schedule | Different retry rhythm from development's `subscription_retry` |

---

## 9. Attack population — adaptive by design

Ten families, all described in terms of *attacker tradecraft*, none derived
from the system's thresholds.

| Family | Tradecraft |
|---|---|
| `ultra_patient_tester` | Very long horizons — days between attempts, longer than any development family |
| `burst_pause_burst` | Alternating: a short burst, a long quiet period, another burst |
| `successful_card_camouflage` | Deliberately mixes genuinely working cards and completed checkouts into the run |
| `merchant_normal_amounts` | Ordinary merchant amounts throughout; no near-minimum tendency at all |
| `moderate_mixed_rotation` | Moderate session and IP rotation — not maximal, obvious churn |
| `campaign_shadow` | Operates inside real merchant campaign windows, hiding in genuine bursts |
| `cross_device_campaign` | One campaign spread across several devices, so each device's own history stays thin |
| `long_warm_up` | An extended genuine-looking phase before testing begins |
| `variable_cadence` | Randomised, irregular gaps to avoid any regular rhythm |
| `sparse_multiday` | Few attempts per day spread across many days, so short-window counters never accumulate |

**Honest note.** `ultra_patient_tester`, `sparse_multiday` and
`cross_device_campaign` attack exactly the limitations recorded at the end of
Phase 5 — long-horizon dilution and cross-device weakness. They are included
because they are realistic adaptive tradecraft that any serious benchmark
must contain, and their parameters come from threat reasoning, not from
probing the model. I expect them to be the hardest families. That expectation
is recorded here, before generation, so it cannot later be presented as a
discovery.

---

## 10. Schema, generation and gates

### Schema

Identical to development, so the same runtime accepts it:

- `raw_events.csv` — `authorization_request` → optional
  `authorization_outcome` → optional `checkout_completion`. Card and payment
  metadata appear **only** on outcome events.
- `labels.csv` — `device_id, actor_id, merchant_id, merchant_kind,
  merchant_origin (known|unseen), population, scenario, label`
- `features.csv` — produced **only** by replaying raw events through the
  runtime `FeatureEngine`; labels joined afterwards on `device_id`.
- `manifest.json` — provenance only. It must contain **no model metric, no
  prediction and no policy metric** at generation time.

All actor-owned identifiers are namespaced `bld_*` and must not collide with
any development identifier.

### Gates (all must pass before evaluation)

**Integrity** — unique event ids; no outcome without a request; no checkout
without an approval; outcome strictly after its request; no card metadata on
any request event; per-device `(timestamp, event_sequence)` never regresses;
deterministic `FeatureEngine` replay; no non-finite feature.

**Independence** — zero device, customer, session, request, event and IP
overlap with train or validation; import-graph test proves the generator
never imports model, policy, training or evaluation code.

**Temporal** — `max(validation timestamp) < min(blind timestamp)`, asserted
hard.

**Leakage** — shuffled-label ROC-AUC near random (≤ 0.60); no single feature
near-perfect (max F1 ≤ 0.85); legitimate and attack distributions still
overlap (coefficient ≥ 0.20 — lower than development's 0.25 because the blind
set is deliberately shifted, but still far from disjoint).

**Composition** — every declared scenario family present with enough devices
and requests; no family dominating its population's requests; **every declared
merchant kind realized**, including every declared *unseen* kind; every
merchant-constrained scenario appearing only on its declared kinds.

**Outcome realism** — the legitimate population's aggregate decline rate must
stay inside `[0.05, 0.40]`, with a warning outside `[0.10, 0.30]`. Individual
families may decline constantly; the *mixture* must still look like a
merchant's book.

### Distribution-shift report (features only)

Before any model is applied, a report compares development-validation against
blind on **features alone** — medians, quantiles, PSI, KS statistic and
overlap coefficient per feature. This inspects no prediction and no metric,
so it does not consume the benchmark.

**The blind set will not be regenerated because it looks hard.** Only a
failed integrity, independence or temporal gate justifies regeneration, and
that requires a spec revision (§12).

---

## 11. Pre-registered evaluation metrics

Fixed now. The report produced in the next phase will contain **all** of
these, whatever they say.

**Model quality** — PR-AUC, ROC-AUC, Brier, log loss, ECE (device-weighted).

**Policy outcomes (device level)** — attack review-or-higher recall; attack
block recall; legitimate review-or-higher rate; legitimate block rate;
attack devices never detected.

**Detection delay** — median and p90 first review attempt; median and p90
first block attempt.

**Per-attack-scenario** — review and block recall, never-detected count,
median detection attempt, for each of the ten families.

**Per-legitimate-scenario** — review and block false-positive rates for each
of the ten families.

**Per-merchant-kind** — review rate, block rate, attack recall; reported
separately for known and unseen merchant kinds.

**Comparison** — every figure above set beside its validation counterpart,
with the delta stated.

### Interpretation rules — also pre-registered

- Report every result, including bad ones.
- **Do not modify the frozen model or policy after seeing any blind metric.**
- Highlight any substantial degradation against validation explicitly.
- Investigate misses descriptively only; do not fix them in this benchmark.
- There is **no pass mark.** No target recall, precision or FPR is defined,
  because defining one creates pressure to reach it. Poor blind results are
  still the result, and are reported as such.
- Aggregate precision is reported as `benchmark_precision` with the
  prevalence caveat attached.

---

## 12. Consumed-benchmark rule and versioning

**The moment any blind model or policy metric is observed, blind v1 is
consumed.**

After that point:

- The frozen model, policy, feature contract, blind spec, blind config and
  blind generator for v1 must not be edited.
- `blind_evaluated` and `consumed` flip to `true` in the freeze manifest, and
  results are written to a version-stamped file — `blind_metrics_v1_1.json`
  for this revision — never a generic mutable name. No `blind_metrics_v1.json`
  exists or will be created, because v1.0 was never evaluated.
- If the model or policy is changed afterwards for any reason, **v1 results
  are not re-run and not overwritten.** A new benchmark is created:
  `blind_version: v2`, a **new seed**, a new spec revision, and its own freeze
  record. v1 results are preserved and reported alongside v2, so the number of
  times the system has seen a "held-out" set is visible rather than hidden.
- If an integrity bug forces an edit *before* evaluation, the spec revision is
  incremented and the freeze re-recorded first.

A test asserts that generation refuses to overwrite a consumed benchmark.

---

## 13. Revision history

| Revision | Date | Change |
|---|---|---|
| v1.0 | 2026-08-31 | Initial specification, frozen before generation. Benchmark generated; **pre-evaluation validation FAILED**. No model or policy was ever run against it; no performance number was observed; never consumed. |
| v1.1 | 2026-08-31 | Generation-correctness revision (see below). |

### v1.0 → v1.1: what changed and why

All four corrections are objective generation defects or naming errors found
by the v1.0 validation run. **None was informed by a model score, a policy
decision, a recall, a precision, a PR-AUC, an FPR or any other blind
performance result — none of which was ever computed.**

**1. Merchant realization.** Merchant kinds were sampled with replacement, so
`flash_sale`, `travel` and the unseen `ticketing_events` archetype had zero
merchants and zero devices. Every declared kind is now realized. The
composition gate was strengthened from "at least two unseen kinds" to "every
declared kind, and every declared unseen kind, is present in the data".

**2. Silent merchant fallback.** A scenario whose declared merchant kinds were
all absent fell back to the whole merchant pool, so `campaign_rush` and
`campaign_shadow` ran on merchants with ordinary campaign schedules. Generation
now raises `BlindBenchmarkError`, and a new gate asserts every constrained
scenario appears only on its declared kinds.

**3. Attack prevalence semantics.** `benchmark_attack_fraction` was applied per
actor while the evaluation is device level; because blind attack actors own
4–9 devices, realized device prevalence was 0.291 against a configured 0.20.
Renamed `benchmark_attack_device_fraction` and applied at device level. The
manifest reports configured device fraction plus realized device, request and
actor fractions separately.

**4. Time semantics.** `window.days` implied the benchmark's span, but it only
bounds when actors *begin*. Renamed `actor_start_window_days`. Long-horizon
families (`ultra_patient_tester`, `sparse_multiday`,
`dormant_returning_customer`) deliberately continue past it and were **not**
truncated — truncating them would delete the behaviour the benchmark exists to
test. The manifest now reports first/last actor start, first/last event and
the realized event span.

**5. Legitimate mixture realism.** v1.0 produced a legitimate decline rate of
0.4179; after the merchant fix it was 0.4384. Both breach the benchmark's own
pre-registered ceiling of 0.40. The correction changed **population share
only** — no merchant approval rate was raised and no family's behaviour was
softened. `persistent_genuine_failures` still draws
`method_validity: [0.15, 0.45]` and still declines ~80% of the time; it simply
stops making 14% of a merchant's genuine attempts.

| Legitimate family | v1.0 weight | v1.1 weight |
|---|---|---|
| `cold_start_wave` | 30 | 30 |
| `event_venue_burst` | 10 | 12 |
| `campaign_rush` | 8 | 5 |
| `high_value_retry` | 5 | 2 |
| `dormant_returning_customer` | 7 | 16 |
| `multi_session_comparison_shopper` | 8 | 14 |
| `mobile_network_churn` | 8 | 8 |
| `persistent_genuine_failures` | 6 | 3 |
| `unstable_connection_retries` | 6 | 3 |
| `dunning_variant` | 4 | 2 |

The corrected aggregate still sits above the comfortable band `[0.10, 0.30]`
and the validator still warns. That warning is left standing rather than tuned
away: blind merchants were deliberately given lower approval bands (§7), and
the campaign families now correctly run on the lowest-approval merchants in
the set, so part of the elevation is a declared shift rather than a mixture
error. Chasing development's 0.2725 would have meant undoing a shift this
specification declared before generation.

### What was NOT changed

The frozen model, the frozen policy, the feature contract, the blind seed
(`90210007`), the merchant seed, the time window, the merchant parameter
ranges, all twenty scenario names, every attack family weight, and every
behavioural range of every family — including the difficult legitimate tails.
