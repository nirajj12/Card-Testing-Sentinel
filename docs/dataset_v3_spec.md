# Dataset v3 Specification — development-v3

**Status: written before the generator, frozen before generation.**

Dataset v3 is intended to be the **final development dataset**. It replaces
Dataset V2 as the training and validation corpus for Model v2. Dataset V2,
Model v1, Policy v1 and Blind v1.1 are preserved unchanged; v3 lives in its
own config, its own module namespace, its own seeds and its own output
directory.

---

## 1. Why v3 exists

The Phase 7B blind evaluation and the Phase-8 design audit established that
Model v1's failures are a **feature and state-representation limitation**, not
a model-capacity limitation. The highest-value Model v2 features are
customer-scoped and long-horizon. Dataset V2 cannot exercise them:

```
customers = [f"cus_{actor_id}_{index}" for index in range(behavior.customer_pool)]
```

Every V2 customer id is namespaced to a single actor, an actor runs once
inside one window, and `customer_pool` puts *several customers on one device*
— the opposite of what cross-device features need. On V2 every customer
feature would be degenerate, and an ablation would "prove" the idea worthless
for reasons that belong to the generator.

v3 fixes that, plus the objective generator defects found in Phases 6-7.

---

## 2. What is preserved, exactly

The causal pipeline is unchanged. Nothing writes a feature value directly and
no branch anywhere keys on the label:

```
scenario intent
  -> latent behavioural parameter ranges (per actor, drawn uniformly)
    -> raw lifecycle events
      -> FeatureEngine replay
        -> labels joined afterwards on device_id
```

Also preserved: outcome resolution *by cause* (an instrument decline poisons
the instrument, a network failure does not); campaigns as a property of the
merchant and the clock, never of the actor; merchant kind as a description of
a business, never a risk level; card metadata only on verified outcomes,
never on a request.

**Not touched by this phase:** `configs/training.yaml`, `ml/generator.py`,
`data/generated/development/`, the frozen model, the frozen policy, the
production `FeatureEngine`, and every file inside the Blind v1.1 freeze
bundle (`ml/merchants.py`, `ml/scenarios.py`, `ml/primitives.py`,
`ml/blind_generator.py`, `pipelines/generate_blind.py`). v3 imports the
neutral mechanics from those modules read-only; it never edits them, so
`scripts/freeze_blind_benchmark.py --verify` must still pass afterwards.

---

## 3. Architecture

Three nested entities replace V2's single flat "actor":

| Entity | Lifetime | Owns |
|---|---|---|
| **Customer** | the whole window; joins once, persists | devices, home IPs, login propensity, merchant affinity |
| **Actor** | one behavioural role bound to one customer | a scenario, its latent parameters |
| **Episode** | one visit: minutes to hours | attempts at one merchant, at one time |

An actor emits **several episodes separated by days or weeks**. Tenure,
long-horizon counts and cross-device linkage therefore *emerge from generated
events* — they are never written as attributes.

A customer's `joined_at` falls inside the first fraction of the window, so a
customer that joins early accumulates real history before its later episodes.
No pre-window synthetic "prior success count" is injected anywhere.

---

## 4. Customer identity and `customer_id` presence

Development target, a **synthetic modelling assumption and not a claimed
industry statistic**:

```
~65% of requests carry customer_id
~35% guest / customer_id absent
```

Presence is decided **per episode**, not per request: a shopper who is logged
in stays logged in for that visit. The per-episode probability is

```
clip(customer.login_propensity * scenario.login_multiplier * merchant.login_affinity, 0, 1)
```

so it is shaped by who the customer is, what they are doing, and where.
Guest scenarios force it to zero.

**`customer_id_present` must not become a label shortcut.** Attack families
deliberately span the full range: `patient_tester_weeks` and
`cross_device_campaign` mostly use accounts (that is how a real campaign
reuses a compromised or throwaway login), while `fast_burst` and
`session_churn` mostly do not. A gate (Section 8) fails generation if
presence separates the populations.

---

## 5. Legitimate population

| Family | What it is | Why it is here |
|---|---|---|
| `returning_customer_multi_episode` | An established shopper across several visits over weeks | The tenure baseline; the population's centre of mass |
| `cold_start_guest` | First-time guest checkout, no account | The largest source of "no history either way" |
| `logged_in_new_customer` | New account, one or two visits | Separates "new" from "guest" |
| `multi_device_customer` | **One person, phone + laptop** | **The anti-leakage family**: `customer_distinct_devices > 1` must not mean "attack" |
| `household_shared_device` | Several people on one device | The inverse relationship |
| `persistent_card_problem_customer` | Real shopper, card genuinely failing, **with earlier successful visits** | The friction case Blind v1.1 punished worst |
| `network_retry_storm` | Flaky connection retries | Failures with a non-instrument cause |
| `shared_network_customer` | Campus / office egress | Shared-IP false positives |
| `flash_sale_customer` | Genuine sale traffic | Campaign bursts |
| `mobile_network_churn` | Mobile connectivity, IPs change constantly | IP-rotation false positives |
| `subscription_dunning` | Retry schedule over days | Long-gap legitimate failures |
| `long_dormant_returner` | Returns after a long inactive gap | Real device age, no recent history |
| `micro_payment_customer` | Small repeated top-ups | Low-amount legitimate velocity |

## 6. Attack population

| Family | Tradecraft |
|---|---|
| `fast_burst` | Many attempts in seconds |
| `slow_drip` | Steady, unhurried attempts inside one session |
| `patient_tester_weeks` | A few attempts per visit, visits days apart, over weeks |
| `sparse_multiday_tester` | One or two attempts a day for many days |
| `cross_device_campaign` | One campaign across several devices, **linked by a shared account or IP** |
| `session_churn` | Heavy session rotation |
| `merchant_typical_amounts` | Ordinary merchant amounts throughout |
| `warm_up_then_test` | Genuine-looking phase, then a switch |
| `flash_sale_camouflage` | Hides inside real campaign bursts |
| `successful_card_camouflage` | Mixes working cards and completed checkouts into the run |

**On `cross_device_campaign`.** In Blind v1.1 this family was unlearnable by
construction: the campaign shared no identifier the feature vector could key
on. v3 makes it linkable through a shared customer or a shared IP — not to
make it easy, but so the question "can a customer-scoped feature find it?"
has a defined answer. A campaign that shares nothing is undetectable by any
merchant-side system, and a benchmark full of them measures nothing.

---

## 7. Deliberate overlap

Every signal Model v2 intends to use must be produced by a legitimate family
too. This table is a **generation requirement**, not commentary:

| Signal | Attack family raising it | Legitimate family that must also raise it |
|---|---|---|
| customer on several devices | `cross_device_campaign` | `multi_device_customer` |
| long-horizon attempt/failure counts | `patient_tester_weeks`, `sparse_multiday_tester` | `persistent_card_problem_customer`, `subscription_dunning` |
| many active days | `sparse_multiday_tester` | `returning_customer_multi_episode` |
| many distinct IPs | `cross_device_campaign` | `mobile_network_churn`, `shared_network_customer` |
| `customer_id` absent | `fast_burst`, `session_churn` | `cold_start_guest` |
| `customer_id` present | `patient_tester_weeks`, `cross_device_campaign` | every logged-in family |
| completed checkouts before failures | `warm_up_then_test`, `successful_card_camouflage` | `persistent_card_problem_customer` |

Latent parameter ranges overlap between populations by construction. A
patient tester and an unlucky returning shopper can draw the same
`method_validity`, the same cadence and the same episode structure.

---

## 8. Gates

All must pass before Dataset v3 is usable.

**Lifecycle** — unique event ids; no orphan outcomes; no checkout without an
approval; outcome strictly after its request; no card or outcome metadata on
any request; per-device `(timestamp, event_sequence)` never regresses;
deterministic replay; no non-finite feature.

**Bookkeeping (new)** — every labelled device must appear in `raw_events`.
Blind v1.1 labelled 109 attack devices that never transacted; that silently
corrupts every denominator.

**Merchant realization (new)** — every declared merchant kind must have at
least one merchant instance and at least one device.

**Customer structure (new)**
- customers owning more than one device exist in **both** populations;
- neither population supplies more than 85% of the multi-device customers;
- a customer never spans the train/validation boundary.

**`customer_id` presence (new)**
- overall presence in `[0.55, 0.75]`;
- `|P(present | attack) - P(present | legitimate)| <= 0.15`;
- presence alone must not separate the populations: max F1 of the presence
  flag as a single classifier `<= 0.65`.

**Long-horizon realism (new)** — in both populations, at least 15% of devices
must have an activity span over 3 days, so 7d/30d features have something to
measure on both sides.

**Leakage** — shuffled-label ROC-AUC `<= 0.60`; no single contract feature
above F1 `0.85`; legitimate/attack overlap coefficient `>= 0.25`.

**Composition** — every declared family present with enough devices and
requests; no family dominating its population's requests.

**Outcome realism** — legitimate aggregate decline rate inside `[0.05, 0.35]`,
warning outside `[0.10, 0.28]`.

**Separation** — train and validation share **no** device, customer, session,
request, event or IP identifier, and `max(train timestamp) < min(validation
timestamp)`.

---

## 9. What v3 deliberately does not do

- It does not make attacks trivially separable. Every new mechanism has a
  legitimate counterpart (Section 7).
- It does not inject any feature value, tenure count or success count as an
  actor attribute. Everything emerges from events.
- It does not model anything a merchant cannot see before authorization.
- It does not replace or modify Dataset V2, and it is not a blind set.

---

## 10. Revision history

| Revision | Date | Change |
|---|---|---|
| v3 | 2026-08-31 | Initial specification, written before the generator |
